"""Medicion de frame time y temperatura.

Se mide `frame_ms` real y su pico, no solo el promedio: el jitter es lo que se
ve en la pared (Presupuesto-de-Rendimiento).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

THERMAL_PATHS = (Path("/sys/class/thermal/thermal_zone0/temp"),)


class FrameTimer:
    """Separa dos cosas que se confunden facil:

    - **periodo**: cuanto pasa entre frames. Define los fps y esta topeado por
      el limitador, asi que con fps objetivo 60 siempre dara ~16.7 ms.
    - **trabajo**: cuanto cuesta producir el frame, sin contar la espera. Es lo
      que hay que mirar para decidir si hay que degradar (US-30).
    """

    def __init__(self, window: int = 120) -> None:
        self._periods: deque[float] = deque(maxlen=window)
        self._work: deque[float] = deque(maxlen=window)

    def add(self, period_seconds: float, work_seconds: float) -> None:
        self._periods.append(period_seconds)
        self._work.append(work_seconds)

    @property
    def fps(self) -> float:
        if not self._periods:
            return 0.0
        mean = sum(self._periods) / len(self._periods)
        return 1.0 / mean if mean > 0 else 0.0

    @property
    def frame_ms(self) -> float:
        """Costo medio de producir un frame."""
        if not self._work:
            return 0.0
        return 1000.0 * sum(self._work) / len(self._work)

    @property
    def frame_ms_max(self) -> float:
        """Peor frame del tramo: el jitter es lo que se ve en la pared."""
        return 1000.0 * max(self._work) if self._work else 0.0

    def reset_peak(self) -> None:
        """Tras publicar telemetria, el pico vuelve a ser del tramo siguiente."""
        for samples in (self._periods, self._work):
            if samples:
                last = samples[-1]
                samples.clear()
                samples.append(last)


def read_temp() -> float | None:
    """Temperatura del SoC en grados. None fuera de Linux o si no esta expuesta.

    Se lee de /sys en vez de `vcgencmd`: dentro del contenedor no hay vcgencmd,
    pero /sys si esta montado.
    """
    for path in THERMAL_PATHS:
        try:
            raw = path.read_text().strip()
        except OSError:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        return value / 1000.0 if value > 1000 else value
    return None
