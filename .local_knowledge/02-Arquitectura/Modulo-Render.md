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

## Latencia de un cambio

El render mide `apply_ms`: de operación recibida a frame presentado. Es el tramo que controla; el
resto de la latencia es navegador, HTTP y bus, y se mide del otro lado.

Medido en desarrollo: 4.74 ms. A 30 fps el período es 33 ms, así que ese número dice que la
operación se aplicó dentro del frame en curso y no esperó al siguiente.

## Capas y FBO

Desde US-13 el render dibuja **capas**, no superficies: cada capa es un efecto sobre una superficie,
con su blend. Dos pasos por capa:

1. El efecto se dibuja en **su** FBO, en UV 0..1, sin saber nada del warp.
2. Ese FBO se dibuja sobre la malla de la superficie, con el blend de la capa.

El FBO de cada capa se dimensiona al **bounding box de su superficie**, no a la resolución de
salida: una cara chica no paga 1080p. Medido en el stack de desarrollo, dos capas sobre caras de
medio ancho usan FBO de 240×224 y 240×208 en vez de 640×360 cada una.

Los blends usan **alfa premultiplicado**: el shader de warp ya multiplica el color por la opacidad,
así que los cuatro modos se definen con la misma convención en vez de una fórmula por modo.

La geometría de la superficie viaja **dentro** de cada capa. El render no tiene índice de
superficies ni le sirve tenerlo: con un solo mensaje puede redibujar todo.

Lo que no se dibuja no llega: el web filtra capas deshabilitadas, superficies deshabilitadas y
efectos no disponibles. El render recibe lo que se dibuja, no un estado sobre el que razonar.

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
