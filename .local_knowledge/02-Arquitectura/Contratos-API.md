---
tags: [arquitectura, api]
---

# Contratos de API

Prefijo `/api`. Todo Pydantic v2. OpenAPI automático en `/docs`.

## Superficies

Una superficie por cada cara física, y toda superficie es una malla ([[ADR-015-Superficie-por-Cara-y-Malla]]).

```
GET    /api/surfaces
POST   /api/surfaces                 {name, mesh_cols?, mesh_rows?}   -> 201
GET    /api/surfaces/{id}
PATCH  /api/surfaces/{id}            {name?, opacity?, enabled?}
PUT    /api/surfaces/{id}/points     {points: [[x,y],...]}
POST   /api/surfaces/{id}/subdivide  {cols, rows}
POST   /api/surfaces/{id}/reset      # malla regular a pantalla completa
DELETE /api/surfaces/{id}            -> 204
```

**Convención de puntos**: normalizados 0..1, origen arriba a la izquierda, **orden fila-mayor**.
Una malla de `cols` × `rows` celdas tiene `(cols+1) × (rows+1)` puntos; para 1×1 el orden es
TL, TR, BL, BR. Se acepta salirse un poco del rango (hasta -1..2): al calibrar a veces hay que tirar
una esquina fuera de pantalla.

`kind` es **derivado**, no se elige: `quad` cuando la malla es 1×1, `mesh` en cualquier otro caso.

Una cantidad de puntos que no corresponde a la subdivisión devuelve **422**, igual que un cuerpo que
no valida.

`subdivide` conserva la forma: al subir la resolución los puntos nuevos se interpolan con
Catmull-Rom, así que la superficie se refina sin deformarse. Al bajarla se pierden los ajustes
finos.

## Efectos

```
GET    /api/effects                  [{id, name, version, tags, needs_camera, cost,
                                       params, available, error}]
POST   /api/effects/active           {id, params?}   -> {id, params}
PUT    /api/effects/active/params    {params: {...}}  # mezcla parcial
POST   /api/effects/active/reset     # descarta los overrides
POST   /api/effects/reload           # re-escanea el disco y recompila
GET    /api/effects/{id}/preview     # JPEG desde el volumen de efectos
```

Los efectos que no cargan aparecen igual en el listado: esconderlos haría que un efecto que
desapareció parezca que nunca existió. Hay **dos** banderas, porque hay dos formas de fallar:

- `available: false` — el manifiesto es inválido o el directorio ya no está. Lo detecta el web.
- `compiled: false` + `error` — el shader no compila con el driver actual. Lo detecta el render.

`PUT /active/params` es **mezcla parcial**: lo que no viene, no se toca. Solo se guardan los
overrides sobre el default del manifiesto, así que `reset` los **descarta** en vez de copiar los
defaults: si el efecto cambia de versión, se hereda solo.

`POST /active` responde con lo que el web **aceptó**. Si el shader no compila, el
render lo desmiente después por el bus y el motivo queda en
`SystemStatus.effect_error`. Mismo criterio que con la cámara: quien puede fallar
de verdad es quien ejecuta.

## Escenas y capas

```
GET    /api/scenes
POST   /api/scenes                   {name}
POST   /api/scenes/{id}/activate     # cambia lo que se proyecta AHORA
POST   /api/scenes/{id}/default      # escena de arranque
POST   /api/scenes/{id}/duplicate

POST   /api/scenes/{id}/layers       {surface_id, effect_id, z_order?, blend_mode?}
PATCH  /api/layers/{id}              {z_order?, blend_mode?, enabled?}
PUT    /api/layers/{id}/params       {speed: 0.7, color_a: "#00ffc8"}   # merge parcial
DELETE /api/layers/{id}
```

## Sistema y calibración

```
GET    /api/system/status            {fps, frame_ms, cpu_temp, scene_id, render_up}
POST   /api/system/blackout          {on: true}
POST   /api/calibration/auto         {method: "graycode"}   -> 202 + task_id
GET    /api/calibration/auto/{task_id}

GET    /api/camera/devices           [{uri, name, label, kind, node, stable_path}]
GET    /api/camera/status            {state, source, width, height, fps, backend, message}
POST   /api/camera/select            {source: "v4l2:///dev/v4l/by-id/..."}
GET    /api/camera/stream            # MJPEG 5 fps (Hito 4)
GET    /api/camera/snapshot          # JPEG (Hito 4)
POST   /api/config/export            # descarga JSON completo
POST   /api/config/import
```

## Red

Detalle y flujo de rollback en [[Modulo-Red]].

```
GET    /api/network/status           {mode, ssid, ip, signal, internet, ap_active}
POST   /api/network/scan             -> 202, escaneo asíncrono (3-8 s)
GET    /api/network/networks         [{ssid, signal, security, saved, in_use}]
POST   /api/network/connect          {ssid, psk?, hidden?}  -> 202 + check_token
GET    /api/network/confirm          ?token=...   # el cliente confirma; cancela el rollback
POST   /api/network/forget           {ssid}
POST   /api/network/ap               {on: true|false}
```

`connect` **nunca** devuelve 200 con la conexión ya hecha: devuelve 202 y el cliente debe reconectarse a la red nueva y llamar a `confirm`. Sin confirmación en 90 s, se revierte solo. La `psk` no se devuelve nunca, ni aparece en logs.

## WebSocket `/ws/telemetry`

Servidor → cliente, 2 Hz:
```json
{"type":"tele","fps":59.4,"frame_ms":16.8,"temp":54.1,"dropped":0,"scene_id":3}
{"type":"log","level":"warn","msg":"shader plasma: compile error line 12"}
{"type":"calib","progress":0.45,"stage":"graycode_v"}
```

## Protocolo IPC web → render (socket UDS, JSON por línea)

```json
{"op":"scene",   "scene": { ...escena serializada completa... }}
{"op":"param",   "layer": 12, "key": "speed", "value": 0.7}
{"op":"points",  "surface": 3, "points": [[0.1,0.1], ...]}
{"op":"blackout","on": true}
{"op":"pattern", "name": "grid"}
{"op":"camera",  "source": "v4l2:///dev/v4l/by-id/usb-XXXX-video-index0"}
{"op":"effect",  "id": "grid_test", "params": {"cells": 24}}
{"op":"effects_reload"}
{"op":"scene",   "scene": {"calibration_version": 7, "surfaces": [
                   {"id": 1, "cols": 1, "rows": 1, "points": [[0.3,0.2], ...], "opacity": 1.0}]}}
{"op":"ping"}
```
Render → web:
```json
{"ev":"tele","fps":59.4,"frame_ms":16.8,"temp":54.1}
{"ev":"error","source":"shader","effect":"plasma","msg":"..."}
{"ev":"calib","progress":0.45,"stage":"graycode_v"}
{"ev":"camera","state":"open","source":"fake://","width":640,"height":480,"fps":15.0,"backend":"fake"}
{"ev":"effects","compiled":["grid_test","solid"],"errors":{"plasma":"line 12: syntax error"}}
```

### Estados de cámara

`state` tiene cuatro valores y el orden importa:

| Estado | Significado |
|---|---|
| `closed` | sin cámara seleccionada, o guardada mientras el render está caído |
| `opening` | el web mandó la orden y espera el evento del render |
| `open` | abierta de verdad, con resolución y fps reales |
| `error` | no se pudo abrir; `message` dice por qué |

`opening` existe por una razón concreta: el render responde unos milisegundos
después, así que si `POST /select` devolviera el estado guardado, la UI mostraría
el error de la cámara que se acaba de descartar.

Sin versionado de protocolo en v1: ambos procesos se despliegan juntos. Ver [[ADR-006-IPC-Web-Render]].

Relacionado: [[Modulo-Web-API]] · [[Modelo-de-Datos]]
