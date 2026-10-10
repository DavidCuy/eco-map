/* Página de efectos: subir un archivo y verlo antes de guardarlo.
 *
 * La previsualización de la imagen reproduce **lo que hace el shader**, no una
 * animación parecida: el mismo desplazamiento con `fract` y el mismo ángulo en
 * grados. Si acá se ve de una forma y proyectado de otra, el control no sirve
 * para decidir nada.
 */

function catalogo() {
  return {
    archivo: null,
    nombre: '',
    kind: null,
    speed: 0.1,
    angle: 0,
    subiendo: false,
    error: null,
    _imagen: null,
    _animacion: null,

    elegir(evento) {
      const archivo = evento.target.files[0];
      if (!archivo) return;
      this.archivo = archivo;
      this.error = null;
      this.kind = this.tipoDe(archivo.name);
      if (!this.nombre.trim()) {
        // Un nombre por defecto a partir del archivo: casi siempre es el que
        // la persona iba a escribir igual.
        this.nombre = archivo.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
      }

      if (this.kind === 'image') this.previsualizarImagen(archivo);
      else if (this.kind) this.previsualizarVideo(archivo);
      else this.error = 'Ese tipo de archivo no se puede usar como efecto.';
    },

    tipoDe(nombre) {
      const ext = (nombre.split('.').pop() || '').toLowerCase();
      if (['jpg', 'jpeg', 'png', 'webp', 'bmp'].includes(ext)) return 'image';
      if (ext === 'gif') return 'gif';
      if (['mp4', 'webm', 'mov', 'm4v'].includes(ext)) return 'video';
      return null;
    },

    previsualizarVideo(archivo) {
      this.detener();
      // Un gif no se puede poner en un <video>: va como imagen animada. Los
      // dos se ven igual de bien en un <img>, así que se usa eso para gif.
      const url = URL.createObjectURL(archivo);
      const video = this.$refs.video;
      if (this.kind === 'gif') {
        video.poster = url;
        video.removeAttribute('src');
        video.style.background = `center / contain no-repeat url(${url})`;
      } else {
        video.style.background = '';
        video.src = url;
      }
    },

    previsualizarImagen(archivo) {
      this.detener();
      const imagen = new Image();
      imagen.onload = () => {
        this._imagen = imagen;
        this.animar();
      };
      imagen.onerror = () => { this.error = 'No se pudo leer la imagen.'; };
      imagen.src = URL.createObjectURL(archivo);
    },

    animar() {
      const lienzo = this.$refs.lienzo;
      const ctx = lienzo.getContext('2d');
      const inicio = performance.now();

      const cuadro = (ahora) => {
        const imagen = this._imagen;
        if (!imagen) return;
        const t = (ahora - inicio) / 1000;

        // Mismo tamaño que el elemento, en píxeles reales.
        const r = lienzo.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        lienzo.width = r.width * dpr;
        lienzo.height = r.height * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        // El shader hace `fract(uv + dir * speed * t)` sobre una textura que
        // se repite. Acá es lo mismo: un patrón repetido, desplazado. El
        // signo de y va invertido porque en el canvas crece hacia abajo y en
        // GL hacia arriba.
        const a = (this.angle * Math.PI) / 180;
        const dx = -Math.cos(a) * this.speed * t * r.width;
        const dy = Math.sin(a) * this.speed * t * r.height;

        const patron = ctx.createPattern(imagen, 'repeat');
        const escalaX = r.width / imagen.width;
        const escalaY = r.height / imagen.height;
        patron.setTransform(new DOMMatrix([escalaX, 0, 0, escalaY, 0, 0]));

        ctx.save();
        ctx.translate(dx % r.width, dy % r.height);
        ctx.fillStyle = patron;
        // Se pinta mas grande que el lienzo y desplazado hacia atras: asi no
        // queda un borde vacio mientras el patron se mueve.
        ctx.fillRect(-r.width, -r.height, r.width * 3, r.height * 3);
        ctx.restore();

        this._animacion = requestAnimationFrame(cuadro);
      };
      this._animacion = requestAnimationFrame(cuadro);
    },

    detener() {
      if (this._animacion) cancelAnimationFrame(this._animacion);
      this._animacion = null;
      this._imagen = null;
    },

    async guardar() {
      this.subiendo = true;
      this.error = null;
      const cuerpo = new FormData();
      cuerpo.append('archivo', this.archivo);
      cuerpo.append('nombre', this.nombre.trim());
      // Van en la misma subida y quedan como los valores por defecto del
      // efecto: es parte de cómo se definió, no un ajuste de una capa.
      if (this.kind === 'image') {
        cuerpo.append('speed', this.speed);
        cuerpo.append('angle', this.angle);
      }

      try {
        const res = await fetch('/api/effects/upload', { method: 'POST', body: cuerpo });
        if (!res.ok) {
          const detalle = await res.json().catch(() => ({}));
          throw new Error(detalle.detail || `error ${res.status}`);
        }
        const { effect } = await res.json();

        // De vuelta al dashboard: guardar un efecto es el final de una tarea,
        // y lo que sigue es usarlo.
        window.location.href = '/?efecto=' + encodeURIComponent(effect.id);
      } catch (e) {
        this.error = e.message;
        this.subiendo = false;
      }
    },
  };
}
