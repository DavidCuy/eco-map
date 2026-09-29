"""Pipeline de dibujo del esqueleto.

Un programa, un draw call. La estructura real (FBO por capa, warp por
superficie, mascaras) entra con US-09 y US-13; lo que importa aca es que el
loop, los uniforms y la deteccion de GLSL ES esten resueltos.
"""

from __future__ import annotations

import logging

import moderngl

from ecomap_render import shaders
from ecomap_render.context import is_gles

log = logging.getLogger(__name__)


class ShaderError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, ctx: moderngl.Context) -> None:
        self.ctx = ctx
        vertex, fragment = shaders.sources(is_gles(ctx))
        try:
            self.program = ctx.program(vertex_shader=vertex, fragment_shader=fragment)
        except Exception as exc:  # moderngl.Error y derivados
            raise ShaderError(str(exc)) from exc
        # Sin atributos: las posiciones salen de gl_VertexID.
        self.vao = ctx.vertex_array(self.program, [])

    def render(
        self,
        target: moderngl.Framebuffer,
        *,
        time: float,
        pattern: int,
        blackout: bool,
    ) -> None:
        target.use()
        if blackout:
            self.ctx.clear(0.0, 0.0, 0.0)
            return
        self._set("u_time", time)
        self._set("u_resolution", (float(target.width), float(target.height)))
        self._set("u_pattern", pattern)
        self.vao.render(moderngl.TRIANGLES, vertices=3)

    def _set(self, name: str, value: object) -> None:
        member = self.program.get(name, None)
        if member is not None:
            member.value = value  # type: ignore[union-attr]

    def release(self) -> None:
        self.vao.release()
        self.program.release()
