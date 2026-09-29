---
tags: [hardware, proyector]
---

# Proyector

## Qué importa (en orden)

1. **Lúmenes ANSI reales** — no "lúmenes LED". Para interior a oscuras, 500–1000 ANSI alcanza. Con luz ambiente, 2500+.
2. **Throw ratio** — determina la distancia para el tamaño deseado: `distancia = throw_ratio × ancho`. Corto alcance (<1.0) salva instalaciones apretadas.
3. **Resolución nativa 1080p.** Un proyector 720p que "acepta 1080p" escala y arruina el detalle fino de las máscaras.
4. **Keystone y lens shift físicos** — cuanto más se corrija en óptica, menos píxeles se pierden en el warp digital. **Poner el keystone del proyector en 0** y hacer la corrección en el software; si no, se deforma dos veces.
5. **Latencia / modo juego** — si hay efectos reactivos, la latencia del proyector se suma a la del pipeline.

## Configuración obligatoria antes de calibrar

- Keystone/corrección automática: **apagada**.
- Modo de imagen: el más neutro (no "dinámico"/"vívido").
- Overscan: apagado.
- Sleep/standby automático: apagado.
- Resolución de entrada fija 1920×1080 @ 60 Hz.

Cualquier cambio en estos ajustes **invalida la calibración**. Anotarlos en la escena.

## Montaje

Fijo y rígido. Un proyector que se mueve 2 mm descalibra visiblemente. La detección de deriva por cámara ([[Modulo-Camara-Feedback]]) avisa, pero no lo arregla.

Relacionado: [[Modulo-Calibracion]] · [[Raspberry-Pi-Setup]]
