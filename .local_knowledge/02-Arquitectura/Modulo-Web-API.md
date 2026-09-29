---
tags: [arquitectura, backend, frontend]
---

# Módulo Web / API

## Stack recomendado

**FastAPI + Jinja2 + HTMX + Alpine.js + Pico.css.** Sin build step, sin Node, sin npm. Total del front: ~45 KB gzip servidos localmente. Justificación completa en [[ADR-002-HTMX-Alpine]].

Reparto de trabajo:

- **Jinja2** — render de páginas y fragmentos en el servidor.
- **HTMX** — CRUD y navegación: `hx-post`, `hx-swap` de fragmentos. Cero JS para formularios.
- **Alpine.js** — estado local de la vista de calibración (arrastre de esquinas en `<canvas>`, sliders, preview).
- **WebSocket nativo** — telemetría y push de estado (fps, temperatura, escena activa).
- **Pico.css** — estilos sin clases, tema oscuro por defecto (se opera a oscuras, al lado del proyector).

## Rutas de páginas

| Ruta | Pantalla |
|---|---|
| `/` | Dashboard: escena activa, fps, temp, botón blackout |
| `/surfaces` | Lista y alta de superficies |
| `/surfaces/{id}/calibrate` | Editor de calibración (canvas + handles) |
| `/effects` | Catálogo de efectos con preview |
| `/scenes` | Escenas: crear, activar, duplicar |
| `/scenes/{id}` | Editor: capas, orden, parámetros |
| `/camera` | Vista de cámara, auto-calibración, ajuste de detección |
| `/settings` | Resolución, fps objetivo, escena de arranque |
| `/settings/network` | Estado de red, escaneo wifi, conexión, modo AP. Ver [[Modulo-Red]] |

API JSON en [[Contratos-API]].

## Estructura de la app

```
app/
  main.py            # FastAPI, lifespan: abre UDS y conexión SQLite
  deps.py            # dependencias (db session, bus IPC)
  routers/
    pages.py         # HTML (Jinja2 + fragmentos HTMX)
    surfaces.py  effects.py  scenes.py  camera.py  system.py  network.py
    ws.py            # /ws/telemetry
  schemas/           # Pydantic v2
  services/          # lógica: calibración, escenas, catálogo, red
  repo/              # acceso SQLite (sqlite3 o SQLModel)
  bus.py             # cliente UDS hacia el render
  templates/  static/  # htmx, alpine y pico servidos localmente, sin CDN
```

## Convenciones

- Endpoints que la UI consume devuelven **fragmento HTML** si la cabecera `HX-Request` está presente, JSON si no. Un solo router, dos representaciones.
- Toda mutación pasa por `services/`, nunca desde el router directo a SQLite.
- El acceso a SQLite es síncrono y corto; se ejecuta en threadpool (`def` en vez de `async def` en el handler) para no bloquear el loop.
- El único módulo que habla con el host (D-Bus / NetworkManager) es `services/network.py`. Nada más sale del contenedor. Ver [[Modulo-Red]].
- Los assets del front se sirven desde `static/`, nunca desde un CDN: la Pi puede estar sin internet. Ver [[ADR-002-HTMX-Alpine]].

Relacionado: [[Arquitectura-General]] · [[Modulo-Calibracion]] · [[Modulo-Red]] · [[Seguridad-y-Red]]
