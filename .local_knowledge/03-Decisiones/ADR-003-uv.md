---
tags: [adr, tooling]
estado: aceptada
fecha: 2026-09-26
---

# ADR-003 — uv como gestor de paquetes

**Estado:** aceptada · **Fecha:** 2026-09-26

## Contexto
Dependencias pesadas (OpenCV, numpy, moderngl) que hay que instalar en dos arquitecturas: escritorio x86-64 de desarrollo y **arm64** en la Pi. Los builds en la Pi son lentos.

## Decisión
**uv** con `pyproject.toml` + `uv.lock` versionado. Extras por componente (`web`, `render`, `vision`, `pi`). Ver [[Estructura-Repositorio]].

## Razones
- Resolución e instalación mucho más rápidas que pip — se nota en la Pi y en cada build de Docker.
- `uv.lock` multiplataforma: el mismo lock resuelve para linux-x86_64 y linux-aarch64.
- `uv sync --frozen` en el Dockerfile = builds reproducibles.
- `uv run` evita activar venv a mano por SSH.

## Riesgo específico de la Pi

> [!note] Resuelto el 2026-09-26 al adoptar webcam USB ([[ADR-010-Camara-USB]]): `picamera2` salió del alcance de v1 y el entorno quedó idéntico en escritorio y Pi. El párrafo siguiente se conserva porque el riesgo vuelve si se agrega cámara CSI en v2.

**`picamera2` no se instala bien desde PyPI**: depende de `libcamera`, que viene como paquete del sistema (`python3-picamera2` vía apt). Solución de entonces: venv con `--system-site-packages` en la Pi y `picamera2` fuera del lock. Análisis en [[ADR-008-Camara-Picamera2]].

## Consecuencias
- `uv.lock` se commitea siempre.
- En CI y Docker: `uv sync --frozen --no-dev`.
- Nunca `pip install` directo dentro de la imagen ni en la Pi: rompe el lock.

Relacionado: [[ADR-009-Todo-en-Contenedores]] · [[Docker-Local]] · [[Despliegue-Raspberry]]
