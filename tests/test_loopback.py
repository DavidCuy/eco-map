"""El banco virtual proyector-camara.

Lo que verifica es que la camara simulada se comporte **como una camara**: si
entrega otra cosa (un canal en vez de tres, un tamano que no es el pedido), el
banco deja de servir para probar el resto del sistema y los bugs aparecen solo
con hardware.
"""

from __future__ import annotations

import numpy as np
import pytest

from ecomap_vision import loopback
from ecomap_vision.source import CameraError, open_source

PROYECTOR = (640, 360)


@pytest.fixture
def proyectado():
    """Registra un proveedor de frames, como hace el render."""
    patron = np.zeros((PROYECTOR[1], PROYECTOR[0]), dtype=np.uint8)
    patron[:, PROYECTOR[0] // 2 :] = 255  # mitad blanca, para notar un espejo

    loopback.set_frame_provider(lambda: (patron, PROYECTOR))
    yield patron
    loopback.set_frame_provider(None)


def test_sin_proveedor_falla_con_un_motivo_util():
    """`loopback://` desde el web no puede funcionar: el frame proyectado solo
    existe en el render."""
    loopback.set_frame_provider(None)
    with pytest.raises(CameraError, match="dentro del render"):
        open_source("loopback://")


def test_entrega_bgr_de_tres_canales(proyectado):
    """Todo lo que consume frames —textura de camara, deteccion de movimiento,
    reduccion a la resolucion de proceso— cuenta con BGR de OpenCV. Una fuente
    que entregue un canal tumba el render al subir la textura."""
    fuente = open_source("loopback://?width=320&height=240")

    frame = fuente.read()

    assert frame is not None
    assert frame.shape == (240, 320, 3)
    assert frame.dtype == np.uint8
    # Gris replicado: los tres canales iguales
    assert np.array_equal(frame[:, :, 0], frame[:, :, 2])


def test_la_homografia_del_banco_no_cambia_entre_frames(proyectado):
    """Mover la camara a mitad de una secuencia la invalida, igual que en la
    realidad: el banco tiene que ser igual de estricto."""
    fuente = open_source("loopback://")
    fuente.read()
    primera = fuente.truth.copy()

    fuente.read()

    assert np.array_equal(fuente.truth, primera)


def test_deforma_de_verdad(proyectado):
    """Si devolviera el frame tal cual, probar la calibracion contra el banco no
    probaria nada."""
    fuente = open_source("loopback://?width=640&height=480&noise=0&blur=1")

    frame = fuente.read()

    assert fuente.truth is not None
    # Las esquinas quedan fuera del area proyectada: la vista esta en
    # perspectiva, no centrada ni a escala.
    assert frame[0, 0].max() < 40
    assert frame[:, :, 0].max() > 150, "el area proyectada deberia verse"


def test_los_parametros_de_la_uri_se_respetan(proyectado):
    fuente = open_source("loopback://?width=160&height=120&noise=0&blur=7&gain=0.5&ambient=30")

    assert fuente.size == (160, 120)
    assert fuente.blur == 7
    assert fuente.gain == 0.5
    assert fuente.read().shape == (120, 160, 3)


def test_el_desenfoque_par_se_vuelve_impar(proyectado):
    """`GaussianBlur` exige kernel impar: redondear es mas util que fallar."""
    fuente = open_source("loopback://?blur=4")
    assert fuente.blur == 5
    assert fuente.read() is not None
