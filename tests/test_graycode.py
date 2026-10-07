"""Gray code verificado contra una homografia conocida.

La ventaja sobre probar con hardware: aca se sabe la respuesta correcta. Se
elige una `H`, se simula la camara deformando lo proyectado con esa `H`, y se
comprueba que el algoritmo la recupera. Con una pared solo se puede decir "se
ve bien".

Lo que esto **no** cubre, y por eso esta en el #33: exposicion automatica que
no obedece, tiempo de asentamiento entre proyectar y capturar, y el ruido real
de un sensor barato.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from ecomap_vision.graycode import (
    Sequence,
    binary_to_gray,
    bits_necesarios,
    correspondences,
    decode,
    desplazamiento,
    estimate_homography,
    gray_to_binary,
    pattern,
)

PROYECTOR = (320, 240)
CAMARA = (400, 300)


# --- codificacion --------------------------------------------------------


def test_gray_cambia_un_solo_bit_entre_consecutivos():
    """Es la razon de usar Gray: un pixel en el borde de una franja se
    equivoca en un bit, no en medio codigo."""
    valores = binary_to_gray(np.arange(256))
    diferencias = valores[:-1] ^ valores[1:]
    # Un solo bit encendido = potencia de dos
    assert all(int(d) & (int(d) - 1) == 0 for d in diferencias)


def test_gray_y_su_inversa_son_ida_y_vuelta():
    original = np.arange(1024)
    assert np.array_equal(gray_to_binary(binary_to_gray(original)), original)


def test_bits_necesarios():
    assert bits_necesarios(1024) == 10
    assert bits_necesarios(1920) == 11
    assert bits_necesarios(1) == 1


def test_la_secuencia_arranca_con_blanco_y_negro():
    """Son la referencia: sin ellas habria que elegir un umbral de brillo
    absoluto, que no funciona igual en una pared blanca que en madera."""
    seq = Sequence.for_size(PROYECTOR)

    assert seq.frame(0).min() == 255
    assert seq.frame(1).max() == 0
    assert seq.describe(0) == "blanco"


def test_el_largo_de_la_secuencia():
    seq = Sequence.for_size((1024, 512))
    # 10 bits en x, 9 en y, cada uno con su inverso, mas blanco y negro
    assert seq.bits_x == 10 and seq.bits_y == 9
    assert len(seq) == 2 + 2 * (10 + 9) == 40


def test_los_patrones_son_franjas_en_el_eje_correcto():
    vertical = pattern((64, 32), bit=0, axis="x")
    horizontal = pattern((64, 32), bit=0, axis="y")

    # Franjas verticales: todas las filas iguales
    assert np.array_equal(vertical[0], vertical[-1])
    # Franjas horizontales: todas las columnas iguales
    assert np.array_equal(horizontal[:, 0], horizontal[:, -1])


def test_el_inverso_es_el_complemento():
    normal = pattern((64, 32), bit=2, axis="x")
    inverso = pattern((64, 32), bit=2, axis="x", inverse=True)
    assert np.array_equal(normal, 255 - inverso)


# --- banco virtual proyector-camara --------------------------------------


def _simular_camara(
    patron: np.ndarray,
    H_proj_a_cam: np.ndarray,
    size_cam: tuple[int, int],
    ruido: float = 0.0,
    desenfoque: int = 0,
    ganancia: float = 0.85,
    ambiente: float = 12.0,
) -> np.ndarray:
    """Lo que veria una camara mirando ese patron proyectado.

    Deforma con la homografia conocida y agrega lo que degrada en la vida real:
    luz ambiente que levanta los negros, ganancia menor a 1 que baja los
    blancos, desenfoque y ruido.
    """
    vista = cv2.warpPerspective(patron, H_proj_a_cam, size_cam)
    vista = vista.astype(np.float32) * ganancia + ambiente
    if desenfoque:
        vista = cv2.GaussianBlur(vista, (desenfoque, desenfoque), 0)
    if ruido:
        vista = vista + np.random.default_rng(0).normal(0, ruido, vista.shape)
    return np.clip(vista, 0, 255).astype(np.uint8)


def _homografia_de_prueba() -> np.ndarray:
    """Proyector -> camara: una vista en perspectiva, como la de una camara al
    costado del proyector."""
    ancho, alto = PROYECTOR
    origen = np.float32([[0, 0], [ancho, 0], [ancho, alto], [0, alto]])
    destino = np.float32([[60, 40], [350, 70], [330, 250], [40, 230]])
    return cv2.getPerspectiveTransform(origen, destino)


def _correr_secuencia(**degradacion) -> tuple[np.ndarray, Sequence]:
    seq = Sequence.for_size(PROYECTOR, max_bits=8)
    H_proj_cam = _homografia_de_prueba()
    frames = [
        _simular_camara(seq.frame(i), H_proj_cam, CAMARA, **degradacion)
        for i in range(len(seq))
    ]
    return frames, seq


# --- decodificacion ------------------------------------------------------


def test_recupera_la_homografia_conocida():
    """La prueba de fondo: se sabe la respuesta y se comprueba que la encuentra."""
    frames, seq = _correr_secuencia()

    decoded = decode(frames, seq)
    cam, proj = correspondences(decoded, step=4)
    H, rms, inliers = estimate_homography(cam, proj)

    assert H is not None
    assert inliers > 100
    assert rms < 3.0, f"error de reproyeccion {rms:.2f} px"

    # Y se compara contra la verdad: la H recuperada es camara -> proyector,
    # asi que componerla con la del banco tiene que dar la identidad.
    H_cam_proj_verdadera = np.linalg.inv(_homografia_de_prueba())
    esquinas = np.float32([[0, 0], [CAMARA[0], 0], [CAMARA[0], CAMARA[1]], [0, CAMARA[1]]])
    esperado = cv2.perspectiveTransform(esquinas.reshape(-1, 1, 2), H_cam_proj_verdadera)
    obtenido = cv2.perspectiveTransform(esquinas.reshape(-1, 1, 2), H)
    error = np.abs(esperado - obtenido).max()
    assert error < 6.0, f"las esquinas difieren hasta {error:.1f} px de la verdad"


def test_aguanta_ruido_y_desenfoque():
    """Una camara barata en penumbra: ruido alto y foco flojo."""
    frames, seq = _correr_secuencia(ruido=8.0, desenfoque=5)

    decoded = decode(frames, seq)
    cam, proj = correspondences(decoded, step=4)
    H, rms, inliers = estimate_homography(cam, proj)

    assert H is not None and inliers > 50
    assert rms < 6.0, f"con ruido el error fue {rms:.2f} px"


def test_la_cobertura_marca_donde_llega_el_proyector():
    """Fuera del area iluminada no hay codigo: eso es lo que distingue el
    objeto del fondo de la sala."""
    frames, seq = _correr_secuencia()

    decoded = decode(frames, seq)

    assert 0.2 < decoded.coverage < 0.9, "deberia cubrir solo la zona proyectada"
    assert not decoded.mask[0, 0], "la esquina de la camara esta fuera del area"


def test_el_contraste_minimo_descarta_lo_que_el_proyector_no_alcanza():
    """Con poco contraste el patron no se distingue del fondo, y esos pixeles
    entrarian como correspondencias falsas."""
    frames, seq = _correr_secuencia(ganancia=0.02, ambiente=120)

    decoded = decode(frames, seq)

    assert decoded.coverage < 0.05


def test_rechaza_una_cantidad_de_frames_incorrecta():
    seq = Sequence.for_size(PROYECTOR, max_bits=8)
    with pytest.raises(ValueError, match="se esperaban"):
        decode([np.zeros((10, 10), np.uint8)] * 3, seq)


def test_sin_correspondencias_no_inventa_homografia():
    vacio = np.zeros((0, 2), dtype=np.float32)
    H, rms, inliers = estimate_homography(vacio, vacio)
    assert H is None and inliers == 0


# --- menos bits que pixeles -----------------------------------------------


def test_desplazamiento_agrupa_cuando_faltan_bits():
    # 640 columnas piden 10 bits; con 8 se agrupan de a 4 pixeles
    assert desplazamiento(640, 8) == 2
    assert desplazamiento(640, 10) == 0
    assert desplazamiento(256, 8) == 0


def test_con_menos_bits_que_el_ancho_la_posicion_no_se_pliega():
    """El bug que encontro el banco virtual.

    Truncar el codigo Gray en vez de agrupar pixeles **pliega** la posicion:
    un Gray reflejado al que le faltan los bits altos devuelve una columna
    espejada, y como el espejo es consistente para toda una franja de la
    imagen, RANSAC lo acepta como si fuera la respuesta. La homografia sale
    invertida con un error de reproyeccion bajisimo, que es la peor forma de
    estar mal.
    """
    proyector = (640, 360)
    camara = (640, 480)
    ancho, alto = proyector
    H_proj_cam = cv2.getPerspectiveTransform(
        np.float32([[0, 0], [ancho, 0], [ancho, alto], [0, alto]]),
        np.float32([[115, 67], [563, 105], [531, 412], [76, 374]]),
    )

    seq = Sequence.for_size(proyector, max_bits=8)
    assert seq.block == (4, 2), "640 con 8 bits son bloques de 4 px"

    frames = [_simular_camara(seq.frame(i), H_proj_cam, camara) for i in range(len(seq))]
    decoded = decode(frames, seq)
    cam, proj = correspondences(decoded, step=6)
    H, rms, inliers = estimate_homography(cam, proj)

    assert H is not None and inliers > 100
    assert rms < 4.0

    # Un rms bajo no alcanza: hay que comparar contra la verdad, que es
    # justamente lo que el pliegue pasaba por alto.
    esquinas = np.float32(
        [[0, 0], [camara[0], 0], [camara[0], camara[1]], [0, camara[1]]]
    ).reshape(-1, 1, 2)
    esperado = cv2.perspectiveTransform(esquinas, np.linalg.inv(H_proj_cam))
    obtenido = cv2.perspectiveTransform(esquinas, H)
    error = float(np.abs(esperado - obtenido).max())
    assert error < 12.0, f"las esquinas difieren {error:.0f} px: la posicion se plego"
