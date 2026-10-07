"""Deteccion de movimiento.

Pipeline barato, en 320x240 (Modulo-Camara-Feedback):

    gris -> blur -> diferencia con el fondo -> umbral -> cantidad y centroide

Publica dos valores que los efectos consumen como uniforms: `u_motion` (0..1) y
`u_motion_pos` (centroide normalizado).

**No** hay deteccion de personas ni ML: no da el presupuesto de CPU, y menos en
dos nucleos.

El riesgo de fondo es el **lazo de realimentacion positiva**: la camara ve la
proyeccion, eso cuenta como movimiento, el efecto crece, la camara ve mas. Tres
mitigaciones, todas aca:

- **Banda muerta**: por debajo de un umbral, el movimiento es cero. Corta el
  ruido de sensor y el titileo de la proyeccion.
- **Suavizado temporal (EMA)**: el valor no puede saltar de golpe, asi que un
  pico no realimenta.
- **Tope de ganancia**: el valor se satura en 1.0 por mas area que se mueva.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Fraccion del area que se considera "movimiento maximo". Un 15% de la imagen
# moviendose ya es mucho: con 100% nunca se llegaria a 1.0 en la practica.
AREA_SATURACION = 0.15


class MotionDetector:
    def __init__(
        self,
        dead_band: float = 0.02,
        smoothing: float = 0.25,
        threshold: int = 25,
    ) -> None:
        self.dead_band = dead_band
        # Peso del valor nuevo en la EMA: bajo = mas suave y mas lento.
        self.smoothing = smoothing
        self.threshold = threshold

        self.motion = 0.0
        self.position = (0.5, 0.5)
        self._fondo: Any | None = None
        self._mask: Any | None = None

    def reset(self) -> None:
        """Se llama al cambiar de camara: el fondo viejo no sirve."""
        self._fondo = None
        self._mask = None
        self.motion = 0.0
        self.position = (0.5, 0.5)

    def update(self, frame: Any) -> tuple[float, tuple[float, float]]:
        """Procesa un frame reducido y devuelve (motion, posicion)."""
        try:
            import cv2
        except ImportError:  # pragma: no cover - depende del entorno
            return self.motion, self.position

        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        gris = cv2.GaussianBlur(gris, (5, 5), 0).astype("float32")

        if self._fondo is None:
            self._fondo = gris
            return 0.0, self.position

        diferencia = cv2.absdiff(gris, self._fondo)
        # El fondo se adapta despacio: asi un cambio de luz ambiente deja de
        # contar como movimiento al rato, pero una persona que pasa si cuenta.
        cv2.accumulateWeighted(gris, self._fondo, 0.05)

        _, mascara = cv2.threshold(diferencia, self.threshold, 255, cv2.THRESH_BINARY)
        mascara = mascara.astype("uint8")
        self._mask = mascara

        total = float(mascara.size)
        activos = float(cv2.countNonZero(mascara))
        crudo = min(1.0, (activos / total) / AREA_SATURACION)

        if crudo < self.dead_band:
            crudo = 0.0
        elif activos > 0:
            momentos = cv2.moments(mascara, binaryImage=True)
            if momentos["m00"] > 0:
                self.position = (
                    float(momentos["m10"] / momentos["m00"]) / mascara.shape[1],
                    float(momentos["m01"] / momentos["m00"]) / mascara.shape[0],
                )

        # EMA: el valor no salta, que es lo que impide que un pico realimente.
        self.motion = self.motion + self.smoothing * (crudo - self.motion)
        if self.motion < 1e-4:
            self.motion = 0.0
        return self.motion, self.position

    @property
    def mask(self) -> Any | None:
        """Mascara binaria del ultimo frame, para la vista de depuracion."""
        return self._mask
