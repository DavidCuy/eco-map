"""Shaders del esqueleto.

Un unico programa con un `u_pattern` para lo que necesita el Hito 0: saludo,
grilla de calibracion, blanco y negro. Los efectos de verdad llegan con US-10 y
US-11, leidos del volumen de efectos.

El header de version se elige en runtime: la Pi da OpenGL ES 3.x y el escritorio
OpenGL 3.3. Es la unica diferencia entre ambos, el cuerpo del shader es el mismo.
"""

from __future__ import annotations

PATTERN_HELLO = 0
PATTERN_GRID = 1
PATTERN_WHITE = 2
PATTERN_BLACK = 3

PATTERN_BY_NAME = {
    "off": PATTERN_HELLO,
    "grid": PATTERN_GRID,
    "white": PATTERN_WHITE,
}

_HEADER_ES = "#version 300 es\nprecision mediump float;\n"
_HEADER_CORE = "#version 330 core\n"

_VERTEX = """
// Triangulo unico que cubre la pantalla: mas barato que dos triangulos de quad.
out vec2 v_uv;
void main() {
    vec2 pos = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = pos;
    gl_Position = vec4(pos * 2.0 - 1.0, 0.0, 1.0);
}
"""

_FRAGMENT = """
in vec2 v_uv;
out vec4 f_color;

uniform float u_time;
uniform vec2  u_resolution;
uniform int   u_pattern;

// Grilla de calibracion: ajedrez, marco y esquinas marcadas en distinto color
// para poder identificar cual es cual desde el otro lado de la sala.
vec3 grid(vec2 uv) {
    vec2 cell = floor(uv * 16.0);
    float checker = mod(cell.x + cell.y, 2.0);
    vec3 color = vec3(checker * 0.55 + 0.08);

    vec2 px = 1.0 / u_resolution;
    float border = 4.0;
    if (uv.x < px.x * border || uv.x > 1.0 - px.x * border ||
        uv.y < px.y * border || uv.y > 1.0 - px.y * border) {
        color = vec3(0.0, 0.95, 0.85);
    }

    // Marcas de esquina: TL roja, TR verde, BR azul, BL amarilla.
    float m = 0.06;
    if (uv.x < m && uv.y > 1.0 - m) color = vec3(1.0, 0.15, 0.15);
    if (uv.x > 1.0 - m && uv.y > 1.0 - m) color = vec3(0.15, 1.0, 0.15);
    if (uv.x > 1.0 - m && uv.y < m) color = vec3(0.25, 0.4, 1.0);
    if (uv.x < m && uv.y < m) color = vec3(1.0, 0.9, 0.1);
    return color;
}

// Saludo del esqueleto: degradado en movimiento, suficiente para ver que el
// loop corre y que el tiempo avanza.
vec3 hello(vec2 uv) {
    float wave = 0.5 + 0.5 * sin(u_time + uv.x * 3.0 + uv.y * 2.0);
    return mix(vec3(0.02, 0.05, 0.10), vec3(0.0, 0.75, 0.68), wave);
}

void main() {
    vec3 color;
    if (u_pattern == 1) {
        color = grid(v_uv);
    } else if (u_pattern == 2) {
        color = vec3(1.0);
    } else if (u_pattern == 3) {
        color = vec3(0.0);
    } else {
        color = hello(v_uv);
    }
    f_color = vec4(color, 1.0);
}
"""


def sources(is_gles: bool) -> tuple[str, str]:
    """Devuelve (vertex, fragment) con el header adecuado al contexto."""
    header = _HEADER_ES if is_gles else _HEADER_CORE
    return header + _VERTEX, header + _FRAGMENT
