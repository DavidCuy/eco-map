"""Gray code estructurado: generar patrones y decodificarlos.

La idea: el proyector muestra una secuencia de franjas binarias y la camara las
mira. Juntando los bits de todos los frames, **cada pixel de camara sabe que
pixel de proyector lo ilumino**. Con esas correspondencias sale la homografia
camara-proyector.

Por que Gray y no binario comun: entre dos valores consecutivos cambia **un
solo bit**. En el borde entre dos franjas, un pixel de camara que cae justo en
el limite se equivoca a lo sumo en un bit, y eso lo deja en una columna vecina
en vez de mandarlo al otro extremo de la pantalla.

Por que cada patron va con su inverso: evita tener que elegir un umbral de
brillo. Un pixel es 1 si se ve mas claro en el patron que en su inverso, y eso
funciona igual con una pared blanca que con una madera oscura.

Este modulo es puro numpy: no toca OpenGL ni la camara, asi que se puede
verificar contra una homografia conocida, que es mas riguroso que mirar una
pared.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# 10 bits son 1024 columnas distinguibles. Mas bits es mas resolucion pero mas
# frames que proyectar, y a partir de cierto punto el limite lo pone la camara,
# no el codigo.
DEFAULT_BITS = 10


def bits_necesarios(tamano: int) -> int:
    """Bits para distinguir `tamano` posiciones."""
    return max(1, int(np.ceil(np.log2(max(tamano, 2)))))


def binary_to_gray(valores: np.ndarray) -> np.ndarray:
    return valores ^ (valores >> 1)


def gray_to_binary(gray: np.ndarray) -> np.ndarray:
    """Inversa de `binary_to_gray`, vectorizada.

    Cada bit del resultado es el XOR acumulado de los bits mas significativos.
    """
    binario = gray.copy()
    desplazamiento = 1
    while desplazamiento < 32:
        binario = binario ^ (binario >> desplazamiento)
        desplazamiento *= 2
    return binario


def desplazamiento(tamano: int, bits: int) -> int:
    """Cuantos bits bajos del indice de pixel **no** se codifican.

    Con menos bits que los que pide el ancho hay que agrupar pixeles en
    bloques; truncar el codigo en vez de agrupar lo hace ambiguo, y un Gray
    reflejado truncado se **pliega** sobre si mismo: el decodificador devuelve
    una posicion espejada que es perfectamente consistente, asi que RANSAC la
    acepta y la homografia sale invertida. Costo de agrupar: la posicion se
    conoce con precision de un bloque, que para una homografia sobra.
    """
    return max(0, bits_necesarios(tamano) - bits)


def pattern(
    size: tuple[int, int], bit: int, axis: str, inverse: bool = False, shift: int = 0
) -> np.ndarray:
    """Un patron de franjas, como imagen en escala de grises.

    `axis` es `"x"` para franjas verticales (codifican la columna) o `"y"` para
    horizontales (codifican la fila). `shift` agrupa pixeles en bloques de
    `2**shift` cuando no hay bits para codificar cada pixel.
    """
    ancho, alto = size
    if axis == "x":
        indices = np.arange(ancho, dtype=np.int64) >> shift
        fila = ((binary_to_gray(indices) >> bit) & 1).astype(np.uint8)
        imagen = np.tile(fila, (alto, 1))
    else:
        indices = np.arange(alto, dtype=np.int64) >> shift
        columna = ((binary_to_gray(indices) >> bit) & 1).astype(np.uint8)
        imagen = np.tile(columna.reshape(-1, 1), (1, ancho))
    if inverse:
        imagen = 1 - imagen
    return imagen * 255


@dataclass
class Sequence:
    """La secuencia completa de patrones a proyectar, en orden."""

    size: tuple[int, int]
    bits_x: int
    bits_y: int
    # Bloques de 2**shift pixeles cuando los bits no alcanzan para uno a uno.
    shift_x: int = 0
    shift_y: int = 0

    @classmethod
    def for_size(cls, size: tuple[int, int], max_bits: int = DEFAULT_BITS) -> Sequence:
        return cls(
            size=size,
            bits_x=min(bits_necesarios(size[0]), max_bits),
            bits_y=min(bits_necesarios(size[1]), max_bits),
            shift_x=desplazamiento(size[0], max_bits),
            shift_y=desplazamiento(size[1], max_bits),
        )

    @property
    def block(self) -> tuple[int, int]:
        """Tamano del bloque en pixeles de proyector, en x y en y."""
        return (1 << self.shift_x, 1 << self.shift_y)

    def __len__(self) -> int:
        # blanco y negro de referencia, mas cada bit con su inverso
        return 2 + 2 * (self.bits_x + self.bits_y)

    def frame(self, index: int) -> np.ndarray:
        """El patron numero `index` de la secuencia."""
        ancho, alto = self.size
        if index == 0:
            return np.full((alto, ancho), 255, dtype=np.uint8)
        if index == 1:
            return np.zeros((alto, ancho), dtype=np.uint8)

        resto = index - 2
        if resto < 2 * self.bits_x:
            return pattern(
                self.size, resto // 2, "x", inverse=bool(resto % 2), shift=self.shift_x
            )
        resto -= 2 * self.bits_x
        return pattern(self.size, resto // 2, "y", inverse=bool(resto % 2), shift=self.shift_y)

    def describe(self, index: int) -> str:
        if index == 0:
            return "blanco"
        if index == 1:
            return "negro"
        resto = index - 2
        if resto < 2 * self.bits_x:
            return f"x bit {resto // 2}{' inverso' if resto % 2 else ''}"
        resto -= 2 * self.bits_x
        return f"y bit {resto // 2}{' inverso' if resto % 2 else ''}"


@dataclass
class Decoded:
    proj_x: np.ndarray   # columna de proyector por pixel de camara
    proj_y: np.ndarray   # fila de proyector
    mask: np.ndarray     # donde el codigo es confiable
    coverage: float      # fraccion de la imagen con codigo valido


def decode(frames: list[np.ndarray], sequence: Sequence, min_contrast: int = 12) -> Decoded:
    """Decodifica los frames capturados.

    `frames` tiene que venir en el mismo orden que la secuencia. Devuelve, por
    cada pixel de camara, que pixel de proyector lo ilumino.

    `min_contrast` descarta los pixeles donde la diferencia entre blanco y
    negro es muy chica: zonas que el proyector no alcanza, o que estan tan
    quemadas por luz ambiente que el patron no se distingue. Sin esto, el ruido
    de esas zonas entra como correspondencias falsas y arruina el ajuste.
    """
    if len(frames) != len(sequence):
        raise ValueError(f"se esperaban {len(sequence)} frames, llegaron {len(frames)}")

    grises = [_a_gris(f).astype(np.int16) for f in frames]
    blanco, negro = grises[0], grises[1]
    mask = (blanco - negro) >= min_contrast

    bloque_x, bloque_y = sequence.block
    # Del indice de bloque al pixel: el centro del bloque es la mejor
    # estimacion que dan los patrones proyectados.
    proj_x = (
        _decodificar_eje(grises[2 : 2 + 2 * sequence.bits_x], sequence.bits_x) * bloque_x
        + (bloque_x - 1) // 2
    )
    inicio_y = 2 + 2 * sequence.bits_x
    proj_y = (
        _decodificar_eje(grises[inicio_y : inicio_y + 2 * sequence.bits_y], sequence.bits_y)
        * bloque_y
        + (bloque_y - 1) // 2
    )

    # Un codigo fuera del tamano del proyector es un error de decodificacion,
    # no una posicion: se descarta.
    mask &= proj_x < sequence.size[0]
    mask &= proj_y < sequence.size[1]

    return Decoded(
        proj_x=proj_x,
        proj_y=proj_y,
        mask=mask,
        coverage=float(mask.sum()) / float(mask.size),
    )


def _a_gris(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    return frame.mean(axis=2)


def _decodificar_eje(grises: list[np.ndarray], bits: int) -> np.ndarray:
    """Arma el codigo Gray bit a bit y lo pasa a binario."""
    gray = np.zeros(grises[0].shape, dtype=np.int64)
    for bit in range(bits):
        normal = grises[2 * bit]
        inverso = grises[2 * bit + 1]
        # Sin umbral absoluto: se compara el patron contra su inverso.
        valor = (normal > inverso).astype(np.int64)
        gray |= valor << bit
    return gray_to_binary(gray)


def correspondences(
    decoded: Decoded, step: int = 8
) -> tuple[np.ndarray, np.ndarray]:
    """Pares (punto de camara, punto de proyector) muestreados en grilla.

    Se muestrea en vez de usar todos los pixeles: con una camara de 640x480 son
    300 mil puntos, y RANSAC no necesita tantos para encontrar la homografia.
    """
    alto, ancho = decoded.mask.shape
    ys, xs = np.mgrid[0:alto:step, 0:ancho:step]
    validos = decoded.mask[ys, xs]

    cam = np.stack([xs[validos], ys[validos]], axis=1).astype(np.float32)
    proj = np.stack(
        [decoded.proj_x[ys, xs][validos], decoded.proj_y[ys, xs][validos]], axis=1
    ).astype(np.float32)
    return cam, proj


def estimate_homography(
    cam: np.ndarray, proj: np.ndarray, reproj_threshold: float = 3.0
) -> tuple[Any | None, float, int]:
    """Homografia camara -> proyector, con RANSAC.

    Devuelve (H, rms en pixeles de proyector, cantidad de inliers). RANSAC
    porque siempre hay correspondencias malas: bordes de franja, reflejos, y
    zonas donde el codigo se decodifico a medias.
    """
    try:
        import cv2
    except ImportError:  # pragma: no cover - depende del entorno
        return None, float("inf"), 0

    if len(cam) < 4:
        return None, float("inf"), 0

    H, inliers = cv2.findHomography(cam, proj, cv2.RANSAC, reproj_threshold)
    if H is None:
        return None, float("inf"), 0

    inliers = inliers.ravel().astype(bool)
    if not inliers.any():
        return None, float("inf"), 0

    proyectados = cv2.perspectiveTransform(cam[inliers].reshape(-1, 1, 2), H).reshape(-1, 2)
    errores = np.linalg.norm(proyectados - proj[inliers], axis=1)
    rms = float(np.sqrt((errores**2).mean()))
    return H, rms, int(inliers.sum())
