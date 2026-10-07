---
tags: [roadmap, plan]
---

# Roadmap

Todos los hitos se desarrollan **sin hardware adicional**: contenedores en el escritorio, render headless con preview MJPEG y cámara simulada. El hardware se usa para validar, no para construir. Ver [[Docker-Local]] y [[ADR-009-Todo-en-Contenedores]].

## Hito 0 — Esqueleto (1 semana)
Repo con `pyproject.toml`/uv, Dockerfile multi-arch, los tres compose, migraciones y SQLite. Los cuatro volúmenes. FastAPI sirviendo el dashboard con Jinja2+HTMX+Pico. Render abriendo contexto GL y dibujando un triángulo. Bus UDS con `ping`/`pong`.
**Criterio:** `podman-compose -f compose.dev.yml up -d` levanta ambos y la UI muestra fps reales del render.
→ [[Estructura-Repositorio]] · [[ADR-003-uv]] · [[ADR-009-Todo-en-Contenedores]]

## Hito 1 — Un quad calibrable (1–2 semanas)
CRUD de superficies. Canvas con 4 handles. Efectos `grid_test` y `solid`. Warp por homografía. Persistencia en SQLite.
**Criterio:** ajustar las esquinas desde el celular y ver la grilla encajar en una caja real.
→ [[Modulo-Calibracion]] · [[Warping-y-Homografia]]

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
Malla N×M, máscaras, unit systemd, export/import de configuración, degradación automática por rendimiento, límites de log.
**Criterio:** la Pi arranca sola y proyecta la escena correcta tras un corte de luz, sin red disponible.
→ [[Despliegue-Raspberry]] · [[Presupuesto-de-Rendimiento]]

## Después de v1
Cámara CSI / NoIR · edge blending multi-proyector · timeline y sincronía de audio · efectos con video · compensación de color por superficie · control externo OSC/MIDI/DMX · subir shaders desde la web (requiere auth, ver [[Seguridad-y-Red]]) · backend de red por D-Bus con checkpoints ([[Modulo-Red]]).

Relacionado: [[Vision-Producto]] · [[Casos-de-Uso]] · [[Eco-Map]]
