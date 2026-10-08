"""Hilo de captura.

Corre dentro del proceso de render: comparte el contexto GL, asi que subir la
textura de camara no cuesta una copia entre procesos (Modulo-Camara-Feedback).

Tres decisiones que vienen de ADR-010 y del presupuesto:

- **Cola de un frame, drop-oldest.** Un frame viejo no sirve para nada: lo que
  importa es el ultimo. Acumular es acumular latencia.
- **Reduccion por CPU a 320x240.** Sin el ISP de una camara CSI no hay stream
  `lores` gratis, asi que se captura a 640x480 y se reduce. Es el costo que en
  dos nucleos mas preocupa, por eso se mide y se publica.
- **Descarte activo si la latencia crece.** `CAP_PROP_BUFFERSIZE=1` lo respetan
  los drivers de forma desigual; cuando el frame tarda mas de lo que deberia,
  se vacia el buffer con `grab()` sin decodificar.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from ecomap_vision.source import CameraError, CameraSource, open_source

log = logging.getLogger(__name__)

PROCESS_WIDTH = 320
PROCESS_HEIGHT = 240
REOPEN_SECONDS = 3.0


class CaptureStats:
    """Lo que el hilo sabe de si mismo. Se publica en la telemetria porque en
    dos nucleos el costo de la camara es el riesgo principal."""

    def __init__(self) -> None:
        self.fps = 0.0
        self.read_ms = 0.0     # leer y decodificar MJPEG
        self.resize_ms = 0.0   # reducir a la resolucion de proceso
        self.dropped = 0
        self.errors = 0


class CameraThread:
    """Lee de una `CameraSource` en segundo plano y deja el ultimo frame listo."""

    def __init__(self, uri: str, target_fps: int = 15, detector: Any | None = None) -> None:
        self.uri = uri
        self.target_fps = max(target_fps, 1)
        self.stats = CaptureStats()
        # El detector corre **en este hilo**: es el hilo de vision. Si corriera
        # en el loop de render, el costo de la deteccion se sumaria al frame.
        self.detector = detector
        self.motion = 0.0
        self.motion_pos = (0.5, 0.5)
        self.motion_ms = 0.0

        # Resultado de abrir, que ocurre dentro del hilo y no en `start()`.
        self.opened = False
        self.error: str | None = None
        self._listo = threading.Event()

        self._source: CameraSource | None = None
        self._lock = threading.Lock()
        self._ultimo: Any | None = None       # frame a resolucion de captura
        self._ultimo_chico: Any | None = None  # reducido, para procesar
        self._seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._periodos: deque[float] = deque(maxlen=30)

    # --- ciclo de vida ---

    def start(self) -> None:
        """Lanza el hilo. **Abrir la camara pasa adentro del hilo**, no aca.

        Medido en Windows con DirectShow: abrir una webcam tarda casi 5
        segundos. Como el que llama a esto es el loop de render, abrir de forma
        sincrona dejaba la proyeccion congelada todo ese rato cada vez que
        alguien cambiaba de camara. En V4L2 es casi inmediato, pero no hay
        motivo para que el render dependa de cual sea el backend.

        El resultado se consulta con `wait_ready()`, o leyendo `opened` y
        `error` cuando `ready` ya es True. El render lo publica por el bus
        desde **su** hilo, que es donde vive el bus.
        """
        self._stop.clear()
        self._listo.clear()
        self.opened = False
        self.error = None
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()
        log.info("camara: hilo iniciado, abriendo %s", self.uri)

    @property
    def ready(self) -> bool:
        """True cuando el intento de abrir termino, con exito o sin el."""
        return self._listo.is_set()

    def wait_ready(self, timeout: float | None = None) -> bool:
        """Espera a que termine de abrir. Devuelve si quedo abierta.

        Para tests y scripts: el render no espera, consulta `ready`.
        """
        self._listo.wait(timeout)
        return self.opened

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._source is not None:
            self._source.close()
            self._source = None

    @property
    def info(self):
        return self._source.info if self._source else None

    # --- consumo ---

    def latest(self) -> tuple[Any | None, Any | None, int]:
        """Ultimo frame (completo, reducido, numero de secuencia).

        El numero de secuencia permite saber si hay algo nuevo sin comparar
        imagenes: el render lo usa para no volver a subir la misma textura.
        """
        with self._lock:
            return self._ultimo, self._ultimo_chico, self._seq

    # --- interno ---

    def _loop(self) -> None:
        try:
            self._source = open_source(self.uri)
        except CameraError as exc:
            self.error = str(exc)
            log.warning("camara: %s", exc)
            self._listo.set()
            return
        except Exception as exc:  # noqa: BLE001 - abrir no debe tumbar el render
            self.error = f"error inesperado al abrir la camara: {exc}"
            log.exception("camara: fallo inesperado al abrir")
            self._listo.set()
            return
        self.opened = True
        self._listo.set()

        periodo = 1.0 / self.target_fps
        proximo = time.perf_counter()
        anterior = proximo

        while not self._stop.is_set():
            inicio = time.perf_counter()
            try:
                frame = self._source.read() if self._source else None
            except Exception:  # noqa: BLE001 - un error de lectura no mata el hilo
                log.exception("camara: fallo al leer")
                frame = None

            if frame is None:
                self.stats.errors += 1
                self._reabrir()
                continue

            leido = time.perf_counter()
            chico = self._reducir(frame)
            redimensionado = time.perf_counter()

            if self.detector is not None:
                self.motion, self.motion_pos = self.detector.update(chico)
                self.motion_ms = (time.perf_counter() - redimensionado) * 1000.0

            with self._lock:
                self._ultimo = frame
                self._ultimo_chico = chico
                self._seq += 1

            self.stats.read_ms = (leido - inicio) * 1000.0
            self.stats.resize_ms = (redimensionado - leido) * 1000.0
            self._periodos.append(redimensionado - anterior)
            anterior = redimensionado
            if self._periodos:
                medio = sum(self._periodos) / len(self._periodos)
                self.stats.fps = 1.0 / medio if medio > 0 else 0.0

            proximo += periodo
            sobra = proximo - time.perf_counter()
            if sobra > 0:
                time.sleep(sobra)
            else:
                # Se fue de tiempo: el buffer del driver puede estar acumulando
                # frames viejos. Se descartan sin decodificar, que es barato.
                self._descartar_atrasados()
                proximo = time.perf_counter()

    def _reducir(self, frame: Any) -> Any:
        try:
            import cv2
        except ImportError:  # pragma: no cover - depende del entorno
            return frame
        if frame.shape[1] == PROCESS_WIDTH and frame.shape[0] == PROCESS_HEIGHT:
            return frame
        return cv2.resize(
            frame, (PROCESS_WIDTH, PROCESS_HEIGHT), interpolation=cv2.INTER_AREA
        )

    def _descartar_atrasados(self) -> None:
        """Vacia el buffer del driver sin decodificar.

        `grab()` saca el frame de la cola y no lo convierte, que es justo lo
        caro de MJPEG. Sin esto la latencia crece hasta hacerse visible.
        """
        capture = getattr(self._source, "_capture", None)
        if capture is None:
            return
        for _ in range(2):
            if not capture.grab():
                break
            self.stats.dropped += 1

    def _reabrir(self) -> None:
        """Un desconectado y vuelto a conectar no deberia requerir reiniciar."""
        time.sleep(REOPEN_SECONDS)
        if self._stop.is_set():
            return
        try:
            if self._source is not None:
                self._source.close()
            self._source = open_source(self.uri)
            log.info("camara: reabierta")
        except CameraError as exc:
            log.warning("camara: no se pudo reabrir (%s)", exc)
