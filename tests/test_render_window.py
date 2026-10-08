"""Modo window: tamano del framebuffer y eleccion de monitor.

No se crea una ventana de verdad: en CI no hay GPU ni servidor grafico, y abrir
una pantalla completa en la maquina de alguien es inaceptable para un test. Lo
que se verifica es el contrato con moderngl-window, que es donde estuvo el bug:
tomar `window.size` (logico) en vez del framebuffer deja la geometria corrida en
cualquier pantalla con escalado. Medido en Windows al 125%: pedir 640x360 da una
ventana de 640x360 y un framebuffer de 800x450.
"""

from __future__ import annotations

import sys
import types

import pytest

from ecomap_core.settings import Settings
from ecomap_render.context import WindowPresenter


class _FakeWindow:
    """Lo minimo de la ventana de moderngl-window que usa WindowPresenter."""

    instancias: list[_FakeWindow] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._window = object()  # handle opaco de GLFW
        logico = kwargs["size"]
        # Escalado al 125%, como una pantalla de Windows por defecto.
        self._width, self._height = logico
        self._buffer_width = int(logico[0] * 1.25)
        self._buffer_height = int(logico[1] * 1.25)
        self.ctx = types.SimpleNamespace(info={"GL_RENDERER": "fake", "GL_VERSION": "3.3"})
        _FakeWindow.instancias.append(self)

    @property
    def size(self):
        return (self._width, self._height)

    @property
    def buffer_size(self):
        return (self._buffer_width, self._buffer_height)


@pytest.fixture
def mglw(monkeypatch):
    """Sustituye moderngl_window por un doble, sin tocar el import del modulo."""
    _FakeWindow.instancias = []
    fake = types.ModuleType("moderngl_window")
    fake.get_local_window_cls = lambda nombre: _FakeWindow
    fake.activate_context = lambda ventana: None
    monkeypatch.setitem(sys.modules, "moderngl_window", fake)
    return fake


def test_size_es_el_framebuffer_no_la_ventana(mglw):
    """El pipeline dibuja en el framebuffer: si `size` fuera el logico, el warp
    quedaria corrido un 25% en una pantalla escalada."""
    presenter = WindowPresenter(Settings(render_mode="window", width=640, height=360))

    assert presenter.size == (800, 450)
    assert presenter.size != _FakeWindow.instancias[0].size


def test_sin_fullscreen_se_ve_el_cursor(mglw):
    WindowPresenter(Settings(render_mode="window"))

    kwargs = _FakeWindow.instancias[0].kwargs
    assert kwargs["fullscreen"] is False
    assert kwargs["cursor"] is True


def test_fullscreen_oculta_el_cursor(mglw):
    """Sobre la proyeccion el puntero se ve y no desaparece solo."""
    WindowPresenter(Settings(render_mode="window", window_fullscreen=True))

    kwargs = _FakeWindow.instancias[0].kwargs
    assert kwargs["fullscreen"] is True
    assert kwargs["cursor"] is False


def test_monitor_primario_no_toca_glfw(mglw, monkeypatch):
    """Con monitor 0 alcanza el fullscreen de moderngl-window, asi que no hay
    razon para importar glfw ni para hablarle directo."""
    llamado = False

    def _no_llamar(self, index):
        nonlocal llamado
        llamado = True

    monkeypatch.setattr(WindowPresenter, "_move_to_monitor", _no_llamar)
    WindowPresenter(Settings(render_mode="window", window_fullscreen=True, window_monitor=0))

    assert llamado is False


def test_monitor_secundario_mueve_la_ventana(mglw, monkeypatch):
    pedidos = []
    monkeypatch.setattr(
        WindowPresenter, "_move_to_monitor", lambda self, index: pedidos.append(index)
    )
    WindowPresenter(Settings(render_mode="window", window_fullscreen=True, window_monitor=1))

    assert pedidos == [1]


def test_monitor_inexistente_no_rompe(mglw, monkeypatch, caplog):
    """Pedir el monitor 3 con un solo monitor conectado avisa y sigue en el
    primario: perder el monitor elegido no justifica no proyectar."""
    mode = types.SimpleNamespace(
        size=types.SimpleNamespace(width=1920, height=1080), refresh_rate=60
    )
    fake_glfw = types.ModuleType("glfw")
    fake_glfw.get_monitors = lambda: ["monitor-0"]
    fake_glfw.get_video_mode = lambda monitor: mode
    fake_glfw.set_window_monitor = lambda *args: pytest.fail("no deberia mover la ventana")
    fake_glfw.get_framebuffer_size = lambda handle: (1920, 1080)
    monkeypatch.setitem(sys.modules, "glfw", fake_glfw)

    with caplog.at_level("WARNING"):
        presenter = WindowPresenter(
            Settings(render_mode="window", width=640, height=360, window_monitor=3,
                     window_fullscreen=True)
        )

    assert presenter.size == (800, 450)  # siguio adelante
    assert "monitores" in caplog.text
