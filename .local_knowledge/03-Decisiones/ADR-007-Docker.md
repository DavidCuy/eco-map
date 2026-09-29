---
tags: [adr, devops]
estado: reemplazada
fecha: 2026-09-26
---

# ADR-007 — Docker para desarrollo local; en la Pi, systemd

**Estado:** REEMPLAZADA · **Fecha:** 2026-09-26

> [!warning] Reemplazada por [[ADR-009-Todo-en-Contenedores]] el 2026-09-26.
> Se conserva por el análisis de alternativas; no refleja la decisión vigente.

## Contexto
Se pidió Dockerfile y docker-compose para probar en local. En producción el software corre en una Raspberry Pi accediendo a GPU (`/dev/dri`), cámara (`/dev/video*`, libcamera) y salida HDMI directa.

## Decisión
- **Docker es el entorno de desarrollo y prueba local**, con el render en **modo mock/headless** (renderiza a FBO y expone preview MJPEG, sin salida HDMI). Ver [[Docker-Local]].
- **En la Pi el despliegue por defecto es nativo con systemd** (dos units: `ecomap-web`, `ecomap-render`). Ver [[Despliegue-Raspberry]].
- Se mantiene una variante de compose con `devices: [/dev/dri]` + `privileged` para quien quiera correr contenedores en la Pi, documentada como camino avanzado.

## Razones
- Contenerizar acceso a KMS/DRM y libcamera en la Pi funciona pero es frágil: permisos, versiones de Mesa que deben coincidir con el kernel del host, `libcamera` que espera archivos del sistema. No vale el costo en la v1.
- Docker sí resuelve el problema real: levantar la app en el escritorio (Windows/Mac/Linux) sin instalar OpenCV ni drivers.
- Imagen multi-stage con uv: `uv sync --frozen` en el stage builder, runtime con solo el venv. Base `python:3.12-slim-bookworm`, que existe para arm64 y amd64.

## Consecuencias
- Dos rutas de instalación documentadas. Riesgo de divergencia → mitigado porque ambas usan el mismo `pyproject.toml` y los mismos entry points.
- `data/` y `effects/` se montan como volúmenes: cambiar un shader no obliga a reconstruir la imagen.
- `opencv-python-headless` (no la variante con GUI): evita arrastrar GTK a la imagen.

Relacionado: [[ADR-003-uv]] · [[Docker-Local]]
