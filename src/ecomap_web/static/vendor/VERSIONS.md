# Assets vendorizados

Servidos desde `static/`, nunca desde un CDN: la Pi puede estar sin internet (ADR-002).

| Archivo | Version | Origen |
|---|---|---|
| `htmx.min.js` | 2.0.4 | cdnjs.cloudflare.com/ajax/libs/htmx/2.0.4/htmx.min.js |
| `htmx-ext-json-enc.js` | 2.0.2 | cdn.jsdelivr.net/npm/htmx-ext-json-enc@2.0.2/json-enc.js |
| `alpine.min.js` | 3.14.8 | cdnjs.cloudflare.com/ajax/libs/alpinejs/3.14.8/cdn.min.js |
| `pico.min.css` | 2.0.6 | cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css |
| `sortable.min.js` | 1.15.6 | cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.6/Sortable.min.js |

`sortable.min.js` reordena las capas arrastrando. Se usa una biblioteca y no la API
nativa de drag-and-drop del navegador porque esa **no funciona con el dedo**, y el
dashboard se usa desde el celular parado frente al objeto.

Para actualizar: `bash scripts/fetch-vendor.sh` y anotar la version nueva aca.
