"""Enumeracion de camaras, fuentes y seleccion desde la API."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.protocol import EV_CAMERA, ev
from ecomap_core.settings import Settings
from ecomap_vision.devices import FAKE_URI, enumerate_cameras
from ecomap_vision.source import CameraError, FakeSource, open_source
from ecomap_web.main import create_app

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


# --- enumeracion ---------------------------------------------------------


def _sysfs(tmp_path: Path, nodos: dict[str, tuple[str, str]]) -> Path:
    """Arma un arbol que imita /sys/class/video4linux."""
    raiz = tmp_path / "sysfs"
    for nodo, (nombre, indice) in nodos.items():
        d = raiz / nodo
        d.mkdir(parents=True)
        (d / "name").write_text(nombre + "\n", encoding="utf-8")
        (d / "index").write_text(indice + "\n", encoding="utf-8")
    return raiz


def test_enumera_solo_los_nodos_de_captura(tmp_path: Path):
    # Una webcam expone dos nodos: captura (index 0) y metadatos (index 1).
    sysfs = _sysfs(
        tmp_path,
        {
            "video0": ("USB Camera: USB Camera", "0"),
            "video1": ("USB Camera: USB Camera", "1"),
            "video2": ("Integrated Webcam", "0"),
        },
    )
    devices = enumerate_cameras(sysfs_root=sysfs, by_id_dir=tmp_path / "no-existe")

    uris = [d.uri for d in devices]
    assert uris == ["v4l2:///dev/video0", "v4l2:///dev/video2", FAKE_URI]
    assert devices[0].label == "USB Camera: USB Camera (video0)"


def test_enumera_sin_sysfs_devuelve_solo_la_simulada(tmp_path: Path):
    devices = enumerate_cameras(sysfs_root=tmp_path / "nada", by_id_dir=tmp_path / "nada")
    assert [d.uri for d in devices] == [FAKE_URI]


def test_prefiere_la_ruta_estable_cuando_existe(tmp_path: Path):
    sysfs = _sysfs(tmp_path, {"video0": ("Logitech C270", "0")})
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    nodo = tmp_path / "video0-real"
    nodo.write_text("", encoding="utf-8")
    enlace = by_id / "usb-046d_C270-video-index0"
    try:
        enlace.symlink_to(nodo)
    except OSError:
        pytest.skip("esta plataforma no permite crear symlinks sin privilegios")

    # El nodo real al que apunta el symlink debe coincidir con /dev/videoN; se
    # simula apuntando al mismo archivo que resolveria /dev/video0.
    devices = enumerate_cameras(sysfs_root=sysfs, by_id_dir=by_id)
    assert devices[0].uri.startswith("v4l2://")


def test_se_puede_excluir_la_simulada(tmp_path: Path):
    devices = enumerate_cameras(
        sysfs_root=tmp_path / "nada", by_id_dir=tmp_path / "nada", include_fake=False
    )
    assert devices == []


# --- fuentes -------------------------------------------------------------


def test_fake_source_entrega_frames_distintos():
    source = FakeSource()
    try:
        primero = source.read()
        segundo = source.read()
        assert primero is not None and segundo is not None
        assert primero.shape == (480, 640, 3)
        assert not (primero == segundo).all()  # el patron avanza
    finally:
        source.close()


def test_open_source_resuelve_el_esquema():
    source = open_source(FAKE_URI)
    try:
        assert source.info.backend == "fake"
    finally:
        source.close()


def test_open_source_rechaza_esquemas_desconocidos():
    with pytest.raises(CameraError, match="esquema"):
        open_source("rtsp://camara/stream")


def test_open_source_rechaza_v4l2_sin_device():
    with pytest.raises(CameraError, match="sin device"):
        open_source("v4l2://")


def test_open_source_falla_claro_si_el_device_no_existe():
    with pytest.raises(CameraError):
        open_source("v4l2:///dev/video-que-no-existe")


# --- API -----------------------------------------------------------------


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def cliente(tmp_path: Path):
    settings = Settings(
        db=tmp_path / "ecomap.db",
        migrations_dir=MIGRATIONS,
        bus=f"tcp://127.0.0.1:{_puerto_libre()}",  # render offline
        effects_dir=tmp_path / "effects",
        media_dir=tmp_path / "media",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client, app


async def test_devices_incluye_la_simulada(cliente):
    client, _ = cliente
    cuerpo = (await client.get("/api/camera/devices")).json()

    assert any(d["uri"] == FAKE_URI for d in cuerpo)
    assert all({"uri", "name", "label", "kind"} <= d.keys() for d in cuerpo)


async def test_seleccionar_persiste_aunque_el_render_este_caido(cliente):
    client, app = cliente

    respuesta = await client.post("/api/camera/select", json={"source": FAKE_URI})

    assert respuesta.status_code == 200
    assert respuesta.json()["state"] == "closed"
    assert "render offline" in respuesta.json()["message"]
    fila = app.state.db.execute("SELECT value FROM setting WHERE key = 'camera'").fetchone()
    assert fila["value"] == FAKE_URI


async def test_el_estado_lo_define_el_render(cliente):
    client, app = cliente
    app.state.app_state.handle_event(
        ev(
            EV_CAMERA,
            state="open",
            source="v4l2:///dev/video0",
            width=640,
            height=480,
            fps=15.0,
            backend="v4l2",
        )
    )

    cuerpo = (await client.get("/api/camera/status")).json()

    assert cuerpo["state"] == "open"
    assert cuerpo["width"] == 640
    assert cuerpo["backend"] == "v4l2"


async def test_error_de_camara_se_refleja_en_el_estado(cliente):
    client, app = cliente
    app.state.app_state.handle_event(
        ev(EV_CAMERA, state="error", source="v4l2:///dev/video9", message="no existe")
    )

    cuerpo = (await client.get("/api/camera/status")).json()

    assert cuerpo["state"] == "error"
    assert cuerpo["message"] == "no existe"


async def test_selector_se_renderiza_como_fragmento(cliente):
    client, _ = cliente

    respuesta = await client.get("/api/camera/devices", headers={"HX-Request": "true"})

    assert respuesta.headers["content-type"].startswith("text/html")
    assert "/api/camera/select" in respuesta.text
    assert "<select" in respuesta.text


async def test_fuente_vacia_es_rechazada(cliente):
    client, _ = cliente
    assert (await client.post("/api/camera/select", json={"source": ""})).status_code == 422


async def test_seleccion_entregada_queda_en_opening_no_en_el_estado_viejo(cliente):
    """Regresion: al cambiar de camara no se debe devolver el estado anterior.

    El render responde por el bus unos milisegundos despues, asi que si el
    endpoint devolviera `state.camera` sin tocarlo, la UI mostraria el error de
    la camara que se acaba de descartar.
    """
    client, app = cliente
    app.state.app_state.handle_event(
        ev(EV_CAMERA, state="error", source="v4l2:///dev/video9", message="no existe")
    )

    async def entregado(_message):
        return True

    app.state.bus.send = entregado  # simula render conectado

    cuerpo = (await client.post("/api/camera/select", json={"source": FAKE_URI})).json()

    assert cuerpo["state"] == "opening"
    assert cuerpo["source"] == FAKE_URI
    assert cuerpo["message"] is None
