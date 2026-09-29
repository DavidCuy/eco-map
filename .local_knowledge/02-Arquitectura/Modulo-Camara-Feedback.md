---
tags: [arquitectura, vision, camara]
---

# Módulo Cámara / Retroalimentación

La cámara cumple **tres** funciones distintas. Conviene no mezclarlas.

## 1. Auto-calibración (offline, unos segundos)

Objetivo: saber qué píxel de cámara corresponde a qué píxel de proyector.

Secuencia **Gray code**:
1. Proyectar negro y blanco → imagen de referencia y máscara de área iluminada.
2. Proyectar ~11 patrones verticales + 11 horizontales (y sus inversos).
3. Por píxel de cámara, decodificar el código → coordenada de proyector.
4. `cv2.findHomography` con RANSAC sobre las correspondencias → `H_cam→proj`.

Alternativa rápida y más tolerante: proyectar un tablero **ArUco/ChArUco** y usar `cv2.aruco`. Menos preciso, 1 frame, buen fallback.

Requisitos: cámara fija y luz ambiente baja. Si el RMS del ajuste supera un umbral, la UI lo dice y sugiere calibración manual.

## 2. Verificación / auto-corrección (periódica)

Con `H` conocida, el sistema puede:
- **Comprobar deriva**: si alguien movió el proyector, el patrón ya no cae donde debe → alerta en el dashboard.
- **Auto-exposición de proyección**: medir luminancia real reflejada y ajustar brillo/gamma por superficie (una pared blanca y una madera oscura no necesitan el mismo nivel).
- **Compensación de color** (v2): medir el color de la superficie y precompensar.

## 3. Efectos reactivos (tiempo real, cada frame)

Pipeline barato, a 15–20 fps, en resolución reducida (320×240):
```
frame → gris → blur → diferencia con fondo (MOG2) → umbral →
contornos → área total = u_motion ; centroide = u_motion_pos
```
Se publican como uniforms al render. **No** se hace detección de personas ni ML en v1: no da el presupuesto de CPU. Ver [[Presupuesto-de-Rendimiento]].

Riesgo real: **lazo de realimentación positiva** — la cámara ve la proyección, eso genera movimiento, el efecto crece, la cámara ve más. Mitigaciones: restar el frame proyectado conocido (usando `H`), banda muerta en el umbral, y suavizado temporal (EMA) de `u_motion`.

## Implementación

- **Cámara web USB** vía `cv2.VideoCapture` con `CAP_V4L2` y fourcc MJPG. Única fuente soportada en v1, por presupuesto. Interfaz `CameraSource` para poder sumar CSI en v2. Ver [[ADR-010-Camara-USB]].
- Captura a 640×480 @ 15 fps; **reducción por CPU** a 320×240 para el pipeline de movimiento (sin CSI no hay stream `lores` gratis del ISP). Presupuestado en [[Presupuesto-de-Rendimiento]].
- Corre como hilo dentro de `ecomap-render`: comparte el contexto GL y sube la textura sin copias entre procesos. Cola de 1 frame, drop-oldest.
- El dispositivo se monta en el contenedor desde `/dev/v4l/by-id/...`, no desde `/dev/video0`: el índice cambia entre arranques. Ver [[Docker-Local]].
- Sin cámara física (desarrollo en escritorio) se usa `FakeSource`: reproduce un mp4 o genera patrones. Todo el flujo de visión es desarrollable sin hardware.
- El stream para la UI se sirve desde el web como MJPEG a 5 fps y tamaño reducido: es para **apuntar** la cámara, no para monitorear.

## Limitaciones propias de una webcam

- Auto-exposición y auto-balance hay que apagarlos durante el Gray code; no todas las webcams obedecen los controles V4L2. Si no obedecen, la UI lo detecta (varianza entre frames idénticos) y sugiere calibración manual.
- Ruido alto en penumbra → más frames de asentamiento por patrón y umbral adaptativo.
- Latencia USB + decodificación JPEG: ~60–100 ms. Irrelevante para calibración, perceptible en efectos reactivos muy rápidos.

Relacionado: [[Modulo-Calibracion]] · [[Camara]] · [[Modulo-Efectos]] · [[ADR-010-Camara-USB]]
