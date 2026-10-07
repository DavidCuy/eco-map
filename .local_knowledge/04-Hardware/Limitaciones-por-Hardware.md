---
tags: [hardware, verificacion]
---

# Limitaciones por hardware

Lo que **no** se puede verificar sin proyector, cámara USB y el equipo real. El registro vivo es el
**issue #33** de GitHub; esta nota explica el criterio, no la lista.

## El criterio

Todo lo que se pueda verificar sin hardware, se verifica — y se deja la medición escrita:

- Render headless con llvmpipe en contenedor ([[Docker-Local]]).
- Cámara simulada: `fake://` con patrón sintético o con un archivo de video.
- [[Banco-Virtual-Proyector-Camara]] (`loopback://`) para el lazo proyector→cámara con homografía
  conocida.
- Inspección a nivel píxel de los snapshots MJPEG.
- Chrome DevTools para la interacción real de la UI.

Lo que queda fuera se anota en el #33 **con el issue que lo originó**, y el issue original se cierra:
quedarse abierto esperando hardware no agrega información, el comentario sí.

## Lo que ningún simulador reproduce

- **Exposición y ganancia automáticas** de una webcam que ignora los controles. Es la causa número
  uno de que una auto-calibración falle: el brillo cambia entre capturas y los patrones dejan de ser
  comparables con sus inversos.
- **Tiempo de asentamiento real** entre proyectar y capturar (`settle`): buffer del driver, latencia
  USB, refresco del proyector.
- **Ruido de un sensor barato** en penumbra, que es la condición normal de una instalación.
- **Térmica y throttling** del equipo bajo carga sostenida.
- **Latencia de entrada del proyector** y su efecto en el lazo de realimentación óptica.

Relacionado: [[Camara]] · [[Proyector]] · [[Modulo-Calibracion]] · [[Presupuesto-de-Rendimiento]]
