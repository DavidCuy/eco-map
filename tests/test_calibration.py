"""Auto-calibracion: la maquina de estados y la API.

La parte matematica se verifica en `test_graycode.py` contra una homografia
conocida. Aca se prueba el runner, que es lo que coordina dos relojes que no
coinciden — el render a 30 o 60 fps y la camara a 15 — y la API.
"""

from __future__ import annotations

import socket
from pathlib import Path

import cv2
import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.settings import Settings
from ecomap_render.calibration import CalibrationRunner
from ecomap_web.main import create_app

RAIZ = Path(__file__).resolve().parent.parent
MIGRATIONS = RAIZ / "migrations"
EFFECTS_DIR = RAIZ / "effects"

PROYECTOR = (320, 240)
CAMARA = (400, 300)


def _homografia() -> np.ndarray:
    ancho, alto = PROYECTOR
    origen = np.float32([[0, 0], [ancho, 0], [ancho, alto], [0, alto]])
    destino = np.float32([[60, 40], [350, 70], [330, 250], [40, 230]])
    return cv2.getPerspectiveTransform(origen, destino)


def _vista_camara(patron: np.ndarray, H: np.ndarray) -> np.ndarray:
    vista = cv2.warpPerspective(patron, H, CAMARA).astype(np.float32) * 0.85 + 10
    return np.clip(vista, 0, 255).astype(np.uint8)


def _correr(runner: CalibrationRunner, settle: int, H: np.ndarray) -> None:
    """Simula el ida y vuelta render-camara hasta que la secuencia termina.

    Cada vuelta del while es un frame de render; el numero de secuencia de la
    camara avanza mas lento, igual que en la realidad.
    """
    cam_seq = 0
    vueltas = 0
    while runner.active and vueltas < 5000:
        vueltas += 1
        patron = runner.sequence.frame(runner.index)
        frame = _vista_camara(patron, H)
        runner.tick(cam_seq, frame)
        cam_seq += 1


# --- maquina de estados ---------------------------------------------------


def test_la_secuencia_termina_y_recupera_la_homografia():
    H = _homografia()
    runner = CalibrationRunner(size=PROYECTOR, settle=2, max_bits=8)

    _correr(runner, settle=2, H=H)

    assert runner.active is False
    assert runner.result is not None and runner.result.ok, runner.result.message
    assert runner.result.rms is not None and runner.result.rms < 3.0
    assert runner.result.inliers > 100
    assert runner.result.camera_size == CAMARA
    assert runner.result.proj_size == PROYECTOR


def test_espera_a_que_la_camara_entregue_frames_nuevos():
    """El render va mas rapido que la camara: si no esperara, capturaria el
    patron anterior y decodificaria cualquier cosa."""
    runner = CalibrationRunner(size=PROYECTOR, settle=3, max_bits=8)
    frame = _vista_camara(runner.sequence.frame(0), _homografia())

    runner.tick(0, frame)  # primera vuelta: anota donde esta la camara
    for _ in range(10):
        runner.tick(0, frame)  # la camara no avanza

    assert runner.index == 0, "no deberia avanzar sin frames nuevos"

    runner.tick(3, frame)
    assert runner.index == 1


def test_el_progreso_avanza_y_describe_la_etapa():
    runner = CalibrationRunner(size=PROYECTOR, settle=0, max_bits=8)
    assert runner.progress == 0.0
    assert runner.stage == "blanco"

    frame = _vista_camara(runner.sequence.frame(0), _homografia())
    runner.tick(0, frame)
    runner.tick(1, frame)

    assert runner.progress > 0.0
    assert runner.stage == "negro"


def test_sin_frames_de_camara_corta_por_timeout(monkeypatch):
    """Si la camara deja de entregar a mitad de la secuencia, hay que decirlo,
    no quedarse esperando para siempre."""
    import ecomap_render.calibration as modulo

    runner = CalibrationRunner(size=PROYECTOR, settle=1, max_bits=8)
    runner.tick(0, None)
    monkeypatch.setattr(modulo, "TIMEOUT_POR_PATRON", -1.0)
    runner._inicio_patron = 0.0

    runner.tick(0, None)

    assert runner.active is False
    assert runner.result is not None and not runner.result.ok
    assert "dejo de entregar" in runner.result.message


def test_cancelar_deja_un_resultado_explicito():
    runner = CalibrationRunner(size=PROYECTOR, max_bits=8)
    runner.cancel()
    assert runner.active is False
    assert runner.result is not None and runner.result.message == "cancelada"


def test_una_camara_que_no_ve_la_proyeccion_falla_con_motivo():
    """El caso mas comun en la vida real: la camara apunta a otro lado, o la
    exposicion automatica aplano los patrones."""
    runner = CalibrationRunner(size=PROYECTOR, settle=0, max_bits=8)
    gris = np.full((CAMARA[1], CAMARA[0]), 128, np.uint8)

    cam_seq = 0
    while runner.active and cam_seq < 500:
        runner.tick(cam_seq, gris)
        cam_seq += 1

    assert runner.result is not None and not runner.result.ok
    assert "exposicion automatica" in runner.result.message


# --- dibujo del patron ----------------------------------------------------
#
# Sin GL: con dobles alcanza para fijar el contrato del paso de warp, y es
# justo donde se escondieron dos bugs que solo se veian proyectando —
# `u_opacity` sin asignar (arranca en 0 y todo sale negro) y medio quad.


class _Uniforme:
    def __init__(self) -> None:
        self.value = None


class _Programa:
    def __init__(self, nombres: tuple[str, ...]) -> None:
        self.uniformes = {n: _Uniforme() for n in nombres}

    def get(self, nombre, default=None):  # noqa: ANN001 - firma de moderngl
        return self.uniformes.get(nombre, default)


class _Textura:
    def __init__(self, size, components) -> None:  # noqa: ANN001
        self.size = size
        self.components = components
        self.filter = None
        self.escrito: bytes | None = None
        self.liberada = False

    def write(self, data: bytes) -> None:
        self.escrito = data

    def use(self, location: int = 0) -> None:
        self.location = location

    def release(self) -> None:
        self.liberada = True


class _Contexto:
    def __init__(self) -> None:
        self.texturas: list[_Textura] = []
        self.limpiado = False

    def texture(self, size, components=3, **kwargs):  # noqa: ANN001
        tex = _Textura(size, components)
        self.texturas.append(tex)
        return tex

    def clear(self, *args) -> None:  # noqa: ANN002
        self.limpiado = True


class _Vao:
    def __init__(self) -> None:
        self.llamadas: list[dict] = []

    def render(self, modo=None, **kwargs):  # noqa: ANN001
        self.llamadas.append(kwargs)


class _Target:
    def use(self) -> None:
        self.usado = True


def _dibujar(runner: CalibrationRunner, nombres=("u_texture", "u_opacity")):
    ctx, programa, vao, target = _Contexto(), _Programa(nombres), _Vao(), _Target()
    runner.draw(ctx, target, programa, vao)
    return ctx, programa, vao


def test_el_patron_se_proyecta_opaco():
    """El shader de warp multiplica por `u_opacity`. Sin asignarlo arranca en 0
    y el proyector muestra negro: la secuencia corre entera y falla al final
    diciendo que la camara no ve el area."""
    runner = CalibrationRunner(size=PROYECTOR, max_bits=8)

    _ctx, programa, _vao = _dibujar(runner)

    assert programa.uniformes["u_opacity"].value == 1.0
    assert programa.uniformes["u_texture"].value == 0


def test_se_dibuja_el_quad_completo():
    """El quad son dos triangulos, seis vertices. Pedir tres dibujaba media
    pantalla y la otra mitad quedaba sin patron."""
    runner = CalibrationRunner(size=PROYECTOR, max_bits=8)

    _ctx, _programa, vao = _dibujar(runner)

    assert len(vao.llamadas) == 1
    assert vao.llamadas[0].get("vertices") in (None, 6)


def test_el_patron_va_en_tres_canales():
    """Con una textura de un canal el shader samplea (r, 0, 0): el proyector
    muestra franjas rojas y a la camara llegan con un tercio del contraste."""
    runner = CalibrationRunner(size=PROYECTOR, max_bits=8)

    ctx, _programa, _vao = _dibujar(runner)

    assert ctx.texturas[-1].components == 3
    ancho, alto = PROYECTOR
    assert len(ctx.texturas[-1].escrito) == ancho * alto * 3


def test_un_programa_sin_esos_uniformes_no_rompe():
    """El paso de warp puede cambiar de uniformes; la calibracion no deberia
    caerse por eso."""
    runner = CalibrationRunner(size=PROYECTOR, max_bits=8)
    _dibujar(runner, nombres=())


# --- API ------------------------------------------------------------------


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def cliente(tmp_path: Path):
    settings = Settings(
        db=tmp_path / "ecomap.db",
        migrations_dir=MIGRATIONS,
        bus=f"tcp://127.0.0.1:{_puerto_libre()}",
        effects_dir=EFFECTS_DIR,
        media_dir=tmp_path / "media",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            enviados: list[dict] = []

            async def espia(message):
                enviados.append(message)
                return True

            app.state.bus.send = espia
            yield client, app, enviados


async def test_calibrar_sin_camara_se_rechaza(cliente):
    """Correr la secuencia entera para fallar al final seria perder 30 s."""
    client, _, _ = cliente

    respuesta = await client.post("/api/calibration/auto", json={})

    assert respuesta.status_code == 422
    assert "camara" in respuesta.text


async def test_calibrar_devuelve_202_y_avisa_al_render(cliente):
    """Es asincrona: son decenas de patrones y un POST que espera daria
    timeout justo cuando va bien."""
    client, app, enviados = cliente
    app.state.app_state.camera.state = "open"

    respuesta = await client.post("/api/calibration/auto", json={"settle": 3})

    assert respuesta.status_code == 202
    assert respuesta.json()["running"] is True
    orden = [m for m in enviados if m.get("op") == "calibrate"][-1]
    assert orden["settle"] == 3


async def test_no_se_pueden_correr_dos_a_la_vez(cliente):
    client, app, _ = cliente
    app.state.app_state.camera.state = "open"
    await client.post("/api/calibration/auto", json={})

    respuesta = await client.post("/api/calibration/auto", json={})

    assert respuesta.status_code == 422
    assert "en curso" in respuesta.text


async def test_se_puede_cancelar_a_mitad(cliente):
    """Son decenas de segundos con el proyector mostrando franjas: si el
    operador se dio cuenta de que la camara apunta mal, cortar tiene que ser un
    boton, no esperar a que termine."""
    client, app, enviados = cliente
    app.state.app_state.camera.state = "open"
    await client.post("/api/calibration/auto", json={})

    respuesta = await client.request("DELETE", "/api/calibration/auto")

    assert respuesta.status_code == 200
    assert [m for m in enviados if m.get("op") == "calibrate"][-1]["cancel"] is True


async def test_cancelar_sin_calibracion_en_curso_se_rechaza(cliente):
    client, _, _ = cliente

    respuesta = await client.request("DELETE", "/api/calibration/auto")

    assert respuesta.status_code == 422
    assert "en curso" in respuesta.text


async def test_el_progreso_llega_por_el_bus(cliente):
    client, app, _ = cliente
    app.state.app_state.handle_event(
        {"ev": "calib", "progress": 0.45, "stage": "x bit 3", "done": False}
    )

    cuerpo = (await client.get("/api/calibration/auto")).json()

    assert cuerpo["running"] is True
    assert cuerpo["progress"] == 0.45
    assert cuerpo["stage"] == "x bit 3"


async def test_una_calibracion_buena_se_guarda_sola(cliente):
    """Repetirla cuesta tiempo y paciencia: no se puede perder porque se
    reinicio el web."""
    client, app, _ = cliente
    H = [[1.0, 0.0, 5.0], [0.0, 1.0, 7.0], [0.0, 0.0, 1.0]]

    app.state.app_state.handle_event(
        {
            "ev": "calib",
            "done": True,
            "ok": True,
            "msg": "320 correspondencias",
            "homography": H,
            "rms": 1.4,
            "inliers": 320,
            "coverage": 0.42,
            "camera_size": [640, 480],
            "proj_size": [1920, 1080],
        }
    )

    guardada = (await client.get("/api/calibration/last")).json()
    assert guardada["homography"] == H
    assert guardada["rms"] == 1.4
    assert guardada["camera_size"] == [640, 480]


async def test_una_calibracion_fallida_no_se_guarda(cliente):
    client, app, _ = cliente

    app.state.app_state.handle_event(
        {"ev": "calib", "done": True, "ok": False, "msg": "no se encontro homografia"}
    )

    assert (await client.get("/api/calibration/last")).json() is None
    estado = (await client.get("/api/calibration/auto")).json()
    assert estado["ok"] is False
    assert "no se encontro" in estado["message"]
