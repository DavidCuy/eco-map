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

Riesgo real: **lazo de realimentación positiva** — la cámara ve la proyección, eso genera
movimiento, el efecto crece, la cámara ve más. Las mitigaciones implementadas, en dos lugares:

**En la detección** (`ecomap_vision/motion.py`), tres perillas ajustables desde la UI:

- **Banda muerta**: por debajo de un umbral el movimiento es cero. Corta el ruido de sensor y el
  titileo de la proyección.
- **Suavizado temporal (EMA)**: el valor no puede saltar de golpe, así que un pico no realimenta.
- **Fondo adaptativo lento**: un cambio de luz ambiente deja de contar al rato; una persona que
  pasa sí cuenta.

**En el efecto** (`camera_echo`), tres frenos más: `decay` siempre menor que 1 — el pasado se apaga
en vez de acumularse —, `gain` que limita cuánto aporta la cámara por frame, y saturación final con
`min()`.

Verificado sin hardware que el efecto **no crece solo**: 45 segundos con entrada en movimiento
constante, muestreando el brillo medio cada 5 s, dio 23–29 sin tendencia ascendente. Eso prueba que
el estado estacionario existe; que el lazo **óptico** no se dispare necesita proyector y cámara
apuntándose, y está en la checklist.

Queda pendiente la cuarta mitigación, que es la más fuerte: **restar el frame proyectado conocido**
usando la homografía de la auto-calibración (Hito 5).

## Selección de cámara

Puede haber más de una cámara conectada (webcam USB, cámara integrada del
equipo, y la simulada de desarrollo), así que el dashboard tiene un **selector**.
El reparto de responsabilidades es el mismo que en el resto del sistema:

- **El web enumera.** Lee `/sys/class/video4linux/video*/{name,index}`, sin abrir
  ningún device ni depender de OpenCV. Se queda con los nodos de `index` 0:
  una webcam expone varios (`video0` captura, `video1` metadatos) y solo el
  primero sirve. Es una heurística, no una consulta de capacidades V4L2 — y
  alcanza, porque el error real lo reporta quien abre.
- **El render abre.** Es el proceso que tiene el device montado y el contexto GL
  donde va a vivir la textura. Reporta por el bus el estado real: resolución,
  fps y backend efectivos, o el mensaje de error.
- **La URI se guarda, no el índice.** Se prefiere `/dev/v4l/by-id/...`, que no
  cambia entre arranques (ADR-010). Queda persistida en `setting.camera` y se
  reenvía al render en cada reconexión.

Una cámara que no se puede abrir **no corta la proyección**: el render queda sin
cámara, avisa, y los efectos que piden `u_cam` reciben textura negra.

Estados y contrato en [[Contratos-API]].

## Medición del costo, que es lo que preocupa en dos núcleos

El hilo de visión publica su propio costo en la telemetría, porque es el riesgo
principal con la mini PC: captura, lectura, reducción y detección. Medido en desarrollo con
video simulado a 640×480:

| etapa | medido |
|---|---|
| captura | 15 fps |
| leer y decodificar | 0.3–0.6 ms |
| detectar movimiento | 0.35–0.8 ms |

Son números de un `FakeSource` leyendo un mp4: una webcam real decodifica MJPEG de verdad y va a
costar más. Está en la checklist de hardware.

## Realimentación en los efectos: `u_prev`

Un shader no tiene memoria: cada frame arranca de cero. Para que `camera_echo` pueda dejar estela,
una capa que declara `needs_feedback` en su manifiesto recibe **su propio frame anterior** en
`u_prev`, con ping-pong de dos texturas — dibujar y leer la misma textura en el mismo pase es
comportamiento indefinido.

Cuesta una textura y un FBO extra por capa, así que se pide explícitamente en vez de dárselo a
todas.

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
