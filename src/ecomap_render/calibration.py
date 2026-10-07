"""Auto-calibracion con Gray code, del lado del render.

El render es quien puede hacer esto: tiene el proyector y la camara. Proyecta
la secuencia, espera a que la camara se asiente, captura, y al final decodifica
y estima la homografia.

Dos tiempos que no coinciden, y es lo que hace esto delicado:

- El render dibuja a 30 o 60 fps.
- La camara captura a 15 fps, con su propio buffer y su latencia USB.

Por eso no se cuentan frames de render para esperar: se espera a que el
**numero de secuencia de la camara avance**, que es la unica senal de que
llego un frame nuevo de verdad. Cuantos hace falta esperar depende del
hardware, y es uno de los numeros que hay que medir cuando haya camara.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import moderngl
import numpy as np

from ecomap_vision.graycode import Sequence, correspondences, decode, estimate_homography

log = logging.getLogger(__name__)

# Frames de camara a descartar tras cambiar el patron. Con 15 fps son ~130 ms.
DEFAULT_SETTLE = 2
# Si un patron no se captura en este tiempo, algo pasa con la camara.
TIMEOUT_POR_PATRON = 5.0


def _uniforme(program, nombre: str, valor) -> None:
    miembro = program.get(nombre, None)
    if miembro is not None:
        miembro.value = valor


@dataclass
class CalibrationResult:
    ok: bool
    homography: list[list[float]] | None = None
    rms: float | None = None
    inliers: int = 0
    coverage: float = 0.0
    message: str = ""
    camera_size: tuple[int, int] | None = None
    proj_size: tuple[int, int] | None = None


@dataclass
class CalibrationRunner:
    """Maquina de estados de la secuencia. Un paso por frame de render."""

    size: tuple[int, int]
    settle: int = DEFAULT_SETTLE
    max_bits: int = 8

    sequence: Sequence = field(init=False)
    index: int = 0
    frames: list[np.ndarray] = field(default_factory=list)
    active: bool = True
    result: CalibrationResult | None = None

    _texture: Any | None = None
    _esperando_desde: int | None = None
    _inicio_patron: float = 0.0

    def __post_init__(self) -> None:
        self.sequence = Sequence.for_size(self.size, max_bits=self.max_bits)
        self._inicio_patron = time.perf_counter()
        log.info(
            "calibracion: %d patrones (%d bits en x, %d en y)",
            len(self.sequence),
            self.sequence.bits_x,
            self.sequence.bits_y,
        )

    @property
    def progress(self) -> float:
        return self.index / max(len(self.sequence), 1)

    @property
    def stage(self) -> str:
        return self.sequence.describe(min(self.index, len(self.sequence) - 1))

    # --- dibujo ---

    def draw(self, ctx: moderngl.Context, target: moderngl.Framebuffer, program, vao) -> None:
        """Proyecta el patron actual a pantalla completa.

        Va por textura y no por shader a proposito: el patron sale del mismo
        codigo numpy que despues lo decodifica, asi que no hay forma de que el
        proyector muestre una cosa y el decodificador asuma otra.
        """
        patron = self.sequence.frame(self.index)
        alto, ancho = patron.shape
        if self._texture is None or self._texture.size != (ancho, alto):
            if self._texture is not None:
                self._texture.release()
            # Tres canales aunque el patron sea gris: con uno solo el shader
            # samplea (r, 0, 0) y el proyector muestra franjas rojas, que
            # ademas llegan a la camara con un tercio del contraste.
            self._texture = ctx.texture((ancho, alto), components=3)
            self._texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
        # Sin interpolacion: suavizar los bordes de las franjas es exactamente
        # lo que arruina la decodificacion.
        rgb = np.repeat(np.flipud(patron)[:, :, None], 3, axis=2)
        self._texture.write(np.ascontiguousarray(rgb).tobytes())

        target.use()
        ctx.clear(0.0, 0.0, 0.0)
        self._texture.use(location=0)
        # `u_opacity` va explicito: el shader de warp lo multiplica, y sin
        # asignarlo arranca en 0 y la proyeccion sale negra.
        _uniforme(program, "u_texture", 0)
        _uniforme(program, "u_opacity", 1.0)
        # El quad son dos triangulos: con `vertices=3` se dibujaba la mitad de
        # la pantalla y la otra quedaba sin patron.
        vao.render(moderngl.TRIANGLES)

    # --- avance ---

    def tick(self, camera_seq: int, camera_frame: np.ndarray | None) -> None:
        """Se llama una vez por frame de render, despues de presentar."""
        if not self.active:
            return

        if self._esperando_desde is None:
            # Recien se mostro este patron: se anota en que frame de camara
            # estabamos para saber cuando hay uno nuevo de verdad.
            self._esperando_desde = camera_seq
            self._inicio_patron = time.perf_counter()
            return

        if time.perf_counter() - self._inicio_patron > TIMEOUT_POR_PATRON:
            self.finish(error="la camara dejo de entregar frames a mitad de la secuencia")
            return

        if camera_frame is None or camera_seq < self._esperando_desde + self.settle:
            return

        self.frames.append(camera_frame.copy())
        self.index += 1
        self._esperando_desde = None

        if self.index >= len(self.sequence):
            self.finish()

    def cancel(self) -> None:
        self.finish(error="cancelada")

    def finish(self, error: str | None = None) -> None:
        self.active = False
        if error:
            self.result = CalibrationResult(ok=False, message=error)
            log.warning("calibracion: %s", error)
        else:
            # Resolver **antes** de liberar: los frames capturados son
            # justamente lo que hay que decodificar.
            self.result = self._resolver()
        self._liberar()

    def _resolver(self) -> CalibrationResult:
        try:
            decoded = decode(self.frames, self.sequence)
        except ValueError as exc:
            return CalibrationResult(ok=False, message=str(exc))

        cam, proj = correspondences(decoded, step=6)
        H, rms, inliers = estimate_homography(cam, proj)
        alto, ancho = self.frames[0].shape[:2]

        if H is None:
            return CalibrationResult(
                ok=False,
                coverage=decoded.coverage,
                message=(
                    "no se encontro una homografia. Suele ser que la camara no ve "
                    "el area proyectada, o que la exposicion automatica altero los "
                    "patrones entre capturas."
                ),
                camera_size=(ancho, alto),
                proj_size=self.size,
            )

        return CalibrationResult(
            ok=True,
            homography=[[float(v) for v in fila] for fila in H],
            rms=rms,
            inliers=inliers,
            coverage=decoded.coverage,
            camera_size=(ancho, alto),
            proj_size=self.size,
            message=f"{inliers} correspondencias, error {rms:.2f} px",
        )

    def _liberar(self) -> None:
        if self._texture is not None:
            self._texture.release()
            self._texture = None
        self.frames.clear()
