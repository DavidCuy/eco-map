/* Parámetros en vivo.
 *
 * Por qué esto no es HTMX: cada respuesta de HTMX reemplaza el fragmento
 * entero, y reemplazar el DOM mientras el dedo arrastra el slider lo arranca
 * del control. Los formularios siguen con HTMX; un slider en movimiento es una
 * interacción, no un envío de formulario.
 *
 * Lo que se ve viaja siempre; lo que se guarda en disco lo difiere el servidor
 * (ADR-004).
 */

(function () {
  const THROTTLE_MS = 50; // RNF-2: el presupuesto total es 100 ms

  const estado = new WeakMap();

  // A donde van los valores. El panel lo declara: los del efecto global van a
  // un lado y los de una capa a otro, pero el control es el mismo y no tiene
  // por que saberlo.
  const DESTINO_POR_DEFECTO = '/api/effects/active/params';

  function destino(control) {
    const contenedor = control.closest('[data-params-url]');
    return contenedor ? contenedor.dataset.paramsUrl : DESTINO_POR_DEFECTO;
  }

  async function enviar(control) {
    const clave = control.dataset.param;
    const valor = leer(control);
    const t0 = performance.now();
    await fetch(destino(control), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: { [clave]: valor } }),
    });
    // Se expone para poder medir la latencia desde fuera sin instrumentar nada
    // más (ver la medición anotada en US-14).
    window.ecomapUltimaLatencia = performance.now() - t0;
  }

  function leer(control) {
    if (control.type === 'checkbox') return control.checked;
    if (control.type === 'color') return control.value;
    if (control.dataset.paramType === 'enum') return parseInt(control.value, 10);
    return parseFloat(control.value);
  }

  function programar(control) {
    const ahora = performance.now();
    const previo = estado.get(control) || { ultimo: 0, pendiente: null };
    clearTimeout(previo.pendiente);

    if (ahora - previo.ultimo >= THROTTLE_MS) {
      estado.set(control, { ultimo: ahora, pendiente: null });
      enviar(control);
      return;
    }
    // Siempre se manda una última al soltar: el valor final no se puede perder
    // por el throttle.
    previo.pendiente = setTimeout(() => {
      estado.set(control, { ultimo: performance.now(), pendiente: null });
      enviar(control);
    }, THROTTLE_MS);
    estado.set(control, previo);
  }

  function enlazar(raiz) {
    raiz.querySelectorAll('[data-param]').forEach((control) => {
      if (control.dataset.enlazado) return;
      control.dataset.enlazado = '1';
      // `input` y no `change`: change solo dispara al soltar, y el sentido de
      // esto es ver el efecto mientras se mueve.
      control.addEventListener('input', () => {
        const eco = control.parentElement.querySelector('[data-param-valor]');
        if (eco) eco.textContent = control.value;
        programar(control);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => enlazar(document));
  // Los paneles se intercambian por HTMX: hay que reenlazar lo que entra.
  document.body.addEventListener('htmx:afterSwap', (e) => enlazar(e.target));
})();
