"""Proceso ecomap-render: dueno del contexto GL y de la salida de video.

No abre SQLite nunca. Recibe el estado por el bus y publica telemetria por el
mismo socket (ADR-004, ADR-006).
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from types import FrameType
from typing import Any

from ecomap_core.protocol import (
    EV_CALIB,
    EV_CAMERA,
    EV_EFFECTS,
    EV_ERROR,
    EV_PONG,
    EV_TELE,
    OP_BLACKOUT,
    OP_CALIBRATE,
    OP_CAMERA,
    OP_EFFECT,
    OP_EFFECTS_RELOAD,
    OP_MOTION,
    OP_PING,
    OP_SCENE,
    ev,
)
from ecomap_core.settings import Settings, load_settings
from ecomap_render.bus import BusServer
from ecomap_render.calibration import CalibrationRunner
from ecomap_render.context import HeadlessPresenter, Presenter, create_presenter
from ecomap_render.pipeline import Pipeline, ShaderError
from ecomap_render.preview import FrameStore, PreviewServer, encode_jpeg, encode_jpeg_bgr
from ecomap_render.telemetry import FrameTimer, read_temp
from ecomap_vision.capture import CameraThread
from ecomap_vision.loopback import set_frame_provider
from ecomap_vision.motion import MotionDetector

log = logging.getLogger(__name__)

TEMP_PERIOD = 1.0


class RenderApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.running = True
        self.blackout = False
        self.effect_id: str | None = None
        # Instante en que llego una op que cambia lo que se ve, para medir
        # cuanto tarda en aparecer en pantalla (RNF-2).
        self._op_recibida: float | None = None
        self.apply_ms = 0.0
        self.scene_id: int | None = None

        self.bus = BusServer(settings.bus_address())
        self.presenter: Presenter | None = None
        self.pipeline: Pipeline | None = None
        self.timer = FrameTimer()
        self.frames = FrameStore()
        self.camera_frames = FrameStore()
        self.preview: PreviewServer | None = None
        self._temp: float | None = None
        self._temp_at = 0.0
        self._preview_at = 0.0
        self._tele_at = 0.0
        self._preview_warned = False
        self.camera: CameraThread | None = None
        self.camera_source: str | None = None
        self._camara_anunciada = True
        self.detector = MotionDetector()
        self.calibration: CalibrationRunner | None = None
        self._proyectado: Any | None = None
        self._proyectado_lock = threading.Lock()
        self._loopback = False

    # --- arranque y parada ---

    def setup(self) -> None:
        self.bus.start()
        self.presenter = create_presenter(self.settings)
        # La camara virtual necesita el frame proyectado, y el unico que lo
        # tiene es este proceso. Se registra siempre: `loopback://` sin
        # proveedor falla con un mensaje claro, no silenciosamente.
        set_frame_provider(self._frame_proyectado)
        try:
            self.pipeline = Pipeline(
                self.presenter.ctx, self.presenter.size, self.settings.effects_dir
            )
        except ShaderError as exc:
            # Un shader que no compila no debe tumbar el proceso: se avisa y se
            # proyecta negro hasta que llegue uno bueno.
            log.error("shader del esqueleto no compila: %s", exc)
            self.bus.publish(ev(EV_ERROR, source="shader", level="error", msg=str(exc)))
            self.blackout = True
        self._publish_effects()
        if isinstance(self.presenter, HeadlessPresenter):
            self.preview = PreviewServer(
                self.settings.preview_port, self.frames, self.camera_frames
            )
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
        elif operation == OP_EFFECTS_RELOAD:
            if self.pipeline is not None:
                self.pipeline.library.reload()
                self._publish_effects()
        elif operation == OP_EFFECT:
            self._select_effect(str(message.get("id", "")), dict(message.get("params") or {}))
        elif operation == OP_CALIBRATE:
            self._start_calibration(dict(message))
        elif operation == OP_MOTION:
            self.detector.dead_band = float(message.get("dead_band", self.detector.dead_band))
            self.detector.smoothing = float(message.get("smoothing", self.detector.smoothing))
            self.detector.threshold = int(message.get("threshold", self.detector.threshold))
            log.info(
                "deteccion: banda muerta %.3f, suavizado %.2f, umbral %d",
                self.detector.dead_band,
                self.detector.smoothing,
                self.detector.threshold,
            )
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
            mensajes = self.bus.poll()
            if mensajes:
                self._op_recibida = time.perf_counter()
            for message in mensajes:
                self.apply(message)

            now = time.perf_counter()
            elapsed = now - started
            fbo = self.presenter.begin_frame()
            if self.calibration is not None and self.pipeline is not None:
                # Durante la calibracion la proyeccion es la secuencia: lo que
                # haya configurado espera, que es lo que el operador espera.
                self.calibration.draw(
                    self.presenter.ctx, fbo, self.pipeline.warp_program, self.pipeline.vao_full
                )
            elif self.pipeline is not None:
                self.pipeline.render(fbo, time=elapsed, blackout=self.blackout)
            else:
                self.presenter.ctx.clear(0.0, 0.0, 0.0)
            self.presenter.end_frame()

            if self._loopback:
                # Antes de avanzar la calibracion: la camara virtual tiene que
                # ver el patron que se acaba de presentar, no el anterior.
                self._publicar_proyectado()

            if self.calibration is not None:
                self._tick_calibration()

            if self._op_recibida is not None:
                # De op recibida a frame presentado. Es el tramo que el render
                # controla; el resto de la latencia es navegador, HTTP y bus.
                self.apply_ms = (time.perf_counter() - self._op_recibida) * 1000.0
                self._op_recibida = None

            self._anunciar_camara()
            self._update_camera()
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

    def _publish_effects(self) -> None:
        """Avisa que efectos compilaron y cuales no.

        El web lee los manifiestos, pero quien compila es el render: si un
        shader no pasa el compilador del driver, solo el render se entera. Sin
        esto, la UI ofreceria un efecto que no se puede usar.
        """
        if self.pipeline is None:
            return
        self.bus.publish(
            ev(
                EV_EFFECTS,
                compiled=sorted(self.pipeline.library.compiled),
                errors=dict(self.pipeline.library.errors),
            )
        )

    def _select_effect(self, effect_id: str, params: dict[str, Any]) -> None:
        """Cambia el efecto activo y reporta si no se pudo.

        Un efecto que no compila o que no esta en el catalogo no corta la
        proyeccion: se sigue con el anterior y la UI muestra el motivo.
        """
        if self.pipeline is None:
            return
        error = self.pipeline.set_fallback_effect(effect_id, params)
        if error:
            self.bus.publish(
                ev(EV_ERROR, source="effect", level="error", msg=f"{effect_id}: {error}")
            )
        else:
            self.effect_id = effect_id

    # --- calibracion ---

    def _start_calibration(self, mensaje: dict[str, Any]) -> None:
        """Arranca la secuencia de Gray code, o cancela la que este corriendo.

        Requiere camara: sin ella no hay nada que decodificar. Se rechaza
        explicitamente en vez de correr la secuencia entera y fallar al final.
        """
        if mensaje.get("cancel"):
            # Cancelar no deja nada a medias: el runner se descarta y el frame
            # siguiente vuelve a dibujar la escena configurada.
            if self.calibration is not None:
                self.calibration.cancel()
                self._tick_calibration()
            else:
                self.bus.publish(
                    ev(EV_CALIB, done=True, ok=False, msg="no habia calibracion en curso")
                )
            return
        if self.camera is None:
            self.bus.publish(
                ev(EV_CALIB, done=True, ok=False, msg="no hay camara abierta")
            )
            return
        if self.presenter is None:
            return
        self.calibration = CalibrationRunner(
            size=self.presenter.size,
            settle=int(mensaje.get("settle", 2)),
            max_bits=int(mensaje.get("max_bits", 8)),
        )
        self.bus.publish(ev(EV_CALIB, progress=0.0, stage="arrancando", done=False))

    def _tick_calibration(self) -> None:
        runner = self.calibration
        if runner is None:
            return
        # El frame **completo**, no el reducido que usa la deteccion de
        # movimiento: las franjas finas no sobreviven a un resize a 320x240, y
        # decodificarlas mal es justo lo que da una homografia invertida. Son
        # ~34 frames una sola vez, no por cuadro.
        frame, _chico, seq = self.camera.latest() if self.camera else (None, None, 0)
        antes = runner.index
        runner.tick(seq, frame)

        if runner.index != antes and runner.active:
            self.bus.publish(
                ev(EV_CALIB, progress=runner.progress, stage=runner.stage, done=False)
            )

        if not runner.active:
            resultado = runner.result
            self.calibration = None
            if resultado is None:
                return
            log.info(
                "calibracion terminada: ok=%s %s", resultado.ok, resultado.message
            )
            self.bus.publish(
                ev(
                    EV_CALIB,
                    done=True,
                    ok=resultado.ok,
                    msg=resultado.message,
                    homography=resultado.homography,
                    rms=resultado.rms,
                    inliers=resultado.inliers,
                    coverage=round(resultado.coverage, 3),
                    camera_size=list(resultado.camera_size or ()),
                    proj_size=list(resultado.proj_size or ()),
                )
            )

    # --- escena ---

    def _apply_scene(self, scene: dict[str, Any]) -> None:
        """Reconstruye la geometria de las superficies.

        Llega entera, no por diferencias: es poca data, se manda en cada cambio
        y al reconectar, y evita que el render tenga que razonar sobre el orden
        de los mensajes.
        """
        if self.pipeline is None:
            return
        self.pipeline.set_scene(scene)
        self.scene_id = scene.get("scene_id")

    # --- camara ---

    def _close_camera(self) -> None:
        if self.camera is None:
            return
        try:
            self.camera.stop()
        except Exception:  # noqa: BLE001 - cerrar no debe tumbar el render
            log.warning("camara: fallo al cerrar", exc_info=True)
        self.camera = None
        self.detector.reset()  # el fondo de la camara vieja no sirve

    def _select_camera(self, source: str) -> None:
        """Pide abrir la camara. El resultado real lo publica `_anunciar_camara`.

        **No espera a que abra.** Medido en Windows con DirectShow, abrir una
        webcam tarda casi 5 segundos, y este metodo corre dentro del loop de
        render: esperar dejaba la proyeccion congelada todo ese rato. El hilo
        de camara abre por su cuenta y el loop publica el desenlace cuando
        llega.

        Una camara que no se puede abrir **no** es motivo para cortar la
        proyeccion: se sigue sin camara, se avisa, y los efectos que piden
        `u_cam` reciben textura negra.
        """
        self._close_camera()
        self.camera_source = source or None
        if not source:
            self.bus.publish(ev(EV_CAMERA, state="closed", source=None))
            return
        self._loopback = source.startswith("loopback")
        self.camera = CameraThread(source, detector=self.detector)
        self._camara_anunciada = False
        self.camera.start()
        # "opening" es la respuesta honesta mientras tanto: el web ya lo sabe
        # mostrar, y evita que la UI quede con el estado de la camara anterior.
        self.bus.publish(ev(EV_CAMERA, state="opening", source=source))

    def _anunciar_camara(self) -> None:
        """Publica como termino de abrir la camara, una sola vez.

        Corre en el hilo de render a proposito: el bus es suyo, y asi el hilo
        de camara no necesita saber que existe.
        """
        camara = self.camera
        if camara is None or self._camara_anunciada or not camara.ready:
            return
        self._camara_anunciada = True
        fuente = self.camera_source or ""

        if not camara.opened:
            mensaje = camara.error or "no se pudo abrir"
            self.camera = None
            self.bus.publish(ev(EV_CAMERA, state="error", source=fuente, message=mensaje))
            return

        info = camara.info
        log.info(
            "camara abierta: %s %sx%s @ %.0f fps (%s, formato %s)",
            info.uri,
            info.width,
            info.height,
            info.fps,
            info.backend,
            info.fourcc or "?",
        )
        if info.fourcc and info.fourcc != "MJPG":
            # Sin MJPG el ancho de banda USB limita los fps por mas que
            # CAP_PROP_FPS diga otra cosa (ADR-010). Donde no hay v4l2-ctl,
            # este aviso es lo unico que lo dice.
            log.warning(
                "camara %s: el driver entrega %s en vez de MJPG; los fps van a "
                "estar limitados por el bus USB",
                info.uri,
                info.fourcc,
            )
        self.bus.publish(
            ev(
                EV_CAMERA,
                state="open",
                source=fuente,
                width=info.width,
                height=info.height,
                fps=info.fps,
                backend=info.backend,
                fourcc=info.fourcc,
            )
        )

    def _update_camera(self) -> None:
        """Pasa el ultimo frame y el movimiento al pipeline.

        El hilo de vision va a 15 fps y el loop a 60: la textura solo se sube
        cuando hay un frame nuevo, lo demas seria copiar lo mismo tres veces.
        """
        if self.camera is None or self.pipeline is None or not self.camera.opened:
            return
        frame, _chico, seq = self.camera.latest()
        self.pipeline.update_camera(frame, seq)
        self.pipeline.motion = self.camera.motion
        self.pipeline.motion_pos = self.camera.motion_pos

    # --- camara virtual (loopback://) ---

    def _frame_proyectado(self) -> tuple[Any | None, tuple[int, int]]:
        """Ultimo frame presentado, para la camara virtual.

        Lo lee el hilo de **render** y lo deja aca copiado: el hilo de vision
        no puede tocar el contexto GL, y leerlo desde alli daria basura o un
        cierre del proceso.
        """
        with self._proyectado_lock:
            return self._proyectado, (self.presenter.size if self.presenter else (0, 0))

    def _publicar_proyectado(self) -> None:
        """Baja el framebuffer a CPU para que la camara virtual lo lea.

        Solo cuando hay una camara `loopback://` abierta: leer el framebuffer
        por frame es caro, y con una camara real no sirve de nada.
        """
        leer = getattr(self.presenter, "read", None)
        if leer is None or self.presenter is None:
            return
        try:
            import cv2
            import numpy as np
        except ImportError:  # pragma: no cover - depende del entorno
            return
        ancho, alto = self.presenter.size
        rgb = np.frombuffer(leer(), dtype=np.uint8).reshape(alto, ancho, 3)
        # El framebuffer de GL tiene el origen abajo; una camara, arriba.
        gris = cv2.cvtColor(np.flipud(rgb), cv2.COLOR_RGB2GRAY)
        with self._proyectado_lock:
            self._proyectado = gris

    def _maybe_preview(self, now: float) -> None:
        if self.preview is None or not isinstance(self.presenter, HeadlessPresenter):
            return
        if now - self._preview_at < 1.0 / max(self.settings.preview_fps, 1):
            return
        self._preview_at = now
        self._publicar_camara()
        width, height = self.presenter.size
        jpeg = encode_jpeg(self.presenter.read(), width, height)
        if jpeg is None:
            if not self._preview_warned:
                log.warning("preview: sin OpenCV instalado, no se publica MJPEG")
                self._preview_warned = True
            return
        self.frames.put(jpeg)

    def _publicar_camara(self) -> None:
        """Publica el ultimo frame de camara como MJPEG, al mismo ritmo que el
        preview de la proyeccion: es para apuntar la camara, no para monitorear."""
        if self.camera is None:
            return
        frame, _chico, _seq = self.camera.latest()
        if frame is None:
            return
        alto, ancho = frame.shape[:2]
        jpeg = encode_jpeg_bgr(frame, ancho, alto)
        if jpeg is not None:
            self.camera_frames.put(jpeg)

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
                camera_fps=round(self.camera.stats.fps, 1) if self.camera else 0.0,
                camera_read_ms=round(self.camera.stats.read_ms, 2) if self.camera else 0.0,
                camera_motion_ms=round(self.camera.motion_ms, 2) if self.camera else 0.0,
                motion=round(self.camera.motion, 3) if self.camera else 0.0,
                scene_id=self.scene_id,
                apply_ms=round(self.apply_ms, 2),
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
