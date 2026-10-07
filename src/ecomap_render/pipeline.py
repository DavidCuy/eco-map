"""Pipeline de dibujo.

Dos pasos, como dice Warping-y-Homografia:

1. El efecto se dibuja en un FBO, en UV 0..1, sin saber nada del warp.
2. Cada superficie dibuja ese FBO sobre su malla deformada.

Hoy hay **un solo FBO compartido** por todas las superficies, porque todas
muestran el mismo efecto. Con las capas del Hito 2 pasa a ser un FBO por capa,
dimensionado al bounding box de su superficie para no pagar 1080p en una
superficie chica.
"""

from __future__ import annotations

import logging
from typing import Any

import moderngl

from ecomap_render import shaders
from ecomap_render.context import is_gles
from ecomap_render.surface import SurfaceMesh

log = logging.getLogger(__name__)


class ShaderError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, ctx: moderngl.Context, size: tuple[int, int]) -> None:
        self.ctx = ctx
        self.size = size
        gles = is_gles(ctx)

        try:
            vertex, fragment = shaders.sources(gles)
            self.program = ctx.program(vertex_shader=vertex, fragment_shader=fragment)
            warp_vertex, warp_fragment = shaders.warp_sources(gles)
            self.warp_program = ctx.program(
                vertex_shader=warp_vertex, fragment_shader=warp_fragment
            )
        except Exception as exc:  # moderngl.Error y derivados
            raise ShaderError(str(exc)) from exc

        # Sin atributos: el efecto se dibuja con un triangulo que sale de gl_VertexID.
        self.vao = ctx.vertex_array(self.program, [])
        # FBO respaldado por textura, no por renderbuffer: el paso de warp tiene
        # que **muestrear** este color, y un renderbuffer no se puede samplear.
        self._color = ctx.texture(size, components=3)
        self._color.filter = (moderngl.LINEAR, moderngl.LINEAR)
        # Sin repeat: si un punto de la malla se va de rango, se estira el borde
        # en vez de repetir el efecto en mosaico.
        self._color.repeat_x = False
        self._color.repeat_y = False
        self.fbo = ctx.framebuffer(color_attachments=[self._color])
        self.surfaces: list[SurfaceMesh] = []

    # --- escena ---

    def set_surfaces(self, surfaces: list[dict[str, Any]]) -> None:
        """Reconstruye la geometria. Se llama al cambiar la calibracion, nunca
        por frame: subir un VBO en cada frame tira el rendimiento."""
        self.clear_surfaces()
        for datos in surfaces:
            try:
                self.surfaces.append(SurfaceMesh(self.ctx, self.warp_program, datos))
            except Exception:  # noqa: BLE001 - una superficie mal formada no tumba el resto
                log.exception("superficie %s: no se pudo construir", datos.get("id"))
        log.info("escena: %d superficies", len(self.surfaces))

    def clear_surfaces(self) -> None:
        for superficie in self.surfaces:
            superficie.release()
        self.surfaces.clear()

    # --- dibujo ---

    def render(
        self,
        target: moderngl.Framebuffer,
        *,
        time: float,
        pattern: int,
        blackout: bool,
    ) -> None:
        if blackout:
            target.use()
            self.ctx.clear(0.0, 0.0, 0.0)
            return

        self._render_effect(time, pattern)

        target.use()
        self.ctx.clear(0.0, 0.0, 0.0)
        if not self.surfaces:
            # Sin superficies calibradas se muestra el efecto a pantalla
            # completa: es lo que permite apuntar el proyector antes de
            # tener nada configurado.
            self._blit_fullscreen(time, pattern)
            return

        self._color.use(location=0)
        self._set(self.warp_program, "u_texture", 0)
        for superficie in self.surfaces:
            self._set(self.warp_program, "u_opacity", superficie.opacity)
            superficie.render()

    def _render_effect(self, time: float, pattern: int) -> None:
        self.fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0)
        self._set(self.program, "u_time", time)
        self._set(self.program, "u_resolution", (float(self.size[0]), float(self.size[1])))
        self._set(self.program, "u_pattern", pattern)
        self.vao.render(moderngl.TRIANGLES, vertices=3)

    def _blit_fullscreen(self, time: float, pattern: int) -> None:
        self._set(self.program, "u_time", time)
        self._set(self.program, "u_resolution", (float(self.size[0]), float(self.size[1])))
        self._set(self.program, "u_pattern", pattern)
        self.vao.render(moderngl.TRIANGLES, vertices=3)

    @staticmethod
    def _set(program: moderngl.Program, name: str, value: object) -> None:
        member = program.get(name, None)
        if member is not None:
            member.value = value  # type: ignore[union-attr]

    def release(self) -> None:
        self.clear_surfaces()
        self.fbo.release()
        self._color.release()
        self.vao.release()
        self.warp_program.release()
        self.program.release()
