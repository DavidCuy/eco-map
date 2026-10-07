---
tags: [arquitectura, api]
---

# Contratos de API

Prefijo `/api`. Todo Pydantic v2. OpenAPI automático en `/docs`.

## Superficies

```
GET    /api/surfaces
POST   /api/surfaces                 {name, kind, mesh_cols, mesh_rows}
GET    /api/surfaces/{id}
PATCH  /api/surfaces/{id}            {name?, opacity?, enabled?, mask?}
PUT    /api/surfaces/{id}/points     {points: [[x,y],...]}   # normalizado 0..1
DELETE /api/surfaces/{id}
POST   /api/surfaces/{id}/reset      # vuelve a quad full-screen
```

## Efectos

```
GET    /api/effects                  # catálogo con manifiestos
POST   /api/effects/reload           # re-escanea el directorio effects/
```

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
POST   /api/system/testpattern       {pattern: "grid"|"white"|"off"}
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
{"op":"ping"}
```
Render → web:
```json
{"ev":"tele","fps":59.4,"frame_ms":16.8,"temp":54.1}
{"ev":"error","source":"shader","effect":"plasma","msg":"..."}
{"ev":"calib","progress":0.45,"stage":"graycode_v"}
{"ev":"camera","state":"open","source":"fake://","width":640,"height":480,"fps":15.0,"backend":"fake"}
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
