# Assets vendorizados

Servidos desde `static/`, nunca desde un CDN: la Pi puede estar sin internet (ADR-002).

| Archivo | Version | Origen |
|---|---|---|
| `htmx.min.js` | 2.0.4 | cdnjs.cloudflare.com/ajax/libs/htmx/2.0.4/htmx.min.js |
| `htmx-ext-json-enc.js` | 2.0.2 | cdn.jsdelivr.net/npm/htmx-ext-json-enc@2.0.2/json-enc.js |
| `alpine.min.js` | 3.14.8 | cdnjs.cloudflare.com/ajax/libs/alpinejs/3.14.8/cdn.min.js |
| `pico.min.css` | 2.0.6 | cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css |

Para actualizar: `bash scripts/fetch-vendor.sh` y anotar la version nueva aca.
