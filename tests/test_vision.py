"""Hilo de captura y deteccion de movimiento.

Todo con frames sinteticos: la ventaja sobre probar con una camara real es que
aca se sabe la respuesta correcta. La camara real aporta lo que esto no puede —
ruido, exposicion automatica que no obedece, enfoque — y eso esta en el #33.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from ecomap_vision.capture import PROCESS_HEIGHT, PROCESS_WIDTH, CameraThread
from ecomap_vision.motion import MotionDetector
from ecomap_vision.source import CameraInfo


class FuenteControlada:
    """Fuente de camara que entrega exactamente los frames que se le dan."""

    def __init__(self, frames: list, size=(640, 480)) -> None:
        self.frames = frames
        self.indice = 0
        self.cerrada = False
        self.info = CameraInfo(
            uri="test://", width=size[0], height=size[1], fps=15.0, backend="test"
        )

    def read(self):
        frame = self.frames[self.indice % len(self.frames)]
        self.indice += 1
        return frame

    def close(self) -> None:
        self.cerrada = True


def _frame(valor: int = 0, size=(480, 640)) -> np.ndarray:
    return np.full((*size, 3), valor, dtype=np.uint8)


def _frame_con_cuadrado(x: int, y: int, lado: int = 60) -> np.ndarray:
    frame = _frame(10)
    frame[y : y + lado, x : x + lado] = 240
    return frame


# --- deteccion -----------------------------------------------------------


def test_sin_cambios_no_hay_movimiento():
    detector = MotionDetector()
    fondo = _frame(50)

    detector.update(fondo)  # el primero solo fija el fondo
    for _ in range(5):
        motion, _ = detector.update(fondo)

    assert motion == 0.0


def test_un_objeto_que_aparece_genera_movimiento():
    detector = MotionDetector(smoothing=1.0)  # sin suavizado, para ver el crudo
    detector.update(_frame(10))

    motion, _ = detector.update(_frame_con_cuadrado(100, 100))

    assert motion > 0.0


def test_el_centroide_sigue_al_objeto():
    detector = MotionDetector(smoothing=1.0)
    detector.update(_frame(10))

    detector.update(_frame_con_cuadrado(40, 300, lado=80))
    _, izquierda_abajo = detector.position, detector.position
    detector.reset()
    detector.update(_frame(10))
    detector.update(_frame_con_cuadrado(520, 40, lado=80))
    derecha_arriba = detector.position

    assert derecha_arriba[0] > izquierda_abajo[0]
    assert derecha_arriba[1] < izquierda_abajo[1]


def test_la_banda_muerta_ignora_el_ruido():
    """La proyeccion titila y el sensor tiene ruido: sin banda muerta, eso
    cuenta como movimiento y realimenta el lazo."""
    ruidoso = MotionDetector(dead_band=0.5, smoothing=1.0)
    ruidoso.update(_frame(10))

    motion, _ = ruidoso.update(_frame_con_cuadrado(100, 100, lado=40))  # area chica

    assert motion == 0.0


def test_el_suavizado_impide_saltos():
    """Un pico instantaneo no puede llevar el valor al maximo: eso es lo que
    evita que el efecto se dispare solo."""
    detector = MotionDetector(smoothing=0.2, dead_band=0.0)
    detector.update(_frame(10))

    motion, _ = detector.update(_frame(250))  # cambio total de golpe

    assert motion < 0.5, "con suavizado 0.2 un salto no puede pasar de ~0.2"


def test_el_valor_se_satura_en_uno():
    detector = MotionDetector(smoothing=1.0, dead_band=0.0)
    detector.update(_frame(0))

    for _ in range(10):
        motion, _ = detector.update(_frame(255))

    assert motion <= 1.0


def test_reset_olvida_el_fondo():
    """Al cambiar de camara el fondo viejo no sirve."""
    detector = MotionDetector(smoothing=1.0)
    detector.update(_frame(10))
    detector.update(_frame_con_cuadrado(100, 100))

    detector.reset()

    assert detector.motion == 0.0
    assert detector.mask is None


# --- hilo de captura -----------------------------------------------------


def _esperar(condicion, timeout: float = 3.0) -> bool:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def hilo(monkeypatch):
    """CameraThread con una fuente controlada en vez de abrir un device."""
    creadas: list[FuenteControlada] = []

    def fake_open(uri, **kwargs):
        fuente = FuenteControlada([_frame(10), _frame_con_cuadrado(200, 150)])
        creadas.append(fuente)
        return fuente

    monkeypatch.setattr("ecomap_vision.capture.open_source", fake_open)
    hilos: list[CameraThread] = []

    def crear(**kwargs) -> CameraThread:
        h = CameraThread("test://", **kwargs)
        hilos.append(h)
        return h

    yield crear, creadas
    for h in hilos:
        h.stop()


def test_el_hilo_entrega_el_ultimo_frame(hilo):
    crear, _ = hilo
    h = crear(target_fps=30)
    h.start()

    assert _esperar(lambda: h.latest()[2] > 0)
    frame, chico, seq = h.latest()
    assert frame is not None and seq > 0


def test_el_frame_reducido_va_a_la_resolucion_de_proceso(hilo):
    """Sin ISP no hay stream chico gratis: se reduce por CPU, y es el costo que
    mas preocupa en dos nucleos."""
    crear, _ = hilo
    h = crear(target_fps=30)
    h.start()

    assert _esperar(lambda: h.latest()[1] is not None)
    _frame_completo, chico, _ = h.latest()
    assert chico.shape[:2] == (PROCESS_HEIGHT, PROCESS_WIDTH)


def test_el_numero_de_secuencia_avanza_para_no_resubir_la_textura(hilo):
    """El render sube la textura solo cuando hay frame nuevo: el hilo va a 15
    fps y el loop a 60."""
    crear, _ = hilo
    h = crear(target_fps=30)
    h.start()

    assert _esperar(lambda: h.latest()[2] >= 2)
    primero = h.latest()[2]
    assert _esperar(lambda: h.latest()[2] > primero)


def test_el_hilo_mide_su_propio_costo(hilo):
    crear, _ = hilo
    h = crear(target_fps=30, detector=MotionDetector())
    h.start()

    assert _esperar(lambda: h.stats.fps > 0)
    assert h.stats.read_ms >= 0.0
    assert h.stats.resize_ms >= 0.0


def test_la_deteccion_corre_en_el_hilo_de_vision(hilo):
    """Si corriera en el loop de render, su costo se sumaria al frame."""
    crear, _ = hilo
    detector = MotionDetector(smoothing=1.0, dead_band=0.0)
    h = crear(target_fps=30, detector=detector)
    h.start()

    assert _esperar(lambda: h.motion > 0.0, timeout=4.0)
    assert h.motion_ms > 0.0


def test_detener_cierra_la_fuente(hilo):
    crear, creadas = hilo
    h = crear(target_fps=30)
    h.start()
    assert _esperar(lambda: h.latest()[2] > 0)

    h.stop()

    assert creadas[0].cerrada is True


def test_la_camara_simulada_aguanta_mas_de_256_frames():
    """NumPy 2 lanza OverflowError al sumar un entero mayor que 255 a un array
    uint8. El desfase del degradado era ese entero, asi que la camara simulada
    moria en el frame 256: 17 segundos a 15 fps, mas de lo que dura un test."""
    from ecomap_vision.source import FakeSource

    fuente = FakeSource()
    for _ in range(300):
        frame = fuente.read()

    assert frame is not None
    assert frame.shape == (480, 640, 3)
    assert frame.dtype == np.uint8


# --- abrir sin bloquear al render ----------------------------------------
#
# Medido: abrir una webcam por DirectShow tarda casi 5 segundos. Antes eso
# pasaba dentro de `start()`, que llama el loop de render, asi que cambiar de
# camara congelaba la proyeccion todo ese rato.


def test_start_no_espera_a_que_la_camara_abra(monkeypatch):
    """`start()` tiene que volver enseguida aunque abrir tarde."""
    import threading
    import time as _time

    from ecomap_vision.capture import CameraThread

    abriendo = threading.Event()

    def lento(uri, **kwargs):
        abriendo.set()
        _time.sleep(0.4)
        return FuenteControlada([_frame(10)])

    monkeypatch.setattr("ecomap_vision.capture.open_source", lento)

    hilo = CameraThread("test://")
    try:
        inicio = _time.perf_counter()
        hilo.start()
        tardo = _time.perf_counter() - inicio

        assert tardo < 0.2, f"start() bloqueo {tardo * 1000:.0f} ms"
        assert abriendo.wait(2.0), "el hilo deberia estar abriendo"
        assert hilo.ready is False or hilo.opened  # todavia abriendo, o ya abrio

        assert hilo.wait_ready(3.0) is True
        assert hilo.opened and hilo.error is None
    finally:
        hilo.stop()


def test_un_fallo_al_abrir_queda_en_error_y_no_lanza(monkeypatch):
    """El render no puede caerse porque la camara no este: sigue proyectando
    sin ella y lo reporta."""
    from ecomap_vision.capture import CameraThread
    from ecomap_vision.source import CameraError

    def falla(uri, **kwargs):
        raise CameraError("no hay camara con ese indice")

    monkeypatch.setattr("ecomap_vision.capture.open_source", falla)

    hilo = CameraThread("dshow://9")
    try:
        hilo.start()  # no lanza

        assert hilo.wait_ready(3.0) is False
        assert hilo.opened is False
        assert hilo.error is not None and "indice" in hilo.error
    finally:
        hilo.stop()


def test_un_error_inesperado_al_abrir_tampoco_tumba_el_hilo(monkeypatch):
    """Un driver puede lanzar cualquier cosa; el render tiene que seguir."""
    from ecomap_vision.capture import CameraThread

    def explota(uri, **kwargs):
        raise RuntimeError("el driver se cayo")

    monkeypatch.setattr("ecomap_vision.capture.open_source", explota)

    hilo = CameraThread("dshow://0")
    try:
        hilo.start()
        assert hilo.wait_ready(3.0) is False
        assert hilo.error is not None and "inesperado" in hilo.error
    finally:
        hilo.stop()


def test_stop_antes_de_que_termine_de_abrir(monkeypatch):
    """Cambiar de camara dos veces seguidas cierra una que todavia no abrio."""
    import time as _time

    from ecomap_vision.capture import CameraThread

    def lento(uri, **kwargs):
        _time.sleep(0.3)
        return FuenteControlada([_frame(10)])

    monkeypatch.setattr("ecomap_vision.capture.open_source", lento)

    hilo = CameraThread("test://")
    hilo.start()
    hilo.stop()  # no debe colgarse ni lanzar
