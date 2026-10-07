---
tags: [adr, camara, vision]
estado: reemplazada
fecha: 2026-09-26
---

# ADR-008 — Cámara: picamera2 (CSI) con fallback OpenCV (USB)

**Estado:** REEMPLAZADA · **Fecha:** 2026-09-26

> [!warning] Reemplazada por [[ADR-010-Camara-USB]] el 2026-09-26.
> Se conserva por el análisis de alternativas; no refleja la decisión vigente.

## Contexto
La retroalimentación necesita frames con baja latencia y bajo costo de CPU, en una Pi ya cargada. El usuario puede tener cámara CSI (Raspberry Pi Camera) o una webcam USB.

## Decisión
Interfaz `CameraSource` con dos implementaciones:
- **`Picamera2Source`** — cámara CSI en Raspberry Pi OS Bookworm. Stream `lores` en YUV420 a 320×240 para procesamiento y `main` a 640×480 para el preview web.
- **`OpenCVSource`** — `cv2.VideoCapture` con `CAP_V4L2`, MJPG como fourcc y `CAP_PROP_BUFFERSIZE=1`.

Selección por configuración, con autodetección al arrancar.

## Razones
- picamera2 usa libcamera y entrega el stream de baja resolución **sin costo extra de CPU** (lo produce el ISP). Con OpenCV habría que capturar grande y reducir por software.
- Las webcams USB son lo que la gente ya tiene; hay que soportarlas.
- Un solo consumidor con cola de 1 frame y descarte del viejo: nunca acumular latencia.

## Costo de la decisión
`picamera2` no se instala limpio desde PyPI (depende de `libcamera`, compilado contra el sistema). Se instala con `apt install python3-picamera2` y el venv se crea con `--system-site-packages`. Esto ensucia el aislamiento del entorno — aceptado a cambio de no compilar libcamera. Ver [[ADR-003-uv]].

## Consecuencias
- El código de visión nunca importa `picamera2` a nivel de módulo: import perezoso dentro de la implementación, para que el desarrollo en escritorio no falle.
- Las pruebas usan una `FakeSource` que reproduce un video o imágenes sintéticas.

Relacionado: [[Modulo-Camara-Feedback]] · [[Camara]]
