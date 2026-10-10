/* Workspace de calibración: canvas con handles de malla.
 *
 * Por qué Alpine y fetch acá, y HTMX en los paneles: el canvas necesita el
 * estado de la malla en el cliente igual (arrastre, nudge, zoom), así que
 * intercambiar HTML desde el servidor dejaría dos copias del mismo estado
 * desincronizándose. En los paneles que son solo formularios, HTMX sigue siendo
 * lo más simple.
 *
 * Convención de puntos (ADR-015): normalizados 0..1, origen arriba a la
 * izquierda, orden fila-mayor. Una malla de cols x rows celdas tiene
 * (cols+1) * (rows+1) puntos.
 */

function workspace(config) {
  return {
    // --- estado ---
    surfaces: config.surfaces || [],
    activeId: null,
    activeHandle: null,
    // Capa elegida: sus parametros ocupan el panel de abajo. Vive en el
    // cliente porque el servidor no tiene por que saber que estas mirando.
    layerId: null,
    aviso: null,
    status: config.status,
    ws: false,
    saving: false,
    error: null,
    previewUrl: config.previewUrl,
    cameraStream: config.cameraStream,
    output: config.output, // {width, height}

    // Homografía cámara -> proyector, de la auto-calibración. Con ella el
    // canvas puede mostrar lo que ve la cámara y dejar marcar la superficie
    // sobre el objeto real, que es más intuitivo que hacerlo sobre la salida
    // del proyector (US-25).
    homography: config.homography || null,
    vista: 'proyector', // o 'camara'
    // Tamaño en que se estimó la homografía: el hilo de visión procesa
    // reducido, así que los píxeles de la H no son los del stream.
    camaraSize: config.cameraSize || [320, 240],
    calib: { running: false, progress: 0, stage: '', ok: null, message: '', rms: null, inliers: 0, coverage: 0 },
    // Error de reproyección a partir del cual no hay que confiar en la
    // homografía: una calibración mala es peor que ninguna, porque todo lo que
    // se dibuje sobre la cámara cae corrido sin que se note hasta proyectar.
    rmsWarn: config.rmsWarn || 2.0,

    // El arrastre manda muchas posiciones por segundo; se limita el ritmo hacia
    // el servidor y siempre se manda una última al soltar, para no perder el
    // valor final (ver ADR-004: cada PUT escribe en disco).
    sendEvery: 100,
    zoomSize: 140, // igual que .zoom en app.css
    lastSent: 0,
    pendingSend: null,

    get puedeVerCamara() {
      return this.homography !== null;
    },

    get fondo() {
      return this.vista === 'camara' ? this.cameraStream : this.previewUrl;
    },

    alternarVista() {
      if (!this.puedeVerCamara) return;
      this.vista = this.vista === 'proyector' ? 'camara' : 'proyector';
      this.activeHandle = null;
      this.draw();
    },

    // --- transformación entre vistas ---
    //
    // Los puntos se guardan SIEMPRE en coordenadas de proyector: es lo único
    // que el render entiende. En vista de cámara se transforman solo para
    // dibujarlos y para interpretar el arrastre, nunca para guardarlos.

    aplicarH(H, p) {
      const [x, y] = p;
      const w = H[2][0] * x + H[2][1] * y + H[2][2];
      if (Math.abs(w) < 1e-9) return p;
      return [
        (H[0][0] * x + H[0][1] * y + H[0][2]) / w,
        (H[1][0] * x + H[1][1] * y + H[1][2]) / w,
      ];
    },

    invertirH(H) {
      // Inversa de 3x3 por cofactores: son nueve números, no justifica una
      // biblioteca.
      const [[a, b, c], [d, e, f], [g, h, i]] = H;
      const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
      if (Math.abs(det) < 1e-12) return null;
      return [
        [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
        [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
        [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
      ];
    },

    // proyector normalizado -> cámara normalizada, para dibujar
    aVista(p) {
      if (this.vista === 'proyector' || !this.homography) return p;
      const inv = this.invertirH(this.homography);
      if (!inv) return p;
      const px = this.aplicarH(inv, [p[0] * this.output.width, p[1] * this.output.height]);
      return [px[0] / this.camaraSize[0], px[1] / this.camaraSize[1]];
    },

    // cámara normalizada -> proyector normalizado, para guardar
    deVista(p) {
      if (this.vista === 'proyector' || !this.homography) return p;
      const px = this.aplicarH(this.homography, [
        p[0] * this.camaraSize[0],
        p[1] * this.camaraSize[1],
      ]);
      return [px[0] / this.output.width, px[1] / this.output.height];
    },

    get active() {
      return this.surfaces.find((s) => s.id === this.activeId) || null;
    },

    get subdivisionLabel() {
      const s = this.active;
      return s ? `${s.mesh_cols}×${s.mesh_rows}` : '—';
    },

    init() {
      if (this.surfaces.length) this.activeId = this.surfaces[0].id;
      this.connect();
      this.$nextTick(() => this.draw());
      new ResizeObserver(() => this.draw()).observe(this.$refs.stage);
      window.addEventListener('keydown', (e) => this.onKey(e));

      // El orden de las capas se cambia arrastrando. Hay que volver a
      // engancharlo después de cada swap de HTMX: el <ol> es nuevo cada vez.
      this.engancharOrden();
      this.engancharOrdenCaras();
      this.preseleccionarEfecto();
      document.body.addEventListener('htmx:afterSwap', () => this.engancharOrden());
    },

    // --- telemetría ---
    connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const socket = new WebSocket(`${proto}://${location.host}/ws/telemetry`);
      socket.onopen = () => { this.ws = true; };
      socket.onclose = () => {
        this.ws = false;
        setTimeout(() => this.connect(), 2000);
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'status') this.status = msg;
        if (msg.ev === 'calib') this.onCalib(msg);
      };
    },

    // --- orden de las capas ---
    //
    // Con flechas hacía falta un viaje al servidor por cada posición, y en el
    // celular los botones quedaban diminutos. Arrastrando se ve el resultado
    // mientras se mueve.

    engancharOrden() {
      const lista = document.getElementById('layers-sortable');
      if (!lista || typeof Sortable === 'undefined') return;
      if (lista._sortable) lista._sortable.destroy();

      lista._sortable = Sortable.create(lista, {
        // Solo las capas: el <li> del mensaje "esta cara no tiene capas" no
        // es arrastrable ni sirve de destino.
        draggable: 'li[data-id]',
        handle: '.tirador',
        animation: 150,
        ghostClass: 'arrastrando',
        // Siempre el modo de respaldo, tambien en escritorio: la API nativa
        // de drag-and-drop del navegador no existe para el dedo, asi que con
        // ella el comportamiento seria distinto en el celular que en la
        // laptop. Uno solo es mas facil de ajustar y de probar.
        forceFallback: true,
        // El dedo necesita un instante de presión antes de arrastrar, o cada
        // intento de hacer scroll mueve una capa.
        delay: 120,
        delayOnTouchOnly: true,
        onEnd: () => this.guardarOrden(lista),
      });
    },

    async guardarOrden(lista) {
      // El orden del DOM **ya es** el orden nuevo, y están todas las capas de
      // la escena aunque solo se vean las de la cara activa: las ocultas se
      // quedaron donde estaban. El backend exige la lista completa.
      const ids = [...lista.querySelectorAll('li[data-id]')].map((li) => Number(li.dataset.id));
      if (!ids.length) return;
      try {
        await this.api('PUT', `/api/scenes/${lista.dataset.scene}/layers/order`, {
          layer_ids: ids,
        });
      } catch (e) {
        // El servidor manda; si rechazó el orden, se recarga el fragmento
        // para no dejar la pantalla mintiendo.
        if (window.htmx) htmx.ajax('GET', '/api/scenes/panel', '#scenes');
      }
    },

    // --- vuelta desde la pagina de efectos ---

    preseleccionarEfecto() {
      // Al guardar un efecto nuevo se vuelve acá con `?efecto=<id>`. Dejarlo
      // elegido en el formulario de capa ahorra buscarlo en la lista, que es
      // lo único que uno quiere hacer justo después de crearlo.
      const id = new URLSearchParams(location.search).get('efecto');
      if (!id) return;
      const select = document.querySelector('.nueva-capa select[name=effect_id]');
      if (select && [...select.options].some((o) => o.value === id)) {
        select.value = id;
        this.aviso = 'Efecto «' + id + '» listo para usar: elegí una cara y agregá la capa.';
      }
      // Se limpia la URL: recargar no deberia volver a avisar de algo viejo.
      history.replaceState({}, '', location.pathname);
    },

    // --- orden de las caras ---
    //
    // La tira es la navegacion entre caras: el canvas muestra una por vez.
    // Poder ordenarlas como estan fisicamente —de izquierda a derecha segun
    // se ve el objeto— es la diferencia entre buscar y señalar.
    //
    // No cambia lo que se proyecta: el apilado lo decide el z_order de las
    // capas. Por eso no se le avisa al render.

    engancharOrdenCaras() {
      const tira = this.$refs.strip;
      if (!tira || typeof Sortable === 'undefined') return;

      Sortable.create(tira, {
        // Los chips los genera un `x-for`, que deja su <template> como primer
        // hijo. Sin esto, Sortable lo trataria como un elemento mas.
        draggable: '[data-id]',
        handle: '.tirador',
        animation: 150,
        ghostClass: 'arrastrando',
        forceFallback: true,
        delay: 120,
        delayOnTouchOnly: true,
        onEnd: (evt) => this.guardarOrdenCaras(tira, evt),
      });
    },

    async guardarOrdenCaras(tira, evt) {
      if (evt.oldIndex === evt.newIndex) return;
      const previo = [...this.surfaces];
      const ids = [...tira.querySelectorAll('[data-id]')].map((el) => Number(el.dataset.id));
      if (ids.length !== previo.length) return;

      // Se deshace el movimiento de Sortable **antes** de tocar el array, y
      // moviendo un solo nodo: la inversa exacta de lo que hizo.
      //
      // Los chips los pinta un `x-for`. Si el DOM se mueve por un lado y el
      // array por el otro, Alpine reordena sobre lo ya movido y la tira
      // termina como estaba, o peor: reusa mal sus nodos y deja uno vacio.
      // El array manda; el DOM lo pinta Alpine.
      const sinItem = [...tira.querySelectorAll('[data-id]')].filter((el) => el !== evt.item);
      tira.insertBefore(evt.item, sinItem[evt.oldIndex] || null);

      this.surfaces = ids.map((id) => previo.find((s) => s.id === id)).filter(Boolean);

      try {
        await this.api('PUT', '/api/surfaces/order', { surface_ids: ids });
      } catch (e) {
        this.surfaces = previo;
      }
    },

    // --- blackout ---
    //
    // Apagar y prender la proyección es lo que más se toca durante un montaje,
    // así que vive sobre el preview y no dentro de un panel plegado. Es un
    // interruptor y nada más: no arrastra el efecto global, que es otra cosa.

    get blackout() {
      return !!this.status.blackout;
    },

    async toggleBlackout() {
      const nuevo = !this.status.blackout;
      // Se pinta el estado nuevo sin esperar la respuesta: el ida y vuelta es
      // de milisegundos, pero un botón de apagado que tarda en reaccionar se
      // toca dos veces.
      this.status = { ...this.status, blackout: nuevo };
      try {
        await this.api('POST', '/api/system/blackout', { on: nuevo });
      } catch (e) {
        this.status = { ...this.status, blackout: !nuevo };
      }
    },

    // --- auto-calibración ---
    //
    // La corre el render, que es quien tiene proyector y cámara. Acá solo se
    // dispara y se sigue el progreso: la secuencia son decenas de patrones y
    // tarda varios segundos, así que el POST devuelve 202 y el resultado llega
    // por el WebSocket.

    async autoCalibrar() {
      if (!confirm('Durante la secuencia el proyector muestra patrones en blanco y negro, no el efecto. Tarda unos segundos. ¿Seguir?')) return;
      this.calib = { running: true, progress: 0, stage: 'arrancando', ok: null, message: '' };
      try {
        await this.api('POST', '/api/calibration/auto', {});
      } catch (e) {
        this.calib.running = false;
      }
    },

    onCalib(msg) {
      if (!msg.done) {
        this.calib = { ...this.calib, running: true, progress: msg.progress || 0, stage: msg.stage || '' };
        return;
      }
      this.calib = {
        running: false,
        progress: 1,
        stage: 'terminada',
        ok: !!msg.ok,
        message: msg.msg || '',
        rms: msg.rms ?? null,
        inliers: msg.inliers || 0,
        coverage: msg.coverage || 0,
      };
      if (msg.ok && msg.homography) {
        this.homography = msg.homography;
        if (msg.camera_size) this.camaraSize = msg.camera_size;
      } else if (this.vista === 'camara') {
        // Si falló, la vista de cámara mostraría puntos en cualquier parte.
        this.vista = 'proyector';
      }
      this.draw();
    },

    async cancelarCalibracion() {
      try {
        await this.api('DELETE', '/api/calibration/auto');
      } catch (e) { /* el estado real llega por el WebSocket */ }
    },

    get calibDudosa() {
      return this.calib.ok === true && this.calib.rms !== null && this.calib.rms > this.rmsWarn;
    },

    get calibResumen() {
      const c = this.calib;
      if (c.ok === null) return this.homography ? 'calibrada en una corrida anterior' : 'sin calibrar';
      if (!c.ok) return c.message;
      const base = `error ${c.rms.toFixed(2)} px · ${c.inliers} puntos · cubre ${(c.coverage * 100).toFixed(0)}% del cuadro`;
      return this.calibDudosa
        ? `${base} — por encima de ${this.rmsWarn} px: conviene ajustar las caras a mano`
        : base;
    },

    // --- API ---
    async api(method, url, body) {
      this.error = null;
      const res = await fetch(url, {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        const detalle = await res.json().catch(() => ({}));
        this.error = detalle.detail || `${method} ${url}: ${res.status}`;
        throw new Error(this.error);
      }
      return res.status === 204 ? null : res.json();
    },

    async addSurface() {
      const name = prompt('Nombre de la cara', `cara ${this.surfaces.length + 1}`);
      if (!name) return;
      const creada = await this.api('POST', '/api/surfaces', { name });
      this.surfaces.push(creada);
      this.activeId = creada.id;
      this.draw();
    },

    async removeSurface() {
      const s = this.active;
      if (!s || !confirm(`¿Borrar "${s.name}"?`)) return;
      await this.api('DELETE', `/api/surfaces/${s.id}`);
      this.surfaces = this.surfaces.filter((x) => x.id !== s.id);
      this.activeId = this.surfaces.length ? this.surfaces[0].id : null;
      this.draw();
    },

    async toggleSurface() {
      const s = this.active;
      if (!s) return;
      const actualizada = await this.api('PATCH', `/api/surfaces/${s.id}`, { enabled: !s.enabled });
      Object.assign(s, actualizada);
      this.draw();
    },

    async resetSurface() {
      const s = this.active;
      if (!s || !confirm('¿Volver a la malla regular a pantalla completa?')) return;
      Object.assign(s, await this.api('POST', `/api/surfaces/${s.id}/reset`));
      this.activeHandle = null;
      this.draw();
    },

    async subdivide(event) {
      const s = this.active;
      if (!s) return;
      const [cols, rows] = event.target.value.split('x').map(Number);
      // Bajar la resolución descarta los ajustes finos de los puntos
      // interiores: se avisa antes, no después.
      const bajando = cols < s.mesh_cols || rows < s.mesh_rows;
      if (bajando && !confirm('Bajar la subdivisión descarta los ajustes de los puntos interiores. ¿Seguir?')) {
        event.target.value = `${s.mesh_cols}x${s.mesh_rows}`;
        return;
      }
      Object.assign(s, await this.api('POST', `/api/surfaces/${s.id}/subdivide`, { cols, rows }));
      this.activeHandle = null;
      this.draw();
    },

    async savePoints(force) {
      const s = this.active;
      if (!s) return;
      const ahora = performance.now();
      clearTimeout(this.pendingSend);
      if (!force && ahora - this.lastSent < this.sendEvery) {
        this.pendingSend = setTimeout(() => this.savePoints(true), this.sendEvery);
        return;
      }
      this.lastSent = ahora;
      this.saving = true;
      try {
        await this.api('PUT', `/api/surfaces/${s.id}/points`, { points: s.points });
      } finally {
        this.saving = false;
      }
    },

    // --- canvas ---
    rect() {
      return this.$refs.canvas.getBoundingClientRect();
    },

    toCanvas(p) {
      const r = this.rect();
      const v = this.aVista(p);
      return [v[0] * r.width, v[1] * r.height];
    },

    fromEvent(event) {
      const r = this.rect();
      const enVista = [
        Math.min(1.2, Math.max(-0.2, (event.clientX - r.left) / r.width)),
        Math.min(1.2, Math.max(-0.2, (event.clientY - r.top) / r.height)),
      ];
      // Se guarda en coordenadas de proyector, siempre.
      return this.deVista(enVista);
    },

    draw() {
      const canvas = this.$refs.canvas;
      if (!canvas) return;
      const r = this.rect();
      // Se dibuja en píxeles reales del dispositivo: en un celular, un canvas
      // escalado por CSS se ve borroso justo donde hace falta precisión.
      const dpr = window.devicePixelRatio || 1;
      canvas.width = r.width * dpr;
      canvas.height = r.height * dpr;
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, r.width, r.height);

      // Solo la cara en la que se está trabajando. Dibujar todas encima del
      // mismo preview las mezclaba visualmente: con dos o tres caras
      // superpuestas no se distingue qué malla es cuál, y los handles de una
      // caen sobre las líneas de otra. Se trabaja una por vez; la tira de
      // abajo cambia de cara.
      if (this.active) this.drawMesh(ctx, this.active, true);
    },

    drawMesh(ctx, surface, activa) {
      const ancho = surface.mesh_cols + 1;
      const pts = surface.points.map((p) => this.toCanvas(p));

      ctx.lineWidth = activa ? 1.5 : 1;
      ctx.strokeStyle = activa ? 'rgba(0, 230, 200, 0.9)' : 'rgba(255, 255, 255, 0.25)';
      if (!surface.enabled) ctx.strokeStyle = 'rgba(255, 120, 120, 0.4)';

      ctx.beginPath();
      for (let y = 0; y <= surface.mesh_rows; y++) {
        for (let x = 0; x <= surface.mesh_cols; x++) {
          const i = y * ancho + x;
          if (x < surface.mesh_cols) {
            ctx.moveTo(...pts[i]);
            ctx.lineTo(...pts[i + 1]);
          }
          if (y < surface.mesh_rows) {
            ctx.moveTo(...pts[i]);
            ctx.lineTo(...pts[i + ancho]);
          }
        }
      }
      ctx.stroke();

      if (!activa) return;
      pts.forEach((p, i) => {
        const esquina = this.isCorner(surface, i);
        const activo = i === this.activeHandle;
        ctx.beginPath();
        ctx.arc(p[0], p[1], activo ? 9 : esquina ? 7 : 4.5, 0, Math.PI * 2);
        ctx.fillStyle = activo ? '#00e6c8' : esquina ? '#ffffff' : 'rgba(255,255,255,0.55)';
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = 'rgba(0,0,0,0.7)';
        ctx.stroke();
      });
    },

    isCorner(surface, i) {
      const ancho = surface.mesh_cols + 1;
      const ultimo = surface.points.length - 1;
      return i === 0 || i === ancho - 1 || i === ultimo - ancho + 1 || i === ultimo;
    },

    nearestHandle(pos) {
      const s = this.active;
      if (!s) return null;
      const [cx, cy] = this.toCanvas(pos);
      let mejor = null;
      let mejorDist = 22; // radio de agarre en píxeles, generoso para el dedo
      s.points.forEach((p, i) => {
        const [px, py] = this.toCanvas(p);
        const d = Math.hypot(px - cx, py - cy);
        if (d < mejorDist) {
          mejorDist = d;
          mejor = i;
        }
      });
      return mejor;
    },

    onPointerDown(event) {
      const pos = this.fromEvent(event);
      const handle = this.nearestHandle(pos);
      if (handle === null) return;
      this.activeHandle = handle;
      this.$refs.canvas.setPointerCapture(event.pointerId);
      this.dragging = true;
      this.draw();
    },

    onPointerMove(event) {
      if (!this.dragging || this.activeHandle === null) return;
      const s = this.active;
      s.points[this.activeHandle] = this.fromEvent(event);
      this.draw();
      this.savePoints(false);
    },

    onPointerUp(event) {
      if (!this.dragging) return;
      this.dragging = false;
      this.$refs.canvas.releasePointerCapture(event.pointerId);
      this.savePoints(true); // la última posición siempre se guarda
    },

    onKey(event) {
      if (this.activeHandle === null || !this.active) return;
      const paso = event.shiftKey ? 10 : 1; // píxeles de salida, no de pantalla
      const delta = {
        ArrowLeft: [-paso, 0],
        ArrowRight: [paso, 0],
        ArrowUp: [0, -paso],
        ArrowDown: [0, paso],
      }[event.key];
      if (!delta) return;
      event.preventDefault();
      const p = this.active.points[this.activeHandle];
      // El nudge se define en píxeles de la salida del proyector: mover "1 px"
      // tiene que significar lo mismo sin importar el tamaño del canvas.
      this.active.points[this.activeHandle] = [
        p[0] + delta[0] / this.output.width,
        p[1] + delta[1] / this.output.height,
      ];
      this.draw();
      this.savePoints(true);
    },

    // Recuadro ampliado de la esquina activa: sin esto el último píxel se
    // ajusta a ciegas.
    zoomStyle() {
      if (this.activeHandle === null || !this.active) return 'display:none';
      const p = this.active.points[this.activeHandle];
      const r = this.rect();
      // La ampliación se calcula sobre el tamaño **mostrado** del preview, no
      // sobre la resolución de salida: la imagen va estirada al stage, así que
      // usar 1920 o 640 descoloca el recuadro.
      const escala = 4;
      const ancho = r.width * escala;
      const alto = r.height * escala;
      const medio = this.zoomSize / 2;
      return [
        `background-image:url('${this.previewUrl}')`,
        `background-size:${ancho}px ${alto}px`,
        `background-position:${-p[0] * ancho + medio}px ${-p[1] * alto + medio}px`,
      ].join(';');
    },
  };
}
