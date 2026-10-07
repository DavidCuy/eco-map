---
tags: [arquitectura, efectos]
---

# Módulo Efectos

Un efecto **es un directorio**, no una clase de Python. Agregar un efecto = copiar una carpeta y recargar el catálogo.

```
/effects/                    <- volumen Docker ecomap-effects
  plasma/
    effect.json      # manifiesto: identidad y parámetros
    frag.glsl        # fragment shader
    vert.glsl        # opcional (default: quad full-screen)
    preview.jpg      # miniatura para el catálogo
```

## Dónde vive

**Volumen propio `ecomap-effects`, separado del volumen de la DB.** Ver [[Docker-Local]] y [[ADR-011-Archivos-vs-DB]].

- Montado **`:ro` en el render**: un efecto no puede corromper el catálogo.
- Montado **lectura/escritura en el web**, que lo escanea y sincroniza al catálogo en SQLite.
- Es portable: un paquete de efectos se copia entre instalaciones sin arrastrar la configuración de superficies y escenas.
- Los assets pesados (videos, imágenes) **no** van aquí: van al volumen `ecomap-media`, y el manifiesto los referencia por ruta relativa.
- En desarrollo se monta como bind mount de `./effects`: se edita un `.glsl` con el editor local y se recarga sin reconstruir la imagen.

En la DB solo queda el espejo del manifiesto (`effect.id`, nombre, versión, `available`). Si el archivo desaparece, la fila queda con `available = 0` y las capas que lo usaban no se rompen.

## El contrato del shader

`frag.glsl` **no es un fragment shader completo**: aporta una función

```glsl
vec3 effect(vec2 uv) { ... }
```

y el loader la envuelve con el header de versión, los uniforms comunes y los
parámetros del manifiesto, declarados con prefijo `p_`. Así un efecto no tiene que
acordarse de declarar nada ni de qué versión de GLSL corre debajo — que cambia
entre la Pi (ES 3.0), la mini PC (3.3 core) y el modo headless.

El armado vive en `ecomap_core.effects`, que es puro: parsea, valida y arma texto,
sin tocar OpenGL. Por eso lo usan los dos procesos — el web para listar y validar,
el render para compilar.

Reglas que hacen fallar la carga, a propósito y temprano:

- El `id` del manifiesto tiene que coincidir con el nombre del directorio; si no,
  elegir un efecto por id dejaría de ser determinista.
- El `.glsl` tiene que definir `vec3 effect(`.
- Un efecto roto **no impide cargar los demás**: se reporta y se sigue.

## Manifiesto

```json
{
  "id": "plasma",
  "name": "Plasma",
  "version": "1.0.0",
  "tags": ["abstracto", "loop"],
  "needs_camera": false,
  "cost": "low",
  "params": [
    {"key":"speed","label":"Velocidad","type":"float","min":0.0,"max":3.0,"default":1.0},
    {"key":"scale","label":"Escala","type":"float","min":1.0,"max":20.0,"default":6.0},
    {"key":"color_a","label":"Color A","type":"color","default":"#00ffc8"},
    {"key":"mirror","label":"Espejo","type":"bool","default":false}
  ]
}
```

El manifiesto **genera la UI sola**: FastAPI lo valida con Pydantic y Jinja2 pinta el control por `type` (`float`→range, `color`→color picker, `bool`→switch, `enum`→select). Un efecto nuevo aparece en la web sin tocar frontend.

## Uniforms siempre disponibles

| Uniform | Tipo | Significado |
|---|---|---|
| `u_time` | float | segundos desde el arranque de la escena |
| `u_resolution` | vec2 | tamaño del FBO |
| `u_beat` | float | 0..1, fase rítmica (por ahora BPM manual) |
| `u_cam` | sampler2D | último frame de cámara (si `needs_camera`) |
| `u_motion` | float | 0..1, cantidad de movimiento detectado. Ver [[Modulo-Camara-Feedback]] |
| `u_motion_pos` | vec2 | centroide del movimiento, normalizado |

## Catálogo v1 propuesto

| Efecto | Costo | Notas |
|---|---|---|
| `solid` | nulo | color plano; sirve para alinear y para máscaras |
| `grid_test` | nulo | ajedrez + esquinas numeradas; **obligatorio** para calibrar |
| `plasma` | bajo | ruido sinusoidal clásico |
| `noise_flow` | medio | simplex + domain warping |
| `waves` | bajo | ondas concéntricas, reactivas a `u_motion_pos` |
| `particles` | alto | transform feedback o compute; 30 fps objetivo |
| `video_loop` | medio | reproducir mp4 (decodificación HW, `v4l2m2m`) |
| `camera_echo` | medio | feedback de cámara con delay y desplazamiento — el efecto "eco" que da nombre al proyecto |

## Reglas para escribir shaders

- `precision mediump float;` por defecto en la Pi; `highp` solo si hace falta (cuesta).
- Nada de `for` con cota dinámica ni `pow` en bucle: el V3D lo sufre.
- Cada efecto debe verse decente con todos los parámetros en default.
- Normalizar por `u_resolution`, nunca asumir 1920×1080.

Relacionado: [[Presupuesto-de-Rendimiento]] · [[Modulo-Render]] · [[Modelo-de-Datos]]
