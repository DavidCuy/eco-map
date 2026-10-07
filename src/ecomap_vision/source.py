"""Fuentes de camara.

Dos implementaciones (ADR-010): webcam USB por V4L2 y una simulada para
desarrollar sin hardware. El pipeline de movimiento y la textura `u_cam` llegan
en el Hito 4; lo que hay aca es lo necesario para **abrir, verificar y cerrar**
una camara, que es lo que el selector del dashboard necesita para dar una
respuesta honesta.

URIs aceptadas:
    fake://                     patron sintetico
    fake:///ruta/video.mp4      archivo reproducido en loop (requiere OpenCV)
    v4l2:///dev/video0          webcam
    v4l2:///dev/v4l/by-id/...   webcam por ruta estable (preferida)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 15


class CameraError(RuntimeError):
    """La camara no se pudo abrir o leer."""


@dataclass
class CameraInfo:
    uri: str
    width: int
    height: int
    fps: float
    backend: str


class CameraSource(Protocol):
    info: CameraInfo

    def read(self) -> Any | None: ...

    def close(self) -> None: ...


class FakeSource:
    """Patron sintetico o archivo de video. Permite desarrollar sin camara."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._capture = None
        self._frame = 0
        if path:
            cv2 = _import_cv2()
            capture = cv2.VideoCapture(path)
            if not capture.isOpened():
                raise CameraError(f"no se pudo abrir el video simulado: {path}")
            self._capture = capture
            self._cv2 = cv2
            ancho = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or DEFAULT_WIDTH
            alto = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or DEFAULT_HEIGHT
            fps = float(capture.get(cv2.CAP_PROP_FPS)) or DEFAULT_FPS
        else:
            ancho, alto, fps = DEFAULT_WIDTH, DEFAULT_HEIGHT, float(DEFAULT_FPS)
        self.info = CameraInfo(
            uri=f"fake://{path or ''}",
            width=ancho,
            height=alto,
            fps=fps,
            backend="fake",
        )

    def read(self) -> Any | None:
        if self._capture is not None:
            ok, frame = self._capture.read()
            if not ok:  # fin del archivo: vuelve al principio
                self._capture.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._capture.read()
            return frame if ok else None

        import numpy as np

        self._frame += 1
        # Degradado que se desplaza: sirve para ver que los frames avanzan.
        fila = (np.arange(self.info.width, dtype=np.uint8) + self._frame) % 255
        frame = np.tile(fila, (self.info.height, 1))
        return np.dstack([frame, np.roll(frame, 40), np.roll(frame, 80)])

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class OpenCVSource:
    """Webcam USB por V4L2.

    MJPG es obligatorio: con YUYV sin comprimir el ancho de banda USB limita a
    pocos fps (ADR-010). `BUFFERSIZE=1` lo respetan los drivers de forma
    desigual, asi que el consumidor debe descartar frames si la latencia crece.
    """

    def __init__(
        self,
        device: str,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fps: int = DEFAULT_FPS,
    ) -> None:
        cv2 = _import_cv2()
        self._cv2 = cv2
        capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not capture.isOpened():
            capture.release()
            raise CameraError(
                f"no se pudo abrir {device}: no existe, esta en uso, "
                "o no esta montado dentro del contenedor"
            )
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("M", "J", "P", "G"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        ok, _ = capture.read()
        if not ok:
            capture.release()
            raise CameraError(f"{device} se abrio pero no entrega frames")

        self._capture = capture
        self.info = CameraInfo(
            uri=f"v4l2://{device}",
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or width,
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height,
            fps=float(capture.get(cv2.CAP_PROP_FPS)) or float(fps),
            backend="v4l2",
        )

    def read(self) -> Any | None:
        ok, frame = self._capture.read()
        return frame if ok else None

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def _import_cv2():
    """Import perezoso: el render sin camara no deberia necesitar OpenCV."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise CameraError("OpenCV no esta instalado: instalar el extra `vision`") from exc
    return cv2


def open_source(uri: str, **kwargs: Any) -> CameraSource:
    """Abre la fuente que describe `uri`. Lanza CameraError si no se puede."""
    parsed = urlparse(uri)
    esquema = parsed.scheme or "fake"
    ruta = parsed.path or ""

    if esquema == "fake":
        return FakeSource(ruta or None)
    if esquema == "v4l2":
        if not ruta:
            raise CameraError(f"uri de camara sin device: {uri!r}")
        return OpenCVSource(ruta, **kwargs)
    raise CameraError(f"esquema de camara desconocido: {esquema!r}")
