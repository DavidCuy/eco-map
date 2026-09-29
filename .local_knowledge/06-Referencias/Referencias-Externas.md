---
tags: [referencias]
---

# Referencias externas

> Enlaces no verificados en esta sesión; confirmar versiones al implementar.

## Stack
- FastAPI — https://fastapi.tiangolo.com · [[ADR-001-FastAPI]]
- HTMX — https://htmx.org/docs · [[ADR-002-HTMX-Alpine]]
- Alpine.js — https://alpinejs.dev
- Pico.css — https://picocss.com
- uv — https://docs.astral.sh/uv · [[ADR-003-uv]]

## Render
- ModernGL — https://moderngl.readthedocs.io · [[ADR-005-Motor-Render-OpenGL]]
- moderngl-window — https://moderngl-window.readthedocs.io
- The Book of Shaders — https://thebookofshaders.com (GLSL desde cero)
- Shadertoy — https://shadertoy.com (fuente de efectos; portar a GLSL ES 3.0)
- Mesa V3D / driver Raspberry — https://docs.mesa3d.org

## Visión
- OpenCV `calib3d` / `findHomography` — https://docs.opencv.org
- `cv2.structured_light` (Gray code) — módulo contrib
- ArUco / ChArUco — https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html
- V4L2 y `v4l2-ctl` — controles de webcam USB · [[ADR-010-Camara-USB]]
- picamera2 manual, PDF — https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf (solo relevante si se suma cámara CSI en v2)
- NetworkManager D-Bus API — https://networkmanager.dev/docs/api/latest/ · [[Modulo-Red]]
- Mermaid — https://mermaid.js.org (diagramas de [[Arquitectura-General]])

## Dominio videomapping
- MadMapper / Resolume Arena — referencia de UX de calibración; mirar cómo resuelven handles, máscaras y warping de malla.
- HeavyM, Millumin — flujos de escenas y capas.
- "Projector-Camera Systems" (ProCams) — literatura académica de auto-calibración y compensación radiométrica. Términos de búsqueda: *structured light*, *radiometric compensation*, *projector-camera calibration*.

Relacionado: [[Eco-Map]]
