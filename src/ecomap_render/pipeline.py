"""Pipeline de dibujo.

Dos pasos, como dice Warping-y-Homografia:

1. El efecto se dibuja en un FBO, en UV 0..1, sin saber nada del warp.
2. Cada superficie dibuja ese FBO sobre su malla deformada.

Hoy hay **un solo FBO compartido** y un solo efecto activo para todas las
superficies. Con las capas del Hito 2 pasa a ser un FBO por capa, dimensionado
al bounding box de su superficie para no pagar 1080p en una superficie chica.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import moderngl

from ecomap_render import shaders
from ecomap_render.context import is_gles
from ecomap_render.effects import EffectLibrary
from ecomap_render.surface import SurfaceMesh

log = logging.getLogger(__name__)


class ShaderError(RuntimeError):
    pass


class Pipeline:
    def __init__(self, ctx: moderngl.Context, size: tuple[int, int], effects_dir: Path) -> None:
        self.ctx = ctx
        self.size = size
        gles = is_gles(ctx)
        self.header = shaders.header(gles)

        try:
            warp_vertex, warp_fragment = shaders.warp_sources(gles)
            self.warp_program = ctx.program(
                vertex_shader=warp_vertex, fragment_shader=warp_fragment
            )
        except Exception as exc:  # moderngl.Error y derivados
            raise ShaderError(str(exc)) from exc

        # FBO respaldado por textura, no por renderbuffer: el paso de warp tiene
        # que **muestrear** este color, y un renderbuffer no se puede samplear.
        self._color = ctx.texture(size, components=3)
        self._color.filter = (moderngl.LINEAR, moderngl.LINEAR)
        # Sin repeat: si un punto de la malla se va de rango, se estira el borde
        # en vez de repetir el efecto en mosaico.
        self._color.repeat_x = False
        self._color.repeat_y = False
        self.fbo = ctx.framebuffer(color_attachments=[self._color])

        self.library = EffectLibrary(ctx, effects_dir, self.header)
        self.library.reload()
        self.surfaces: list[SurfaceMesh] = []
        self.effect_id: str | None = None
        self.params: dict[str, Any] = {}

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

    def set_effect(self, effect_id: str, params: dict[str, Any] | None = None) -> str | None:
        """Cambia el efecto activo. Devuelve el mensaje de error si no se pudo."""
        compilado = self.library.get(effect_id)
        if compilado is None:
            motivo = self.library.errors.get(effect_id, "no esta en el catalogo")
            log.warning("efecto %s: %s", effect_id, motivo)
            return motivo
        self.effect_id = effect_id
        self.params = params or {}
        log.info("efecto activo: %s", effect_id)
        return None

    # --- dibujo ---

    def render(self, target: moderngl.Framebuffer, *, time: float, blackout: bool) -> None:
        if blackout:
            target.use()
            self.ctx.clear(0.0, 0.0, 0.0)
            return

        dibujo = self._render_effect(time)

        target.use()
        self.ctx.clear(0.0, 0.0, 0.0)
        if not dibujo:
            return
        if not self.surfaces:
            # Sin superficies calibradas se muestra el efecto a pantalla
            # completa: es lo que permite apuntar el proyector antes de tener
            # nada configurado.
            self._draw_effect(time)
            return

        self._color.use(location=0)
        miembro = self.warp_program.get("u_texture", None)
        if miembro is not None:
            miembro.value = 0  # type: ignore[union-attr]
        for superficie in self.surfaces:
            opacidad = self.warp_program.get("u_opacity", None)
            if opacidad is not None:
                opacidad.value = superficie.opacity  # type: ignore[union-attr]
            superficie.render()

    def _render_effect(self, time: float) -> bool:
        self.fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0)
        return self._draw_effect(time)

    def _draw_effect(self, time: float) -> bool:
        if self.effect_id is None:
            return False
        compilado = self.library.get(self.effect_id)
        if compilado is None:
            return False
        compilado.set_common(
            u_time=time,
            u_resolution=(float(self.size[0]), float(self.size[1])),
        )
        compilado.apply_params(self.params)
        compilado.render()
        return True

    def release(self) -> None:
        self.clear_surfaces()
        self.library.release()
        self.fbo.release()
        self._color.release()
        self.warp_program.release()
