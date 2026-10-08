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

Única implementación de producción: **`OpenCVSource`**. Se saca `picamera2` del alcance de v1 y del `pyproject.toml`. Se conserva la interfaz `CameraSource` para poder agregar CSI en v2 sin refactor.

El backend va **en el esquema de la URI** y no se adivina: `v4l2://` en Linux, `dshow://` o `msmf://` en Windows. OpenCV elige uno solo si no se le dice cuál, y cuál elige cambia entre instalaciones: con eso, la misma cámara da 30 fps en un equipo y 10 en otro sin que nada lo explique.

```python
cap = cv2.VideoCapture(dev, api)   # api: CAP_V4L2 | CAP_DSHOW | CAP_MSMF
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 15)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("M", "J", "P", "G"))
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
```

**El orden importa, y es al revés de lo que parece.** Medido con DirectShow sobre una webcam real: pidiendo MJPG primero y el tamaño después, el driver entrega **YUY2** — cambiar el tamaño renegocia el formato y se pierde lo pedido. Con la resolución primero, entrega MJPG. Era un bug silencioso: nada fallaba, solo se capturaba sin comprimir.

Por eso `OpenCVSource` expone `fourcc`: lo que el driver **entrega**, no lo que se pidió. Donde no hay `v4l2-ctl` —es decir, en Windows— es la única forma de verlo, y el dashboard lo muestra con un aviso cuando no es MJPG.

Implementaciones: `OpenCVSource` (producción) y `FakeSource` (tests y desarrollo sin cámara: reproduce un mp4 o genera patrones sintéticos).

## Consecuencias y costos

- **Hay que redimensionar por CPU.** Sin el ISP de la CSI no existe el stream `lores` gratis: se captura a 640x480 y se reduce a 320x240 con `cv2.resize` para el pipeline de movimiento. Costo estimado: ~10 % de un core. Presupuestado en [[Presupuesto-de-Rendimiento]].
- **MJPEG obligatorio** como fourcc. La decodificación JPEG cuesta CPU, pero YUYV sin comprimir satura el ancho de banda USB y cae a pocos fps.
- **Auto-exposición y auto-balance hay que apagarlos** para el Gray code (`CAP_PROP_AUTO_EXPOSURE`, `CAP_PROP_AUTO_WB`). No todas las webcams respetan estos controles, así que `set_auto_exposure()` **relee la propiedad** y devuelve tres resultados distintos: `aplicado`, `ignorado` (quedó en otro valor) y `sin_confirmar` (el driver devuelve −1 y no hay forma de saberlo desde OpenCV). Tratar los dos últimos como lo mismo manda a buscar un problema de cámara donde puede no haberlo.
- **El número mágico del modo manual no es el mismo en cada backend**: V4L2 usa el enum de su API (`1` manual, `3` automático) y DirectShow su propia convención (`0.25` manual, `0.75` automático). Mandar el valor de uno al otro deja la cámara en automático sin que nada falle.
- **Abrir tarda.** Medido con DirectShow: ~4,5 s. Por eso el hilo de cámara abre **dentro del hilo** y no en `start()`: antes el loop de render esperaba, y cambiar de cámara congelaba la proyección esos segundos. El render publica `opening` y después el desenlace.
- **En Windows la cámara se direcciona por índice**, no por ruta: no hay nada equivalente a `/dev/v4l/by-id`, así que el índice puede cambiar al enchufar otra cámara. Es parte de por qué el appliance va sobre la Pi.
- **`BUFFERSIZE=1` no siempre funciona**: si la latencia crece, el hilo de captura descarta frames llamando `grab()` sin `retrieve()`.
- El índice del dispositivo cambia entre arranques → montar la ruta persistente `/dev/v4l/by-id/...`, no `/dev/video0`.
- Bus USB 2.0 compartido en Pi 4: no colgar la webcam del mismo controlador que un SSD USB si se puede evitar.
- Calidad óptica pobre y ruido alto en penumbra: el umbralizado de Gray code necesita más margen y más frames de asentamiento que con una CSI.

## Alternativas descartadas

- **Pi Camera Module 3 + picamera2** — mejor técnicamente, pero cuesta dinero y obliga a `--system-site-packages` y a contenerizar libcamera. Análisis original en [[ADR-008-Camara-Picamera2]]. Candidata natural para v2.

Relacionado: [[Modulo-Camara-Feedback]] · [[Camara]]
