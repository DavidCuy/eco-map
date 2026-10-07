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
    """Ventana GLFW en un escritorio con GPU."""

    def __init__(self, settings: Settings) -> None:
        import moderngl_window

        window_cls = moderngl_window.get_local_window_cls("glfw")
        self._window = window_cls(
            title="Eco-Map",
            size=(settings.width, settings.height),
            gl_version=(3, 3),
            vsync=True,
            resizable=False,
        )
        moderngl_window.activate_context(self._window)
        self.ctx = self._window.ctx
        self.size = self._window.size

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
