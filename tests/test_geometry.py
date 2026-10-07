"""Geometria de mallas: orden de puntos, subdivision, triangulacion y perspectiva."""

from __future__ import annotations

import pytest

from ecomap_core.geometry import (
    GeometryError,
    default_mesh,
    expected_points,
    perspective_weights,
    resample,
    triangulate,
    validate_mesh,
)


def test_malla_por_defecto_es_fila_mayor():
    # 1x1 celda = 4 puntos, fila de arriba primero: TL, TR, BL, BR.
    assert default_mesh(1, 1) == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]


def test_cantidad_de_puntos_segun_subdivision():
    assert expected_points(1, 1) == 4
    assert expected_points(3, 3) == 16
    assert len(default_mesh(2, 3)) == expected_points(2, 3)


def test_validacion_rechaza_cantidad_incorrecta():
    with pytest.raises(GeometryError, match="necesita 4 puntos"):
        validate_mesh([(0, 0), (1, 0), (1, 1)], 1, 1)


def test_validacion_rechaza_coordenadas_disparatadas():
    with pytest.raises(GeometryError, match="fuera de rango"):
        validate_mesh([(0, 0), (1, 0), (0, 1), (640, 480)], 1, 1)


def test_validacion_acepta_salirse_un_poco_de_pantalla():
    # Tirar una esquina fuera del 0..1 es legitimo al calibrar.
    validate_mesh([(-0.2, -0.1), (1.1, 0.0), (0.0, 1.0), (1.0, 1.2)], 1, 1)


def test_subdividir_conserva_las_esquinas():
    original = [(0.1, 0.1), (0.9, 0.2), (0.0, 0.8), (1.0, 0.9)]
    denso = resample(original, 1, 1, 4, 4)

    assert len(denso) == expected_points(4, 4)
    assert denso[0] == pytest.approx(original[0])  # TL
    assert denso[4] == pytest.approx(original[1])  # TR
    assert denso[20] == pytest.approx(original[2])  # BL
    assert denso[24] == pytest.approx(original[3])  # BR


def test_subdividir_un_quad_plano_da_puntos_equiespaciados():
    denso = resample(default_mesh(1, 1), 1, 1, 2, 2)
    assert _plano(denso) == pytest.approx(_plano(default_mesh(2, 2)))


def _plano(puntos):
    """pytest.approx no compara bien listas de tuplas; se aplanan."""
    return [c for punto in puntos for c in punto]


def test_subdividir_ida_y_vuelta_no_deforma_las_esquinas():
    original = [(0.2, 0.1), (0.8, 0.15), (0.1, 0.9), (0.95, 0.85)]
    vuelta = resample(resample(original, 1, 1, 5, 5), 5, 5, 1, 1)
    assert _plano(vuelta) == pytest.approx(_plano(original), abs=1e-9)


def test_triangulacion_dos_triangulos_por_celda():
    indices = triangulate(2, 3)
    assert len(indices) == 2 * 3 * 6  # celdas * 2 triangulos * 3 vertices
    assert max(indices) == expected_points(2, 3) - 1


def test_triangulacion_de_la_primera_celda():
    # Malla 1x1: TL=0 TR=1 BL=2 BR=3 -> (TL,TR,BR) y (TL,BR,BL)
    assert triangulate(1, 1) == [0, 1, 3, 0, 3, 2]


def test_pesos_de_perspectiva_uniformes_en_un_paralelogramo():
    # Las diagonales se cortan al medio: todos los pesos iguales, y un factor
    # comun se cancela al dividir en el shader.
    pesos = perspective_weights([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert pesos == pytest.approx([2.0, 2.0, 2.0, 2.0])


def test_pesos_de_perspectiva_distintos_en_un_trapecio():
    # Lado de arriba mas corto que el de abajo: los vertices de abajo pesan mas.
    tl, tr, br, bl = perspective_weights([(0.2, 0.0), (0.8, 0.0), (1.0, 1.0), (0.0, 1.0)])
    assert tl == pytest.approx(tr)
    assert br == pytest.approx(bl)
    assert br > tl


def test_pesos_neutros_si_la_celda_degenera():
    # Cuatro puntos colineales: no hay cruce de diagonales utilizable.
    assert perspective_weights([(0, 0), (1, 0), (2, 0), (3, 0)]) == [1.0, 1.0, 1.0, 1.0]


def test_subdivision_fuera_de_rango():
    with pytest.raises(GeometryError, match="al menos una celda"):
        default_mesh(0, 1)
    with pytest.raises(GeometryError, match="maximo"):
        default_mesh(1, 999)


def test_vertices_invierten_y_y_v_para_calzar_con_gl():
    """El FBO del efecto tiene origen abajo y la malla arriba.

    Si no se invierten las dos cosas, la misma superficie se ve espejada segun
    si se dibuja a pantalla completa o a traves de la malla, y las marcas de
    esquina del patron de calibracion dejan de significar lo que dicen.
    """
    from ecomap_render.surface import build_vertices

    vertices = build_vertices(default_mesh(1, 1), 1, 1)
    tl, tr, bl, br = vertices  # orden fila-mayor

    # Posicion: el punto (0,0) de arriba a la izquierda va a (-1, +1) en clip space.
    assert (tl[0], tl[1]) == pytest.approx((-1.0, 1.0))
    assert (br[0], br[1]) == pytest.approx((1.0, -1.0))

    # UV: se guardan como u*q, v*q, q. La fila de arriba muestrea v = 1.
    assert tl[2] / tl[4] == pytest.approx(0.0)
    assert tl[3] / tl[4] == pytest.approx(1.0)
    assert br[2] / br[4] == pytest.approx(1.0)
    assert br[3] / br[4] == pytest.approx(0.0)
