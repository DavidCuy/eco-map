"""Geometria de las superficies: mallas, subdivision y correccion de perspectiva.

Vive en `core` porque la usan los dos procesos: el web valida e interpola al
editar, y el render triangula y calcula los pesos de perspectiva al dibujar.

**Convenciones** (ADR-015):

- Toda superficie es una malla de `cols` x `rows` celdas. Un quad es la malla
  1x1. No hay dos modelos.
- Los puntos se guardan **normalizados 0..1**, con origen arriba a la izquierda
  (como el canvas del navegador), en **orden fila-mayor**: primero la fila de
  arriba de izquierda a derecha, despues la siguiente. Para una malla 1x1 eso
  da TL, TR, BL, BR.
- Una malla de `cols` x `rows` celdas tiene `(cols+1) * (rows+1)` puntos.
"""

from __future__ import annotations

type Point = tuple[float, float]
type Mesh = list[Point]

MAX_CELLS = 32  # tope por lado: 32x32 celdas son 1089 puntos, de sobra


class GeometryError(ValueError):
    """La malla no cumple las invariantes."""


def expected_points(cols: int, rows: int) -> int:
    return (cols + 1) * (rows + 1)


def default_mesh(cols: int = 1, rows: int = 1) -> Mesh:
    """Malla que cubre toda la salida, repartida de forma regular."""
    validate_subdivision(cols, rows)
    return [(x / cols, y / rows) for y in range(rows + 1) for x in range(cols + 1)]


def validate_subdivision(cols: int, rows: int) -> None:
    if cols < 1 or rows < 1:
        raise GeometryError("la malla necesita al menos una celda por lado")
    if cols > MAX_CELLS or rows > MAX_CELLS:
        raise GeometryError(f"maximo {MAX_CELLS} celdas por lado")


def validate_mesh(points: Mesh, cols: int, rows: int) -> None:
    """Verifica cantidad y rango. No verifica que la malla no se auto-intersecte:
    cruzar los puntos es visualmente raro pero legitimo, y prohibirlo estorbaria
    al calibrar superficies con formas poco amables."""
    validate_subdivision(cols, rows)
    esperados = expected_points(cols, rows)
    if len(points) != esperados:
        raise GeometryError(
            f"la malla {cols}x{rows} necesita {esperados} puntos, llegaron {len(points)}"
        )
    for i, punto in enumerate(points):
        if len(punto) != 2:
            raise GeometryError(f"el punto {i} no es un par (x, y)")
        x, y = punto
        if not (-1.0 <= x <= 2.0) or not (-1.0 <= y <= 2.0):
            # Se permite salirse un poco del 0..1: a veces hace falta tirar una
            # esquina fuera de pantalla. Mas alla de eso es un error de unidades.
            raise GeometryError(f"el punto {i} = ({x}, {y}) esta fuera de rango")


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """Spline de Catmull-Rom entre p1 y p2, con p0 y p3 como tangentes."""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def _sample_row(fila: list[Point], u: float) -> Point:
    """Evalua una fila de puntos de control en u ∈ [0, 1]."""
    n = len(fila)
    if n == 1:
        return fila[0]
    segmento = u * (n - 1)
    i = min(int(segmento), n - 2)
    t = segmento - i
    # Indices clampeados: con pocos puntos de control la spline degenera en algo
    # cercano a la interpolacion lineal, que es justo lo que se quiere al
    # subdividir un quad plano.
    i0 = max(i - 1, 0)
    i1 = i
    i2 = i + 1
    i3 = min(i + 2, n - 1)
    return (
        _catmull_rom(fila[i0][0], fila[i1][0], fila[i2][0], fila[i3][0], t),
        _catmull_rom(fila[i0][1], fila[i1][1], fila[i2][1], fila[i3][1], t),
    )


def resample(points: Mesh, cols: int, rows: int, new_cols: int, new_rows: int) -> Mesh:
    """Cambia la subdivision conservando la forma.

    Al subir la resolucion, los puntos nuevos salen de interpolar con
    Catmull-Rom la malla existente, asi que la superficie no se deforma: se
    refina. Al bajarla se pierden los ajustes finos — por eso la UI debe avisar.
    """
    validate_mesh(points, cols, rows)
    validate_subdivision(new_cols, new_rows)

    filas = [points[y * (cols + 1) : (y + 1) * (cols + 1)] for y in range(rows + 1)]

    # Primero se densifica en x, despues en y sobre el resultado.
    filas_u = [[_sample_row(fila, i / new_cols) for i in range(new_cols + 1)] for fila in filas]

    salida: Mesh = []
    for j in range(new_rows + 1):
        v = j / new_rows
        for i in range(new_cols + 1):
            columna = [filas_u[y][i] for y in range(rows + 1)]
            salida.append(_sample_row(columna, v))
    return salida


def triangulate(cols: int, rows: int) -> list[int]:
    """Indices de los triangulos de la malla, dos por celda."""
    validate_subdivision(cols, rows)
    ancho = cols + 1
    indices: list[int] = []
    for y in range(rows):
        for x in range(cols):
            tl = y * ancho + x
            tr = tl + 1
            bl = tl + ancho
            br = bl + 1
            indices.extend([tl, tr, br, tl, br, bl])
    return indices


def perspective_weights(quad: list[Point]) -> list[float]:
    """Pesos `q` para que la textura siga la perspectiva dentro de una celda.

    Interpolar UV linealmente sobre los dos triangulos de un quad deformado
    produce el quiebre diagonal clasico. El truco conocido: en el punto donde se
    cruzan las diagonales, cada vertice recibe un peso proporcional a cuanto le
    toca de su diagonal; se pasa `uv * q` y `q`, y el fragment divide.

    `quad` llega en orden TL, TR, BR, BL. Si las diagonales no se cruzan (celda
    degenerada) devuelve pesos neutros: peor interpolacion, pero nunca un
    division por cero en el shader.
    """
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad

    # Diagonales: TL->BR y TR->BL
    ax, ay = x2 - x0, y2 - y0
    bx, by = x3 - x1, y3 - y1
    den = ax * by - ay * bx
    if abs(den) < 1e-12:
        return [1.0, 1.0, 1.0, 1.0]

    s = ((x1 - x0) * by - (y1 - y0) * bx) / den  # posicion del cruce en TL->BR
    t = ((x1 - x0) * ay - (y1 - y0) * ax) / den  # posicion del cruce en TR->BL
    if not (0.0 < s < 1.0) or not (0.0 < t < 1.0):
        return [1.0, 1.0, 1.0, 1.0]

    return [
        1.0 / (1.0 - s),  # TL
        1.0 / (1.0 - t),  # TR
        1.0 / s,  # BR
        1.0 / t,  # BL
    ]
