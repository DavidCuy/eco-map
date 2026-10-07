---
tags: [moc, eco-map]
tipo: god-node
---

# Eco-Map — Nodo raíz

Videomapping de bajo costo: **1 proyector + 1 computadora chica + 1 cámara web USB**, configurado desde una **interfaz web** que corre en el mismo equipo. Plataforma de referencia: mini PC x86; Raspberry Pi soportada ([[ADR-013-Plataforma-Agnostica]]).

## Qué es

Sistema que proyecta efectos visuales deformados (warping) sobre una superficie física real. La superficie se define y calibra desde el navegador. Una cámara mira la proyección y **retroalimenta** el sistema: auto-calibración y efectos reactivos.

## Mapa

- Producto → [[Vision-Producto]] · [[Casos-de-Uso]] · [[Glosario]] · [[Roadmap]]
- Arquitectura → [[Arquitectura-General]] (diagramas) · [[Modelo-de-Datos]] · [[Contratos-API]]
- Módulos → [[Modulo-Web-API]] · [[Modulo-Calibracion]] · [[Modulo-Render]] · [[Modulo-Efectos]] · [[Modulo-Camara-Feedback]] · [[Modulo-Red]]
- Decisiones vigentes → [[ADR-001-FastAPI]] · [[ADR-002-HTMX-Alpine]] · [[ADR-003-uv]] · [[ADR-004-SQLite]] · [[ADR-005-Motor-Render-OpenGL]] · [[ADR-006-IPC-Web-Render]] · [[ADR-009-Todo-en-Contenedores]] · [[ADR-010-Camara-USB]] · [[ADR-011-Archivos-vs-DB]] · [[ADR-012-Podman-Desarrollo-Local]] · [[ADR-013-Plataforma-Agnostica]] · [[ADR-014-Podman-Rootful]]
- Decisiones reemplazadas → [[ADR-007-Docker]] → [[ADR-009-Todo-en-Contenedores]] · [[ADR-008-Camara-Picamera2]] → [[ADR-010-Camara-USB]]
- Hardware → [[Mini-PC-Setup]] · [[Raspberry-Pi-Setup]] · [[Proyector]] · [[Camara]]
- Operación → [[Docker-Local]] · [[Despliegue-Raspberry]] · [[Estructura-Repositorio]] · [[Seguridad-y-Red]]
- Referencias → [[Referencias-Externas]]

## Stack en una línea

Python 3.12 · FastAPI + HTMX/Alpine/Jinja2 · ModernGL (GLSL ES) · OpenCV + webcam USB · SQLite · uv · contenedores en todos los entornos (Podman rootless en desarrollo).

## Restricciones rectoras

1. Todo corre **en el equipo local**, sin nube, sin GPU discreta. Lo que no rinda a 30–60 fps en 1080p en una mini PC o una Pi 4/5 no entra en v1. Ver [[Presupuesto-de-Rendimiento]].
2. Todo se ejecuta en **contenedores**, también en producción. Ver [[ADR-009-Todo-en-Contenedores]]; con Podman rootful ([[ADR-012-Podman-Desarrollo-Local]], [[ADR-014-Podman-Rootful]]).
3. Todo se **desarrolla sin hardware adicional**: render headless + cámara simulada. Ver [[Modulo-Render]].
4. **Configuración voluminosa en archivos, metadatos en SQLite.** Ver [[ADR-011-Archivos-vs-DB]].
5. **Sin login en v1.** La red se configura desde la propia web. Ver [[Modulo-Red]] · [[Seguridad-y-Red]].
