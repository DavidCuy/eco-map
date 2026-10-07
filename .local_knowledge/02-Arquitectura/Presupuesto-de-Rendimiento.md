---
tags: [arquitectura, rendimiento]
---

# Presupuesto de rendimiento

Objetivo: **16.6 ms por frame** (60 fps); 33 ms (30 fps) aceptable con partículas. Dos plataformas
soportadas, con cuellos distintos. Ver [[ADR-013-Plataforma-Agnostica]].

| | Mini PC (N3350) | Raspberry Pi 4 |
|---|---|---|
| CPU | 2 núcleos Goldmont 1.1–2.4 GHz | 4 núcleos Cortex-A72 1.5 GHz |
| GPU | HD 500, 12 EUs @650 MHz | VideoCore VI |
| Cuello esperado | **CPU** | **fillrate de GPU** |

En la mini PC hay más margen de GPU pero la mitad de núcleos, así que el riesgo se mueve: el hilo
de cámara ([[Modulo-Camara-Feedback]]), que decodifica MJPEG y redimensiona por CPU, pasa a competir
con el loop de render y con el web. Ninguna de las dos columnas está medida todavía en `kms`:
los números de abajo son presupuesto, no observación. Qué medir: [[Mini-PC-Setup]].

## Reparto en Pi 4 (1080p)

| Etapa | Presupuesto | Nota |
|---|---|---|
| Efectos (todas las capas) | 8 ms | FBO por capa, al bounding box de su superficie (implementado en US-13) |
| Warp + compose + máscaras | 3 ms | geometría trivial, limitado por fillrate |
| Swap / vsync | — | bloqueante |
| Cámara: captura + decodificación MJPEG | ~25 % de un core | webcam USB 640×480 @ 15 fps |
| Cámara: resize a 320×240 + motion | ~15 % de un core | sin ISP hay que reducir por CPU. Ver [[ADR-010-Camara-USB]] |
| FastAPI + SQLite | < 5 % CPU en reposo | |
| Docker (overhead) | despreciable en CPU | ~100 MB de disco por imagen |

## Reglas que salen de esto

1. **Fillrate es el cuello, no la CPU.** El V3D de la Pi 4 sufre con shaders caros a pantalla completa. Bajar la resolución del FBO es la palanca más efectiva.
2. Máximo **4 capas simultáneas** en Pi 4; 8 en Pi 5.
3. Nada de leer el framebuffer a CPU por frame (`glReadPixels` mata el pipeline). El preview para la web es un render aparte a 5 fps y 480×270.
4. Cámara a 320×240. Subir la textura con PBO / `GL_UNPACK` directo, sin pasar por numpy si se puede.
5. `vcgencmd measure_temp` en telemetría: con >80 °C hay throttling y se pierden frames. Ver [[Raspberry-Pi-Setup]].
6. Medir siempre con `frame_ms` real, no con fps promedio: el jitter es lo que se ve.

## Degradación automática

Si `frame_ms` > 2× objetivo durante 3 s: escalar FBOs a 0.75 → 0.5 y avisar en la UI. Nunca bajar la resolución de **salida** (rompería la calibración visual).

Relacionado: [[Modulo-Render]] · [[Modulo-Efectos]] · [[Casos-de-Uso]]
