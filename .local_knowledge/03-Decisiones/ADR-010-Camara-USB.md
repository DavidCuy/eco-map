---
tags: [adr, camara, vision]
estado: aceptada
fecha: 2026-09-26
reemplaza: ADR-008-Camara-Picamera2
---

# ADR-010 — Cámara web USB como único hardware soportado en v1

**Estado:** aceptada · **Fecha:** 2026-09-26 · **Reemplaza a** [[ADR-008-Camara-Picamera2]]

## Contexto

Restricción de presupuesto: se usa una **cámara web USB** ya disponible, no un módulo CSI. Además todo debe correr en contenedores ([[ADR-009-Todo-en-Contenedores]]), y `picamera2` era precisamente la dependencia que lo complicaba.

## Decisión

Única implementación de producción: **`OpenCVSource`** con `cv2.VideoCapture(dev, cv2.CAP_V4L2)`. Se saca `picamera2` del alcance de v1 y del `pyproject.toml`. Se conserva la interfaz `CameraSource` para poder agregar CSI en v2 sin refactor.

```python
cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("M", "J", "P", "G"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 15)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
```

Implementaciones: `OpenCVSource` (producción) y `FakeSource` (tests y desarrollo sin cámara: reproduce un mp4 o genera patrones sintéticos).

## Consecuencias y costos

- **Hay que redimensionar por CPU.** Sin el ISP de la CSI no existe el stream `lores` gratis: se captura a 640x480 y se reduce a 320x240 con `cv2.resize` para el pipeline de movimiento. Costo estimado: ~10 % de un core. Presupuestado en [[Presupuesto-de-Rendimiento]].
- **MJPEG obligatorio** como fourcc. La decodificación JPEG cuesta CPU, pero YUYV sin comprimir satura el ancho de banda USB y cae a pocos fps.
- **Auto-exposición y auto-balance hay que apagarlos** para el Gray code (`CAP_PROP_AUTO_EXPOSURE`, `CAP_PROP_AUTO_WB`). No todas las webcams respetan estos controles: si no responden, la UI avisa y ofrece calibración manual.
- **`BUFFERSIZE=1` no siempre funciona**: si la latencia crece, el hilo de captura descarta frames llamando `grab()` sin `retrieve()`.
- El índice del dispositivo cambia entre arranques → montar la ruta persistente `/dev/v4l/by-id/...`, no `/dev/video0`.
- Bus USB 2.0 compartido en Pi 4: no colgar la webcam del mismo controlador que un SSD USB si se puede evitar.
- Calidad óptica pobre y ruido alto en penumbra: el umbralizado de Gray code necesita más margen y más frames de asentamiento que con una CSI.

## Alternativas descartadas

- **Pi Camera Module 3 + picamera2** — mejor técnicamente, pero cuesta dinero y obliga a `--system-site-packages` y a contenerizar libcamera. Análisis original en [[ADR-008-Camara-Picamera2]]. Candidata natural para v2.

Relacionado: [[Modulo-Camara-Feedback]] · [[Camara]]
