---
tags: [arquitectura, render]
---

# Módulo Render

Proceso `ecomap-render`. Único dueño del contexto OpenGL y de la salida HDMI.

## Runtime

- **ModernGL** sobre **OpenGL ES 3.1** (Mesa V3D en Pi 4/5).
- Ventana/superficie: `moderngl-window` con backend GLFW en escritorio, o **contexto standalone EGL sobre KMS/DRM** en la Pi sin X (`ctx = moderngl.create_context(standalone=True, backend='egl')` + scanout DRM). Justificación y alternativas en [[ADR-005-Motor-Render-OpenGL]].
- Sin compositor, sin escritorio: la Pi arranca en consola y el render toma el display.

## Loop

```python
while running:
    bus.poll()                 # no bloqueante: ops del web (param, reload, blackout)
    t = time.perf_counter() - t0
    for layer in scene.layers:
        layer.effect.render(fbo=layer.fbo, time=t, params=layer.params, cam=cam_tex)
        surface.draw(layer.fbo, layer.blend)
    swap_buffers()
    telemetry.tick()           # fps, frame time, temp cada 1 s
```

## Estado en memoria

El render mantiene un `Scene` inmutable-por-frame. Las ops del bus se aplican **entre frames**, nunca a mitad de dibujo. Un `reload` completo re-lee la escena desde... el web, que se la manda serializada por el socket; el render **no abre SQLite**. Así hay una sola fuente de verdad de lectura y cero locks.

## Manejo de fallos

| Fallo | Respuesta |
|---|---|
| Shader no compila | log + fallback a shader `solid_black`, marca el efecto como `broken`, avisa a la UI |
| Frame time > 2× objetivo por 3 s | baja resolución de FBO un escalón y avisa |
| Socket caído (web reiniciado) | sigue proyectando con el último estado; reintenta accept |
| Sin cámara | los efectos que piden `u_cam` reciben textura negra |

## Modo desarrollo — requisito, no comodidad

**Todo el sistema debe ser desarrollable sin proyector, sin Pi y sin cámara** (RNF-5, CU-09). El render tiene tres modos de salida, seleccionados por configuración:

| Modo | Salida | Dónde |
|---|---|---|
| `kms` | EGL + KMS/DRM → HDMI | Pi en producción |
| `window` | ventana GLFW | escritorio Linux con GPU |
| `headless` | FBO + servidor MJPEG en `:8001` | contenedor de desarrollo, CI |

En `headless` con `LIBGL_ALWAYS_SOFTWARE=1` (llvmpipe) el pipeline completo funciona por CPU: efectos, warp, máscaras y composición. La UI muestra ese MJPEG como preview, así que calibrar, crear escenas y escribir shaders se hace entero desde el navegador en la laptop. La cámara se reemplaza por `FakeSource`: un mp4 o patrones sintéticos. Ver [[Docker-Local]] y [[ADR-010-Camara-USB]].

Lo que **no** se valida así: rendimiento real (llvmpipe no dice nada del V3D), diferencias de GLSL ES en el driver de la Pi, y el lazo óptico proyector→cámara. Esos tres se prueban en hardware al cerrar cada hito. Ver [[Presupuesto-de-Rendimiento]].

El modo `headless` es además lo que permite tests de render en CI: renderizar un frame y compararlo con una imagen de referencia con tolerancia.

Relacionado: [[Modulo-Efectos]] · [[Warping-y-Homografia]] · [[ADR-006-IPC-Web-Render]]
