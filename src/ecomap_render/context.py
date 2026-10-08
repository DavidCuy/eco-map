"""Creacion del contexto GL y presentacion del frame.

Tres modos (Modulo-Render):

- `kms`      -> Raspberry Pi sin escritorio: SDL2 con backend KMSDRM y salida HDMI.
- `window`   -> escritorio con GPU: ventana GLFW, util para depurar a ojo.
- `headless` -> contenedor de desarrollo y CI: FBO fuera de pantalla que se
                publica como MJPEG. Es lo que permite trabajar sin hardware.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

import moderngl

from ecomap_core.settings import Settings

log = logging.getLogger(__name__)


class Presenter(Protocol):
    ctx: moderngl.Context
    size: tuple[int, int]

    def begin_frame(self) -> moderngl.Framebuffer: ...

    def end_frame(self) -> None: ...

    def should_close(self) -> bool: ...

    def close(self) -> None: ...


def is_gles(ctx: moderngl.Context) -> bool:
    return "ES" in str(ctx.info.get("GL_VERSION", "")).upper()


class HeadlessPresenter:
    """Renderiza a un FBO. Quien quiera ver el resultado lo lee con `read()`."""

    def __init__(self, settings: Settings) -> None:
        kwargs: dict[str, object] = {"standalone": True}
        if settings.gl_backend:
            kwargs["backend"] = settings.gl_backend
        self.ctx = moderngl.create_context(**kwargs)  # type: ignore[arg-type]
        self.size = (settings.width, settings.height)
        self._fbo = self.ctx.simple_framebuffer(self.size, components=3)
        log.info(
            "render: contexto headless (%s, %s)",
            self.ctx.info.get("GL_RENDERER", "?"),
            self.ctx.info.get("GL_VERSION", "?"),
        )

    def begin_frame(self) -> moderngl.Framebuffer:
        self._fbo.use()
        return self._fbo

    def end_frame(self) -> None:
        self.ctx.finish()

    def read(self) -> bytes:
        """Pixeles RGB del ultimo frame. Costoso: llamarlo solo para el preview."""
        return self._fbo.read(components=3)

    def should_close(self) -> bool:
        return False

    def close(self) -> None:
        self._fbo.release()
        self.ctx.release()


class WindowPresenter:
    """Ventana GLFW: escritorio con GPU, o proyector en un host con escritorio.

    Requiere el paquete `glfw`, que moderngl-window no instala solo (extra
    `window` del proyecto). En pantalla completa es la alternativa a `kms`
    cuando el host no puede ceder el DRM master, por ejemplo Windows.
    """

    def __init__(self, settings: Settings) -> None:
        import moderngl_window

        window_cls = moderngl_window.get_local_window_cls("glfw")
        self._window = window_cls(
            title="Eco-Map",
            size=(settings.width, settings.height),
            gl_version=(3, 3),
            vsync=True,
            resizable=False,
            fullscreen=settings.window_fullscreen,
            # El puntero del mouse sobre la proyeccion se ve, y no se va solo.
            cursor=not settings.window_fullscreen,
        )
        if settings.window_fullscreen and settings.window_monitor:
            self._move_to_monitor(settings.window_monitor)
        moderngl_window.activate_context(self._window)
        self.ctx = self._window.ctx
        # El framebuffer, no la ventana: con escalado de pantalla (Windows,
        # HiDPI) no miden lo mismo, y lo que se dibuja es el framebuffer. Todo
        # lo de aguas abajo usa este `size`, asi que la resolucion real que da
        # el monitor en pantalla completa manda sobre width/height pedidos.
        self.size = self._window.buffer_size
        log.info(
            "render: contexto window %dx%d%s (%s, %s)",
            self.size[0],
            self.size[1],
            " pantalla completa" if settings.window_fullscreen else "",
            self.ctx.info.get("GL_RENDERER", "?"),
            self.ctx.info.get("GL_VERSION", "?"),
        )

    def _move_to_monitor(self, index: int) -> None:
        """Pasa la ventana al monitor `index` a la resolucion nativa de ese monitor.

        moderngl-window solo sabe de pantalla completa en el primario, asi que
        hay que hablarle a GLFW directo. Si la version de moderngl-window cambia
        el nombre del handle, se avisa y se sigue en el primario: perder el
        monitor elegido no justifica no proyectar.
        """
        import glfw

        try:
            monitors = glfw.get_monitors()
            if index >= len(monitors):
                log.warning(
                    "render: ECOMAP_WINDOW_MONITOR=%d pero hay %d monitores; se usa el primario",
                    index,
                    len(monitors),
                )
                return
            monitor = monitors[index]
            mode = glfw.get_video_mode(monitor)
            glfw.set_window_monitor(
                self._window._window,
                monitor,
                0,
                0,
                mode.size.width,
                mode.size.height,
                mode.refresh_rate,
            )
            self._window._width, self._window._height = mode.size.width, mode.size.height
            self._window._buffer_width, self._window._buffer_height = glfw.get_framebuffer_size(
                self._window._window
            )
        except (AttributeError, TypeError) as exc:
            log.warning("render: no se pudo mover al monitor %d (%s)", index, exc)

    def begin_frame(self) -> moderngl.Framebuffer:
        self._window.use()
        return self._window.fbo

    def end_frame(self) -> None:
        self._window.swap_buffers()

    def should_close(self) -> bool:
        return bool(self._window.is_closing)

    def close(self) -> None:
        self._window.destroy()


class KmsPresenter:
    """Salida directa a HDMI en la Pi, sin servidor X ni compositor.

    SDL2 con el driver KMSDRM crea la superficie y moderngl se engancha al
    contexto ya activo. Requiere `vc4-kms-v3d` en config.txt y que el usuario
    pertenezca a los grupos video y render.
    """

    def __init__(self, settings: Settings) -> None:
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        import pygame

        pygame.display.init()
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES
        )
        pygame.display.set_mode(
            (settings.width, settings.height),
            pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN,
        )
        self._pygame = pygame
        self.ctx = moderngl.create_context()
        self.size = (settings.width, settings.height)
        log.info(
            "render: contexto kms (%s, %s)",
            self.ctx.info.get("GL_RENDERER", "?"),
            self.ctx.info.get("GL_VERSION", "?"),
        )

    def begin_frame(self) -> moderngl.Framebuffer:
        self.ctx.screen.use()
        return self.ctx.screen

    def end_frame(self) -> None:
        self._pygame.display.flip()

    def should_close(self) -> bool:
        return False

    def close(self) -> None:
        self._pygame.display.quit()


def create_presenter(settings: Settings) -> Presenter:
    if settings.render_mode == "window":
        return WindowPresenter(settings)
    if settings.render_mode == "kms":
        return KmsPresenter(settings)
    return HeadlessPresenter(settings)
