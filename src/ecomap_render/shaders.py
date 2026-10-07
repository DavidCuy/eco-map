"""Shaders propios del render.

Los **efectos** ya no viven aca: son archivos del volumen de efectos y se arman
en `ecomap_core.effects` (US-10). Lo que queda es el paso de warp, que es parte
del motor y no del catalogo, y la eleccion del header de version.

El header se elige en runtime: la Pi da OpenGL ES 3.x y el escritorio OpenGL
3.3. Es la unica diferencia entre ambos, el cuerpo de los shaders es el mismo.
"""

from __future__ import annotations

_HEADER_ES = "#version 300 es\nprecision mediump float;\n"
_HEADER_CORE = "#version 330 core\n"


def header(is_gles: bool) -> str:
    return _HEADER_ES if is_gles else _HEADER_CORE


# --- warp: dibuja el FBO del efecto sobre la malla de una superficie ---

_WARP_VERTEX = """
in vec2 in_position;
in vec3 in_uvq;
out vec3 v_uvq;
void main() {
    v_uvq = in_uvq;
    gl_Position = vec4(in_position, 0.0, 1.0);
}
"""

_WARP_FRAGMENT = """
in vec3 v_uvq;
out vec4 f_color;

uniform sampler2D u_texture;
uniform float u_opacity;

void main() {
    // La division por w es lo que evita el quiebre diagonal al interpolar UV
    // sobre los dos triangulos de una celda deformada.
    vec2 uv = v_uvq.xy / v_uvq.z;
    vec4 src = texture(u_texture, uv);
    // Alfa premultiplicado: el color ya viene multiplicado por su alfa y por la
    // opacidad de la superficie, asi que los cuatro modos de blend se definen
    // con la misma convencion y no hay que cambiar de formula por modo.
    f_color = vec4(src.rgb * u_opacity, src.a * u_opacity);
}
"""


def warp_sources(is_gles: bool) -> tuple[str, str]:
    """Devuelve (vertex, fragment) del paso de warp."""
    cabecera = header(is_gles)
    return cabecera + _WARP_VERTEX, cabecera + _WARP_FRAGMENT
