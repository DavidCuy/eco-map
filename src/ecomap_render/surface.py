"""Geometria de una superficie en GPU.

Cada superficie es una malla texturizada con el FBO del efecto. El pipeline es
el de Warping-y-Homografia:

    efecto -> FBO -> malla deformada -> framebuffer de salida

El efecto nunca conoce el warp: dibuja en UV 0..1 y la malla se encarga del
resto. Por eso cambiar de efecto no obliga a recalibrar.
"""

from __future__ import annotations

import logging
from typing import Any

import moderngl
import numpy as np

from ecomap_core.geometry import Mesh, perspective_weights, triangulate

log = logging.getLogger(__name__)


def build_vertices(points: Mesh, cols: int, rows: int) -> np.ndarray:
    """Arma el buffer de vertices: posicion en clip space + UV con peso.

    Los puntos llegan normalizados 0..1 con origen arriba a la izquierda. GL usa
    -1..1 con origen abajo, asi que la Y se invierte aca y no en el shader.

    La V de la textura tambien se invierte, y por el mismo motivo: el FBO del
    efecto tiene origen abajo. Sin eso, la misma superficie se ve espejada
    segun si se dibuja a pantalla completa o a traves de la malla, y las marcas
    de esquina del patron de calibracion dejan de significar lo que dicen.

    El peso `q` sale de la celda a la que pertenece cada vertice. Un vertice
    compartido entre celdas toma el promedio de las que lo tocan: con mallas
    finas la diferencia es despreciable, y es lo que permite usar un solo buffer
    en vez de duplicar vertices por celda.
    """
    ancho = cols + 1
    acumulado = np.zeros(len(points), dtype=np.float64)
    conteo = np.zeros(len(points), dtype=np.int32)

    for y in range(rows):
        for x in range(cols):
            tl = y * ancho + x
            tr = tl + 1
            bl = tl + ancho
            br = bl + 1
            celda = [points[tl], points[tr], points[br], points[bl]]
            for indice, peso in zip((tl, tr, br, bl), perspective_weights(celda), strict=True):
                acumulado[indice] += peso
                conteo[indice] += 1

    pesos = np.where(conteo > 0, acumulado / np.maximum(conteo, 1), 1.0)

    vertices = np.zeros((len(points), 5), dtype="f4")
    for i, (px, py) in enumerate(points):
        u = (i % ancho) / cols
        v = 1.0 - (i // ancho) / rows  # fila 0 es arriba; la textura, al reves
        q = float(pesos[i])
        vertices[i] = (
            px * 2.0 - 1.0,  # x en clip space
            1.0 - py * 2.0,  # y invertida: 0 arriba -> +1 arriba
            u * q,
            v * q,
            q,
        )
    return vertices


class SurfaceMesh:
    """Malla de una superficie, lista para dibujar."""

    def __init__(
        self,
        ctx: moderngl.Context,
        program: moderngl.Program,
        surface: dict[str, Any],
    ) -> None:
        self.ctx = ctx
        self.id = int(surface["id"])
        self.cols = int(surface["cols"])
        self.rows = int(surface["rows"])
        self.opacity = float(surface.get("opacity", 1.0))
        puntos = [(float(x), float(y)) for x, y in surface["points"]]

        vertices = build_vertices(puntos, self.cols, self.rows)
        indices = np.array(triangulate(self.cols, self.rows), dtype="i4")

        self._vbo = ctx.buffer(vertices.tobytes())
        self._ibo = ctx.buffer(indices.tobytes())
        self.vao = ctx.vertex_array(
            program,
            [(self._vbo, "2f 3f", "in_position", "in_uvq")],
            index_buffer=self._ibo,
            index_element_size=4,
        )
        self.triangles = len(indices) // 3

    def render(self) -> None:
        self.vao.render(moderngl.TRIANGLES)

    def release(self) -> None:
        self.vao.release()
        self._vbo.release()
        self._ibo.release()
