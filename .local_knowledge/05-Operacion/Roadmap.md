---
tags: [roadmap, plan]
---

# Roadmap

Todos los hitos se desarrollan **sin hardware adicional**: contenedores en el escritorio, render headless con preview MJPEG y cámara simulada. El hardware se usa para validar, no para construir. Ver [[Docker-Local]] y [[ADR-009-Todo-en-Contenedores]].

## Hito 0 — Esqueleto (1 semana)
Repo con `pyproject.toml`/uv, Dockerfile multi-arch, los tres compose, migraciones y SQLite. Los cuatro volúmenes. FastAPI sirviendo el dashboard con Jinja2+HTMX+Pico. Render abriendo contexto GL y dibujando un triángulo. Bus UDS con `ping`/`pong`.
**Criterio:** `podman-compose -f compose.dev.yml up -d` levanta ambos y la UI muestra fps reales del render.
→ [[Estructura-Repositorio]] · [[ADR-003-uv]] · [[ADR-009-Todo-en-Contenedores]]

## Hito 1 — Caras calibrables (2–3 semanas)
CRUD de superficies, **una por cara física**. Canvas con handles de malla: 1×1 por defecto,
subdividible a 3×3, 5×5, 9×9. Warp por malla, con la homografía como cálculo de la celda 1×1.
Efectos `grid_test` y `solid`. Persistencia en SQLite. Dashboard rediseñado alrededor del canvas.
**Criterio:** mapear las tres caras visibles de una caja desde el celular y ver la grilla encajar en
cada una.
→ [[Modulo-Calibracion]] · [[Warping-y-Homografia]] · [[Direccion-de-UI]] · [[ADR-015-Superficie-por-Cara-y-Malla]]

Creció respecto del plan original: absorbe la malla, que estaba en el Hito 6, y el rediseño del
dashboard. La malla se adelantó porque mantener dos caminos de warp (quad y malla) es trabajo doble;
el rediseño, porque el canvas es la pantalla principal y no tiene sentido pintarla dos veces.

## Hito 2 — Efectos y escenas (2 semanas)
Volumen de efectos, catálogo sincronizado desde manifiestos, UI de parámetros autogenerada, capas, escenas, activación, escena de arranque. Efectos `plasma`, `waves`, `noise_flow`.
**Criterio:** cambiar un slider y ver el cambio proyectado en menos de 100 ms.
→ [[Modulo-Efectos]] · [[ADR-011-Archivos-vs-DB]] · [[Contratos-API]]

## Hito 3 — Red (1 semana)
`services/network.py` sobre `nmcli`, pantalla `/settings/network`, escaneo, conexión con rollback, AP de rescate, mDNS.
**Criterio:** llevar la Pi a una red nueva y configurarla entera desde el celular, sin teclado; y meter mal la clave a propósito sin quedarse sin acceso.
→ [[Modulo-Red]] · [[Seguridad-y-Red]]

## Hito 4 — Cámara (2 semanas)
`OpenCVSource` con webcam USB, `FakeSource` para desarrollo, preview MJPEG, detección de movimiento → `u_motion`. Efecto `camera_echo`.
**Criterio:** mover la mano frente a la superficie y que el efecto responda, sin que el lazo se realimente solo.
→ [[Modulo-Camara-Feedback]] · [[ADR-010-Camara-USB]]

## Hito 5 — Auto-calibración (2 semanas)
Gray code, homografía cámara↔proyector, dibujar superficies sobre la vista de cámara. Manejo de webcams que ignoran los controles manuales.
**Criterio:** una superficie calibrada automáticamente con error menor a 3 px.

## Hito 6 — Instalación real (1 semana)
Unit systemd, export/import de configuración, degradación automática por rendimiento, límites de log.
**Criterio:** el equipo arranca solo y proyecta la escena correcta tras un corte de luz, sin red
disponible.
→ [[Despliegue-Raspberry]] · [[Presupuesto-de-Rendimiento]]

Perdió la malla (se adelantó al Hito 1) y las máscaras (pasaron a post-v1: el derrame de luz ayuda a
delimitar mientras se calibra).

## Después de v1
**Máscaras poligonales** (acabado final, quitar el halo) · **proyectar la interfaz de edición sobre
el objeto real**, para alinear sin mirar la pantalla · **efectos de tipo textura/imagen**, que hoy
quedan fuera a propósito: el catálogo es GLSL ([[ADR-015-Superficie-por-Cara-y-Malla]]) ·
agrupar superficies por objeto · cámara CSI / NoIR · edge blending multi-proyector · timeline y
sincronía de audio · compensación de color por superficie · control externo OSC/MIDI/DMX · subir
shaders desde la web (requiere auth, ver [[Seguridad-y-Red]]) · backend de red por D-Bus con
checkpoints ([[Modulo-Red]]).

Relacionado: [[Vision-Producto]] · [[Casos-de-Uso]] · [[Eco-Map]]
