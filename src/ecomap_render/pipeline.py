"""Pipeline de dibujo.

Dos pasos por capa, como dice Warping-y-Homografia:

1. El efecto de la capa se dibuja en **su** FBO, en UV 0..1, sin saber nada del
   warp.
2. Ese FBO se dibuja sobre la malla de la superficie de la capa, con su modo de
   blend.

El FBO de cada capa se dimensiona al **bounding box de su superficie**, no a la
resolucion de salida: una cara chica no paga 1080p. Es la deuda que el Hito 1
dejo anotada y que US-13 paga.

Sin capas se dibuja el efecto de fallback a pantalla completa, que es lo que
sirve para apuntar el proyector antes de configurar nada.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import moderngl

from ecomap_render import shaders
from ecomap_render.context import is_gles
from ecomap_render.effects import EffectLibrary
from ecomap_render.media import MediaLibrary
from ecomap_render.surface import SurfaceMesh

log = logging.getLogger(__name__)

# Los FBO se redondean a multiplo de 8 y se acotan: una superficie diminuta no
# necesita un FBO de 32 px, y una que se sale de pantalla no debe pedir mas que
# la salida.
FBO_MIN = 64
FBO_ALIGN = 8


class ShaderError(RuntimeError):
    pass


def fbo_size(points: list[tuple[float, float]], output: tuple[int, int]) -> tuple[int, int]:
    """Tamano del FBO de una capa, a partir del bounding box de su superficie."""
    xs = [p[0] for p in points] or [0.0, 1.0]
    ys = [p[1] for p in points] or [0.0, 1.0]
    ancho = (max(xs) - min(xs)) * output[0]
    alto = (max(ys) - min(ys)) * output[1]
    return (
        _ajustar(ancho, output[0]),
        _ajustar(alto, output[1]),
    )


def _ajustar(valor: float, tope: int) -> int:
    entero = int(valor)
    alineado = ((entero + FBO_ALIGN - 1) // FBO_ALIGN) * FBO_ALIGN
    return max(FBO_MIN, min(alineado, tope))


class Layer:
    """Una capa lista para dibujar: su FBO, su malla y su blend."""

    def __init__(
        self,
        ctx: moderngl.Context,
        warp_program: moderngl.Program,
        datos: dict[str, Any],
        output: tuple[int, int],
    ) -> None:
        self.ctx = ctx
        self.id = datos.get("id")
        self.effect_id = str(datos.get("effect", ""))
        self.params = dict(datos.get("params") or {})
        self.blend = str(datos.get("blend", "normal"))
        self.mesh = SurfaceMesh(ctx, warp_program, datos["surface"])

        self.size = fbo_size([(float(x), float(y)) for x, y in datos["surface"]["points"]], output)
        self.texture = ctx.texture(self.size, components=4)
        self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.texture.repeat_x = False
        self.texture.repeat_y = False
        self.fbo = ctx.framebuffer(color_attachments=[self.texture])

        # Realimentacion: una capa que la pide lee su propio frame anterior en
        # `u_prev`. Cuesta una textura y un FBO extra, por eso es opcional.
        self.needs_feedback = bool(datos.get("needs_feedback"))
        self.prev_texture = None
        self.prev_fbo = None
        if self.needs_feedback:
            self.prev_texture = ctx.texture(self.size, components=4)
            self.prev_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.prev_texture.repeat_x = False
            self.prev_texture.repeat_y = False
            self.prev_fbo = ctx.framebuffer(color_attachments=[self.prev_texture])

    def swap_feedback(self) -> None:
        """Intercambia los dos buffers: lo recien dibujado pasa a ser `u_prev`.

        Es ping-pong clasico: dibujar y leer la misma textura en el mismo pase
        es comportamiento indefinido.
        """
        if not self.needs_feedback:
            return
        self.texture, self.prev_texture = self.prev_texture, self.texture
        self.fbo, self.prev_fbo = self.prev_fbo, self.fbo

    def release(self) -> None:
        self.mesh.release()
        self.fbo.release()
        self.texture.release()
        if self.prev_fbo is not None:
            self.prev_fbo.release()
        if self.prev_texture is not None:
            self.prev_texture.release()


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

        # FBO del fallback, a resolucion de salida.
        self._fallback_tex = ctx.texture(size, components=4)
        self._fallback_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._fallback_fbo = ctx.framebuffer(color_attachments=[self._fallback_tex])

        # Quad a pantalla completa para dibujar una textura tal cual: lo usa
        # la calibracion para proyectar sus patrones sin pasar por una
        # superficie.
        self.vao_full = self._quad_completo()

        self.library = EffectLibrary(ctx, effects_dir, self.header)
        self.media = MediaLibrary(ctx)
        self.library.reload()
        self.media.sync(self.library.efectos())
        # Textura negra de 1x1 para los efectos que piden camara cuando no hay:
        # sin esto el sampler queda sin enlazar y el resultado es indefinido.
        self._sin_camara = ctx.texture((1, 1), components=3, data=bytes(3))
        self._cam_texture = None
        self._cam_seq = -1
        self.motion = 0.0
        self.motion_pos = (0.5, 0.5)

        self.layers: list[Layer] = []
        self.scene_id: int | None = None
        self.fallback_effect: str | None = None
        self.fallback_params: dict[str, Any] = {}

    def reload_library(self) -> None:
        """Recarga el catalogo y vuelve a cargar los archivos de los efectos.

        Las dos cosas juntas y no por separado: un efecto subido desde la web
        aparece con su manifiesto y su archivo al mismo tiempo, y olvidarse
        del segundo lo deja compilando pero proyectando negro.
        """
        self.library.reload()
        self.media.sync(self.library.efectos())

    # --- escena ---

    def set_scene(self, scene: dict[str, Any]) -> None:
        """Reconstruye capas y geometria. Se llama al cambiar la escena o la
        calibracion, nunca por frame."""
        self.clear_layers()
        self.scene_id = scene.get("scene_id")
        self.fallback_effect = scene.get("fallback_effect")
        self.fallback_params = dict(scene.get("fallback_params") or {})

        for datos in scene.get("layers") or []:
            try:
                self.layers.append(Layer(self.ctx, self.warp_program, datos, self.size))
            except Exception:  # noqa: BLE001 - una capa mal formada no tumba el resto
                log.exception("capa %s: no se pudo construir", datos.get("id"))
        log.info(
            "escena %s: %d capas (%s)",
            self.scene_id,
            len(self.layers),
            ", ".join(f"{c.effect_id}@{c.size[0]}x{c.size[1]}" for c in self.layers) or "ninguna",
        )

    def _quad_completo(self):
        """VAO de dos triangulos que cubren la pantalla, con UV directo."""
        import numpy as np

        # posicion (clip space) + uvq con q=1: sin perspectiva, es plano
        datos = np.array(
            [
                -1.0, -1.0, 0.0, 0.0, 1.0,
                 1.0, -1.0, 1.0, 0.0, 1.0,
                 1.0,  1.0, 1.0, 1.0, 1.0,
                -1.0, -1.0, 0.0, 0.0, 1.0,
                 1.0,  1.0, 1.0, 1.0, 1.0,
                -1.0,  1.0, 0.0, 1.0, 1.0,
            ],
            dtype="f4",
        )
        self._vbo_full = self.ctx.buffer(datos.tobytes())
        return self.ctx.vertex_array(
            self.warp_program, [(self._vbo_full, "2f 3f", "in_position", "in_uvq")]
        )

    def clear_layers(self) -> None:
        for capa in self.layers:
            capa.release()
        self.layers.clear()

    def set_fallback_effect(
        self, effect_id: str, params: dict[str, Any] | None = None
    ) -> str | None:
        """Efecto a pantalla completa para cuando no hay capas. Devuelve el
        motivo si no se pudo."""
        if self.library.get(effect_id) is None:
            motivo = self.library.errors.get(effect_id, "no esta en el catalogo")
            log.warning("efecto %s: %s", effect_id, motivo)
            return motivo
        self.fallback_effect = effect_id
        self.fallback_params = params or {}
        return None

    # --- camara ---

    def update_camera(self, frame, seq: int) -> None:
        """Sube el ultimo frame de camara a GPU.

        Solo cuando hay uno nuevo: el hilo de vision va a 15 fps y el render a
        60, asi que tres de cada cuatro frames reusan la textura.
        """
        if frame is None or seq == self._cam_seq:
            return
        alto, ancho = frame.shape[:2]
        if self._cam_texture is None or self._cam_texture.size != (ancho, alto):
            if self._cam_texture is not None:
                self._cam_texture.release()
            self._cam_texture = self.ctx.texture((ancho, alto), components=3)
            self._cam_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        if frame.ndim == 2:
            import numpy as np

            # Una fuente de un solo canal no deberia tumbar la proyeccion: se
            # replica a tres y sigue.
            frame = np.repeat(frame[:, :, None], 3, axis=2)
        # OpenCV entrega BGR y con el origen arriba; GL espera RGB desde abajo.
        self._cam_texture.write(frame[::-1, :, ::-1].tobytes())
        self._cam_seq = seq

    def _bind_camera(self) -> None:
        textura = self._cam_texture or self._sin_camara
        textura.use(location=1)

    # --- dibujo ---

    def render(self, target: moderngl.Framebuffer, *, time: float, blackout: bool) -> None:
        if blackout:
            target.use()
            self.ctx.clear(0.0, 0.0, 0.0)
            return

        # Los videos avanzan una vez por frame, no una vez por capa: dos capas
        # del mismo efecto comparten la textura y adelantarla dos veces lo
        # haria ir al doble de velocidad.
        self.media.tick()

        if not self.layers:
            self._render_fallback(target, time)
            return

        for capa in self.layers:
            self._render_effect(
                capa.fbo, capa.size, capa.effect_id, capa.params, time, capa
            )

        target.use()
        self.ctx.clear(0.0, 0.0, 0.0)
        self.ctx.enable(moderngl.BLEND)
        for capa in self.layers:
            self._aplicar_blend(capa.blend)
            capa.texture.use(location=0)
            self._set(self.warp_program, "u_texture", 0)
            self._set(self.warp_program, "u_opacity", capa.mesh.opacity)
            capa.mesh.render()
        self.ctx.disable(moderngl.BLEND)

        for capa in self.layers:
            capa.swap_feedback()

    def _render_fallback(self, target: moderngl.Framebuffer, time: float) -> None:
        target.use()
        self.ctx.clear(0.0, 0.0, 0.0)
        if self.fallback_effect:
            self._render_effect(target, self.size, self.fallback_effect, self.fallback_params, time)

    def _render_effect(
        self,
        fbo: moderngl.Framebuffer,
        size: tuple[int, int],
        effect_id: str,
        params: dict[str, Any],
        time: float,
        capa: Layer | None = None,
    ) -> None:
        compilado = self.library.get(effect_id)
        if compilado is None:
            return
        fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)

        self._bind_camera()
        if capa is not None and capa.prev_texture is not None:
            capa.prev_texture.use(location=2)
        else:
            self._sin_camara.use(location=2)
        # Imagen, gif o video del efecto. Si no tiene, queda una textura negra
        # de 1x1: un sampler sin enlazar da resultado indefinido.
        self.media.bind(effect_id, 3)

        compilado.set_common(
            u_time=time,
            u_resolution=(float(size[0]), float(size[1])),
            u_cam=1,
            u_prev=2,
            u_media=3,
            u_motion=self.motion,
            u_motion_pos=self.motion_pos,
        )
        compilado.apply_params(params)
        compilado.render()

    def _aplicar_blend(self, modo: str) -> None:
        """Alfa premultiplicado: el shader de warp ya multiplica el color por la
        opacidad, asi que los cuatro modos quedan consistentes entre si."""
        if modo == "add":
            self.ctx.blend_func = (moderngl.ONE, moderngl.ONE)
        elif modo == "multiply":
            self.ctx.blend_func = (moderngl.DST_COLOR, moderngl.ZERO)
        elif modo == "screen":
            self.ctx.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_COLOR)
        else:  # normal
            self.ctx.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)

    @staticmethod
    def _set(program: moderngl.Program, name: str, value: object) -> None:
        member = program.get(name, None)
        if member is not None:
            member.value = value  # type: ignore[union-attr]

    def release(self) -> None:
        self.clear_layers()
        self.vao_full.release()
        self._vbo_full.release()
        self.library.release()
        self.media.release()
        self._fallback_fbo.release()
        self._fallback_tex.release()
        self._sin_camara.release()
        if self._cam_texture is not None:
            self._cam_texture.release()
        self.warp_program.release()
