"""Proceso ecomap-render: dueno del contexto GL y de la salida de video.

No abre SQLite nunca. Recibe el estado por el bus y publica telemetria por el
mismo socket (ADR-004, ADR-006).
"""

from __future__ import annotations

import logging
import signal
import time
from types import FrameType
from typing import Any

from ecomap_core.protocol import (
    EV_CAMERA,
    EV_ERROR,
    EV_PONG,
    EV_TELE,
    OP_BLACKOUT,
    OP_CAMERA,
    OP_PATTERN,
    OP_PING,
    OP_SCENE,
    ev,
)
from ecomap_core.settings import Settings, load_settings
from ecomap_render import shaders
from ecomap_render.bus import BusServer
from ecomap_render.context import HeadlessPresenter, Presenter, create_presenter
from ecomap_render.pipeline import Pipeline, ShaderError
from ecomap_render.preview import FrameStore, PreviewServer, encode_jpeg
from ecomap_render.telemetry import FrameTimer, read_temp
from ecomap_vision.source import CameraError, CameraSource, open_source

log = logging.getLogger(__name__)

TEMP_PERIOD = 1.0


class RenderApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.running = True
        self.blackout = False
        self.pattern = shaders.PATTERN_HELLO
        self.scene_id: int | None = None

        self.bus = BusServer(settings.bus_address())
        self.presenter: Presenter | None = None
        self.pipeline: Pipeline | None = None
        self.timer = FrameTimer()
        self.frames = FrameStore()
        self.preview: PreviewServer | None = None
        self._temp: float | None = None
        self._temp_at = 0.0
        self._preview_at = 0.0
        self._tele_at = 0.0
        self._preview_warned = False
        self.camera: CameraSource | None = None
        self.camera_source: str | None = None

    # --- arranque y parada ---

    def setup(self) -> None:
        self.bus.start()
        self.presenter = create_presenter(self.settings)
        try:
            self.pipeline = Pipeline(self.presenter.ctx, self.presenter.size)
        except ShaderError as exc:
            # Un shader que no compila no debe tumbar el proceso: se avisa y se
            # proyecta negro hasta que llegue uno bueno.
            log.error("shader del esqueleto no compila: %s", exc)
            self.bus.publish(ev(EV_ERROR, source="shader", level="error", msg=str(exc)))
            self.blackout = True
        if isinstance(self.presenter, HeadlessPresenter):
            self.preview = PreviewServer(self.settings.preview_port, self.frames)
            self.preview.start()

    def teardown(self) -> None:
        self._close_camera()
        if self.preview:
            self.preview.stop()
        if self.pipeline:
            self.pipeline.release()
        if self.presenter:
            self.presenter.close()
        self.bus.stop()

    def stop(self, *_: object) -> None:
        self.running = False

    # --- operaciones entrantes ---

    def apply(self, message: dict[str, Any]) -> None:
        operation = message.get("op")
        if operation == OP_PING:
            self.bus.publish(ev(EV_PONG))
        elif operation == OP_BLACKOUT:
            self.blackout = bool(message.get("on"))
            log.info("blackout: %s", self.blackout)
        elif operation == OP_PATTERN:
            name = str(message.get("name", "off"))
            self.pattern = shaders.PATTERN_BY_NAME.get(name, shaders.PATTERN_HELLO)
            log.info("patron: %s", name)
        elif operation == OP_CAMERA:
            self._select_camera(str(message.get("source", "")))
        elif operation == OP_SCENE:
            self._apply_scene(message.get("scene") or {})
        else:
            log.debug("operacion ignorada en el Hito 0: %s", operation)

    # --- loop ---

    def run(self) -> None:
        assert self.presenter is not None
        target_frame = 1.0 / max(self.settings.fps, 1)
        tele_period = 1.0 / self.settings.telemetry_hz
        started = time.perf_counter()
        previous = started
        # Cadencia fija: se acumula sobre el instante ideal del proximo frame en
        # vez de restar el frame anterior, que se realimenta y termina corriendo
        # al doble del objetivo.
        next_frame = started

        while self.running and not self.presenter.should_close():
            for message in self.bus.poll():
                self.apply(message)

            now = time.perf_counter()
            elapsed = now - started
            fbo = self.presenter.begin_frame()
            if self.pipeline is not None:
                self.pipeline.render(
                    fbo,
                    time=elapsed,
                    pattern=self.pattern,
                    blackout=self.blackout,
                )
            else:
                self.presenter.ctx.clear(0.0, 0.0, 0.0)
            self.presenter.end_frame()

            self._maybe_preview(now)
            self._maybe_telemetry(now, tele_period)

            done = time.perf_counter()
            work_seconds = done - now
            self.timer.add(period_seconds=done - previous, work_seconds=work_seconds)
            previous = done

            # En headless no hay vsync que regule; en window lo hace el driver.
            next_frame += target_frame
            sleep_for = next_frame - time.perf_counter()
            if self.settings.render_mode == "window":
                continue
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                # No se llego al presupuesto: se resincroniza para no acumular
                # deuda y entrar en espiral.
                next_frame = time.perf_counter()

    # --- escena ---

    def _apply_scene(self, scene: dict[str, Any]) -> None:
        """Reconstruye la geometria de las superficies.

        Llega entera, no por diferencias: es poca data, se manda en cada cambio
        y al reconectar, y evita que el render tenga que razonar sobre el orden
        de los mensajes.
        """
        if self.pipeline is None:
            return
        surfaces = scene.get("surfaces") or []
        self.pipeline.set_surfaces(surfaces)
        self.scene_id = scene.get("calibration_version")

    # --- camara ---

    def _close_camera(self) -> None:
        if self.camera is None:
            return
        try:
            self.camera.close()
        except Exception:  # noqa: BLE001 - cerrar no debe tumbar el render
            log.warning("camara: fallo al cerrar", exc_info=True)
        self.camera = None

    def _select_camera(self, source: str) -> None:
        """Abre la camara pedida y reporta el resultado real por el bus.

        Una camara que no se puede abrir **no** es motivo para cortar la
        proyeccion: se deja sin camara, se avisa, y los efectos que piden
        `u_cam` reciben textura negra.
        """
        self._close_camera()
        self.camera_source = source or None
        if not source:
            self.bus.publish(ev(EV_CAMERA, state="closed", source=None))
            return
        try:
            self.camera = open_source(source)
        except CameraError as exc:
            log.warning("camara: %s", exc)
            self.bus.publish(ev(EV_CAMERA, state="error", source=source, message=str(exc)))
            return
        info = self.camera.info
        log.info(
            "camara abierta: %s %sx%s @ %.0f fps (%s)",
            info.uri,
            info.width,
            info.height,
            info.fps,
            info.backend,
        )
        self.bus.publish(
            ev(
                EV_CAMERA,
                state="open",
                source=source,
                width=info.width,
                height=info.height,
                fps=info.fps,
                backend=info.backend,
            )
        )

    def _maybe_preview(self, now: float) -> None:
        if self.preview is None or not isinstance(self.presenter, HeadlessPresenter):
            return
        if now - self._preview_at < 1.0 / max(self.settings.preview_fps, 1):
            return
        self._preview_at = now
        width, height = self.presenter.size
        jpeg = encode_jpeg(self.presenter.read(), width, height)
        if jpeg is None:
            if not self._preview_warned:
                log.warning("preview: sin OpenCV instalado, no se publica MJPEG")
                self._preview_warned = True
            return
        self.frames.put(jpeg)

    def _maybe_telemetry(self, now: float, period: float) -> None:
        if now - self._tele_at < period:
            return
        self._tele_at = now
        if now - self._temp_at >= TEMP_PERIOD:
            self._temp = read_temp()
            self._temp_at = now
        self.bus.publish(
            ev(
                EV_TELE,
                fps=round(self.timer.fps, 2),
                frame_ms=round(self.timer.frame_ms, 2),
                frame_ms_max=round(self.timer.frame_ms_max, 2),
                temp=self._temp,
                dropped=self.bus.dropped_events,
                scene_id=self.scene_id,
                mode=self.settings.render_mode,
            )
        )
        self.timer.reset_peak()


def run() -> None:
    """Entry point `ecomap-render`."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    app = RenderApp(settings)

    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("render: senal %s, cerrando", signum)
        app.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    app.setup()
    try:
        app.run()
    finally:
        app.teardown()
        log.info("render: cerrado")


if __name__ == "__main__":
    run()
