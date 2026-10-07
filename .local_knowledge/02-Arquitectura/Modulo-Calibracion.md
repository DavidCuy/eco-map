---
tags: [arquitectura, calibracion]
---

# Módulo Calibración

Define **dónde** cae cada efecto en el mundo físico. Dos modos: manual y asistido por cámara.

**Una superficie por cara física** ([[ADR-015-Superficie-por-Cara-y-Malla]]). No se mapea el objeto,
se mapean sus caras: dos cajas apiladas con tres caras visibles cada una son hasta seis superficies
independientes. La UI tiene que hacer cómodo crear, duplicar, nombrar y saltar entre ellas.

**Toda superficie es una malla.** Un quad es la malla de 1×1 celda. No hay dos modos ni dos caminos
de render.

## Manual (siempre disponible)

UI: `<canvas>` con el preview de la proyección a escala y los handles de la malla arrastrables
(Alpine). Una superficie nueva arranca en 1×1 — cuatro esquinas — y se subdivide cuando hace falta.
Coordenadas **normalizadas 0..1** respecto del framebuffer de salida, así el cambio de resolución no
rompe la calibración.

Ayudas obligatorias en la UI:
- **Grilla de prueba** proyectada (ajedrez + números de esquina) mientras se calibra.
- **Nudge con teclado**: flechas = 1 px, Shift+flechas = 10 px. Arrastrar con mouse no alcanza para el último píxel.
- **Zoom de esquina**: recuadro amplificado del handle activo.
- **Bloquear aspecto** y **snap** a bordes de pantalla.

## Subdivisión de la malla

N×M configurable (1×1, 3×3, 5×5, 9×9). Al subir la resolución los puntos interiores se interpolan
con Catmull-Rom y después se editan a mano. Bajarla descarta ajustes y debe avisar.
Ver [[Warping-y-Homografia]].

## Asistida por cámara

Secuencia de auto-calibración, detalle en [[Modulo-Camara-Feedback]]:
1. Proyectar blanco → capturar → detectar el área iluminada (contorno).
2. Proyectar Gray code (h + v, ~20 frames) → mapa píxel-cámara → píxel-proyector.
3. Resolver homografía cámara↔proyector (`cv2.findHomography`, RANSAC).
4. El usuario dibuja la superficie **sobre la imagen de la cámara** (más intuitivo que sobre el proyector) y el sistema la transforma a coordenadas de proyector.

## Máscaras (opcional, post-v1)

Polígono libre por superficie, editable en el mismo canvas, aplicado como stencil en el render.

**Bajó de prioridad a propósito.** El derrame de luz alrededor del objeto no es un defecto: mientras
se calibra, muestra dónde caen los límites de la superficie. Las máscaras son una herramienta de
acabado para la instalación final, no un requisito de v1 ([[ADR-015-Superficie-por-Cara-y-Malla]]).

## Reglas de datos

- Los puntos se guardan normalizados y ordenados **TL, TR, BR, BL**.
- Cada edición guarda `updated_at`; la escena mantiene un `calibration_version` para invalidar cachés de matriz en el render.
- Exportar/importar calibración como JSON (respaldo antes de tocar el proyector).

Relacionado: [[Modulo-Render]] · [[Modelo-de-Datos]] · [[Casos-de-Uso]]
