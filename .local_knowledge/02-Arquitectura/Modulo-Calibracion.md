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

## Asistida por cámara (implementada)

La corre el **render**, que es el único proceso con proyector y cámara. El web la dispara
(`POST /api/calibration/auto` → 202), sigue el progreso por el WebSocket y guarda el resultado en la
tabla `calibration`. Es asíncrona a propósito: son decenas de patrones y varios segundos, y un POST
que esperara daría timeout justo cuando va bien.

Secuencia (`src/ecomap_vision/graycode.py`, `src/ecomap_render/calibration.py`):

1. **Blanco y negro de referencia.** Sin ellos habría que elegir un umbral de brillo absoluto, que
   no funciona igual en una pared blanca que en madera. Un píxel entra solo si el contraste
   blanco−negro supera `min_contrast`; eso es lo que separa el área proyectada del fondo de la sala.
2. **Gray code en x y en y, cada patrón con su inverso.** Un píxel es 1 si se ve más claro en el
   patrón que en su inverso — comparación relativa, sin umbral. Gray y no binario común porque entre
   dos valores consecutivos cambia un solo bit: un píxel en el borde de una franja cae en la columna
   vecina, no al otro extremo de la pantalla.
3. **Correspondencias** cámara→proyector, submuestreadas (`step`).
4. `cv2.findHomography` con RANSAC → `H`, error RMS de reproyección e inliers.

El usuario después dibuja la superficie **sobre la imagen de la cámara** y la UI la transforma a
coordenadas de proyector con `H⁻¹`. Los puntos se guardan **siempre** en coordenadas de proyector:
es lo único que el render entiende. La vista de cámara solo cambia cómo se dibujan y cómo se
interpreta el arrastre.

### Dos relojes que no coinciden

El render dibuja a 30 o 60 fps; la cámara captura a 15, con su buffer de driver y su latencia USB.
Por eso **no se cuentan frames de render** para esperar: se espera a que avance el *número de
secuencia de la cámara*, que es la única señal de que llegó un frame nuevo de verdad. Cuántos hace
falta descartar tras cambiar el patrón es el parámetro `settle`, y su valor justo depende del
hardware ([[Limitaciones-por-Hardware]]).

### El pliegue del Gray code

Con menos bits que los que pide el ancho hay que **agrupar píxeles en bloques** (`2**shift`), no
truncar el código. Un Gray *reflejado* al que le faltan los bits altos se pliega sobre sí mismo: el
decodificador devuelve una columna espejada, y como el espejo es consistente para toda una franja de
la imagen, RANSAC la acepta como respuesta válida.

Así se veía el bug: `rms = 0.69 px`, 283 inliers — y la homografía invertida, con las esquinas a
1093 px de la verdad. **Un error de reproyección bajo no prueba que la calibración sea correcta**,
solo que es internamente consistente. Lo encontró el [[Banco-Virtual-Proyector-Camara]], que es el
único que puede comparar contra la respuesta conocida.

Con bloques: 640 columnas con 8 bits son bloques de 4 px, precisión de sobra para una homografía, y
las franjas finas de 4 px sobreviven mejor a una cámara mediocre que las de 1 px.

### Se decodifica el frame completo

El hilo de visión reduce a 320×240 para detectar movimiento; la calibración usa el frame **sin
reducir**. Un `resize` con `INTER_AREA` promedia los bordes de las franjas finas, que es exactamente
lo que arruina la decodificación. Son ~34 frames una sola vez, no por cuadro.

## Máscaras (opcional, post-v1)

Polígono libre por superficie, editable en el mismo canvas, aplicado como stencil en el render.

**Bajó de prioridad a propósito.** El derrame de luz alrededor del objeto no es un defecto: mientras
se calibra, muestra dónde caen los límites de la superficie. Las máscaras son una herramienta de
acabado para la instalación final, no un requisito de v1 ([[ADR-015-Superficie-por-Cara-y-Malla]]).

## Reglas de datos

- Los puntos se guardan normalizados 0..1, con origen arriba a la izquierda, en **orden
  fila-mayor**: la fila de arriba de izquierda a derecha, después la siguiente. Para una malla 1×1
  eso da TL, TR, BL, BR. Es el orden que generaliza a cualquier subdivisión.
- Cada edición guarda `updated_at`; la escena mantiene un `calibration_version` para invalidar cachés de matriz en el render.
- Exportar/importar calibración como JSON (respaldo antes de tocar el proyector).

Relacionado: [[Modulo-Render]] · [[Modelo-de-Datos]] · [[Casos-de-Uso]] · [[Banco-Virtual-Proyector-Camara]]
