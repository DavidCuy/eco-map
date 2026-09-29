---
tags: [adr, render]
estado: aceptada
fecha: 2026-09-26
---

# ADR-005 — Motor de render: ModernGL + GLSL sobre KMS/DRM

**Estado:** aceptada · **Fecha:** 2026-09-26

## Contexto
Hay que generar efectos a 1080p60 y deformarlos geométricamente, en una Raspberry Pi. La CPU no alcanza: cualquier efecto por píxel en numpy da 5 fps. Tiene que ir a la GPU (VideoCore VI / V3D, OpenGL ES 3.1).

## Decisión
**ModernGL** (bindings sobre OpenGL/GLES) con shaders **GLSL ES 3.0**. En la Pi, contexto **EGL** sobre **KMS/DRM** sin servidor X ni escritorio. En desarrollo de escritorio, `moderngl-window` con GLFW.

## Razones
- ModernGL es una API limpia sobre GL: FBOs, texturas, VAOs, uniforms — exactamente las primitivas que necesita el pipeline de [[Warping-y-Homografia]].
- Los efectos como shaders son **datos**: agregar uno no toca Python. Ver [[Modulo-Efectos]].
- Sin escritorio: se ahorra ~200 MB de RAM y el compositor deja de introducir latencia y tearing.
- La textura de cámara se sube directo a GPU y se consume como `sampler2D` sin copias extra.

## Alternativas
- **pygame (SDL2, software)** — simple, pero blitting por CPU; no da 1080p60.
- **pygame + OpenGL** — funciona pero SDL agrega una capa que no aporta; ModernGL es más directo.
- **OpenFrameworks / C++** — mejor rendimiento, peor velocidad de desarrollo y rompe la premisa de proyecto en Python.
- **GStreamer + `glshader`** — potente para video, incómodo para geometría interactiva.
- **MadMapper / servidor externo** — contradice [[Vision-Producto]].

## Riesgos
- El driver V3D soporta GLES 3.1, **no** OpenGL 4.x de escritorio: los shaders deben escribirse en GLSL ES y probarse en la Pi, no solo en el escritorio. Riesgo real de "funciona en mi máquina".
- Arrancar EGL/KMS sin X tiene detalles (permisos de `/dev/dri`, `vc4-kms-v3d` en `config.txt`). Ver [[Raspberry-Pi-Setup]].
- El acceso a GPU desde un contenedor exige montar `/dev/dri` y los grupos `video` y `render`. Ver [[ADR-009-Todo-en-Contenedores]].

## Consecuencias
- Un solo proceso dueño del contexto GL. Ver [[Modulo-Render]].
- Los efectos se validan compilando el shader al arrancar; si falla, fallback y aviso a la UI.

Relacionado: [[Presupuesto-de-Rendimiento]]
