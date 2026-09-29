---
tags: [arquitectura, calibracion]
---

# Módulo Calibración

Define **dónde** cae cada efecto en el mundo físico. Dos modos: manual y asistido por cámara.

## Manual (siempre disponible)

UI: `<canvas>` con el preview de la proyección a escala + 4 handles arrastrables (Alpine). Coordenadas **normalizadas 0..1** respecto del framebuffer de salida, así el cambio de resolución no rompe la calibración.

Ayudas obligatorias en la UI:
- **Grilla de prueba** proyectada (ajedrez + números de esquina) mientras se calibra.
- **Nudge con teclado**: flechas = 1 px, Shift+flechas = 10 px. Arrastrar con mouse no alcanza para el último píxel.
- **Zoom de esquina**: recuadro amplificado del handle activo.
- **Bloquear aspecto** y **snap** a bordes de pantalla.

## Malla (superficies no planas)

Subdivisión N×M (3×3, 5×5, 9×9). Los puntos interiores se interpolan con Catmull-Rom al crear la malla y luego se editan a mano. Ver [[Warping-y-Homografia]].

## Asistida por cámara

Secuencia de auto-calibración, detalle en [[Modulo-Camara-Feedback]]:
1. Proyectar blanco → capturar → detectar el área iluminada (contorno).
2. Proyectar Gray code (h + v, ~20 frames) → mapa píxel-cámara → píxel-proyector.
3. Resolver homografía cámara↔proyector (`cv2.findHomography`, RANSAC).
4. El usuario dibuja la superficie **sobre la imagen de la cámara** (más intuitivo que sobre el proyector) y el sistema la transforma a coordenadas de proyector.

## Máscaras

Polígono libre por superficie, editable en el mismo canvas. Se aplica como stencil en el render. Sirve para no derramar luz fuera del objeto (clave en fachadas).

## Reglas de datos

- Los puntos se guardan normalizados y ordenados **TL, TR, BR, BL**.
- Cada edición guarda `updated_at`; la escena mantiene un `calibration_version` para invalidar cachés de matriz en el render.
- Exportar/importar calibración como JSON (respaldo antes de tocar el proyector).

Relacionado: [[Modulo-Render]] · [[Modelo-de-Datos]] · [[Casos-de-Uso]]
