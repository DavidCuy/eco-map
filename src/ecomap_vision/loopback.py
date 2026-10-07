"""Camara virtual: devuelve lo que el proyector acaba de dibujar, deformado.

Es un banco de pruebas proyector-camara **en software**. Cierra el lazo que en
la realidad pasa por una pared: toma el frame que el render presento, lo
deforma con una homografia que uno elige, lo degrada, y lo devuelve como si
fuera una camara mirando la proyeccion.

Para que sirve:

- Probar la auto-calibracion sabiendo la respuesta correcta. Con hardware solo
  se puede decir "se ve bien"; aca se compara contra la homografia que se uso
  para simular.
- Probar el lazo de realimentacion de `camera_echo` sin montar nada.
- Probar casos que en una sala serian un dia de trabajo: ruido alto,
  desenfoque, una esquina fuera de cuadro.

Lo que **no** puede simular, y por eso no reemplaza al hardware: la exposicion
automatica de una webcam que ignora los controles, el tiempo real de
asentamiento entre proyectar y capturar, y el ruido de un sensor barato.

URI: `loopback://` con parametros opcionales, por ejemplo
`loopback://?noise=6&blur=5`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np

from ecomap_vision.source import CameraError, CameraInfo

log = logging.getLogger(__name__)

# Proveedor del ultimo frame proyectado. Lo registra el render, que es el unico
# que lo tiene.
FrameProvider = Callable[[], tuple[np.ndarray | None, tuple[int, int]]]

_provider: FrameProvider | None = None


def set_frame_provider(provider: FrameProvider | None) -> None:
    global _provider
    _provider = provider


class LoopbackSource:
    """Camara simulada que mira lo que el proyector dibuja."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        noise: float = 2.0,
        blur: int = 3,
        gain: float = 0.85,
        ambient: float = 10.0,
    ) -> None:
        if _provider is None:
            raise CameraError(
                "loopback:// solo funciona dentro del render, que es quien tiene "
                "el frame proyectado"
            )
        self.size = (width, height)
        self.noise = noise
        self.blur = blur if blur % 2 == 1 else blur + 1
        self.gain = gain
        self.ambient = ambient
        self._rng = np.random.default_rng(0)
        self._homografia: Any | None = None
        self.info = CameraInfo(
            uri="loopback://", width=width, height=height, fps=15.0, backend="loopback"
        )

    def _asegurar_homografia(self, proj_size: tuple[int, int]) -> Any:
        """Una vista en perspectiva fija, como una camara al costado del
        proyector. Se calcula una vez y no cambia: mover la camara a mitad de
        una calibracion la invalidaria, igual que en la realidad."""
        import cv2

        if self._homografia is not None:
            return self._homografia
        ancho, alto = proj_size
        cam_w, cam_h = self.size
        origen = np.float32([[0, 0], [ancho, 0], [ancho, alto], [0, alto]])
        destino = np.float32(
            [
                [cam_w * 0.18, cam_h * 0.14],
                [cam_w * 0.88, cam_h * 0.22],
                [cam_w * 0.83, cam_h * 0.86],
                [cam_w * 0.12, cam_h * 0.78],
            ]
        )
        self._homografia = cv2.getPerspectiveTransform(origen, destino)
        return self._homografia

    @property
    def truth(self) -> Any | None:
        """La homografia que usa el banco. Es la verdad contra la que se puede
        comparar lo que estime la calibracion."""
        return self._homografia

    def read(self) -> np.ndarray | None:
        import cv2

        if _provider is None:
            return None
        frame, proj_size = _provider()
        if frame is None:
            return None

        H = self._asegurar_homografia(proj_size)
        vista = cv2.warpPerspective(frame, H, self.size)
        vista = vista.astype(np.float32) * self.gain + self.ambient
        if self.blur > 1:
            vista = cv2.GaussianBlur(vista, (self.blur, self.blur), 0)
        if self.noise:
            vista = vista + self._rng.normal(0, self.noise, vista.shape)
        gris = np.clip(vista, 0, 255).astype(np.uint8)
        # BGR de tres canales, como entrega OpenCV: el resto del sistema
        # —textura de camara, detector de movimiento— cuenta con eso, y una
        # camara simulada que entregue otra cosa no simula nada.
        return cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)

    def close(self) -> None:
        return


def from_uri(uri: str) -> LoopbackSource:
    parsed = urlparse(uri)
    q = parse_qs(parsed.query)

    def num(clave: str, default: float) -> float:
        try:
            return float(q[clave][0])
        except (KeyError, ValueError):
            return default

    return LoopbackSource(
        width=int(num("width", 640)),
        height=int(num("height", 480)),
        noise=num("noise", 2.0),
        blur=int(num("blur", 3)),
        gain=num("gain", 0.85),
        ambient=num("ambient", 10.0),
    )
