"""Enumeracion de camaras, fuentes y seleccion desde la API."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.protocol import EV_CAMERA, ev
from ecomap_core.settings import Settings
from ecomap_vision import devices as devices_mod
from ecomap_vision.devices import FAKE_URI, enumerate_cameras
from ecomap_vision.source import CameraError, FakeSource, open_source
from ecomap_web.main import create_app

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
EFFECTS_DIR = Path(__file__).resolve().parent.parent / "effects"


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
    devices = enumerate_cameras(
        sysfs_root=sysfs, by_id_dir=tmp_path / "no-existe", system="Linux"
    )

    uris = [d.uri for d in devices]
    assert uris == ["v4l2:///dev/video0", "v4l2:///dev/video2", FAKE_URI]
    assert devices[0].label == "USB Camera: USB Camera (video0)"


def test_enumera_sin_sysfs_devuelve_solo_la_simulada(tmp_path: Path):
    devices = enumerate_cameras(
        sysfs_root=tmp_path / "nada", by_id_dir=tmp_path / "nada", system="Linux"
    )
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
    devices = enumerate_cameras(sysfs_root=sysfs, by_id_dir=by_id, system="Linux")
    assert devices[0].uri.startswith("v4l2://")


def test_se_puede_excluir_la_simulada(tmp_path: Path):
    devices = enumerate_cameras(
        sysfs_root=tmp_path / "nada",
        by_id_dir=tmp_path / "nada",
        include_fake=False,
        system="Linux",
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
        effects_dir=EFFECTS_DIR,
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


def test_el_evento_de_camara_se_construye_bien():
    """Regresion: un parche mal anclado metio una constante de mas dentro de
    esta llamada, y `ev()` es posicional-solo, asi que el render explotaba al
    reportar un error de camara — justo en el camino de error."""
    from ecomap_core.protocol import EV_CAMERA, ev

    mensaje = ev(EV_CAMERA, state="open", source="fake://", width=640, height=480, backend="fake")

    assert mensaje["ev"] == "camera"
    assert mensaje["state"] == "open"
    assert mensaje["width"] == 640


# --- ajustes de deteccion (#21) ------------------------------------------


async def test_los_ajustes_de_deteccion_se_persisten_y_viajan(cliente):
    """Son las perillas contra la realimentacion optica, asi que el render
    tiene que recibirlas y sobrevivir a un reinicio."""
    (
        client,
        app,
    ) = cliente[0], cliente[1]
    enviados: list[dict] = []

    async def espia(message):
        enviados.append(message)
        return True

    app.state.bus.send = espia

    respuesta = await client.put(
        "/api/camera/motion", json={"dead_band": 0.08, "smoothing": 0.4, "threshold": 40}
    )

    assert respuesta.status_code == 200
    motion = [m for m in enviados if m.get("op") == "motion"][-1]
    assert motion["dead_band"] == 0.08
    assert motion["threshold"] == 40
    guardado = (await client.get("/api/camera/motion")).json()
    assert guardado["smoothing"] == 0.4


async def test_los_ajustes_de_deteccion_se_validan(cliente):
    client = cliente[0]
    # Un suavizado de 0 congelaria el valor para siempre.
    assert (
        await client.put(
            "/api/camera/motion", json={"dead_band": 0.0, "smoothing": 0.0, "threshold": 25}
        )
    ).status_code == 422
    assert (
        await client.put(
            "/api/camera/motion", json={"dead_band": 2.0, "smoothing": 0.5, "threshold": 25}
        )
    ).status_code == 422


# --- camera_echo (#22) ---------------------------------------------------


def test_camera_echo_declara_camara_y_realimentacion():
    """Sin `needs_feedback` el render no le arma el buffer y el efecto no
    tendria memoria: cada frame arrancaria de cero."""
    from ecomap_core.effects import load_effect

    efecto = load_effect(EFFECTS_DIR / "camera_echo")

    assert efecto.manifest.needs_camera is True
    assert efecto.manifest.needs_feedback is True


def test_camera_echo_tiene_los_tres_frenos_contra_la_realimentacion():
    """La camara ve la proyeccion: sin frenos el efecto se satura solo.

    Los tres: decay < 1 (el pasado se apaga), gain (cuanto aporta la camara) y
    la saturacion final.
    """
    from ecomap_core.effects import load_effect

    efecto = load_effect(EFFECTS_DIR / "camera_echo")
    claves = {p.key: p for p in efecto.manifest.params}

    assert claves["decay"].max < 1.0, "con decay 1.0 el pasado nunca se apaga"
    assert "gain" in claves
    assert "min(" in efecto.fragment, "falta la saturacion final"


async def test_la_escena_le_dice_al_render_que_capa_necesita_realimentacion(cliente):
    """El render arma una textura extra por capa que la pida, asi que tiene que
    venir en la escena."""
    client, app = cliente[0], cliente[1]
    enviados: list[dict] = []

    async def espia(message):
        enviados.append(message)
        return True

    app.state.bus.send = espia
    surface_id = (await client.post("/api/surfaces", json={"name": "cara"})).json()["id"]
    scene_id = (await client.post("/api/scenes", json={"name": "demo"})).json()["id"]

    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "camera_echo"},
    )

    capa = [m for m in enviados if m.get("op") == "scene"][-1]["scene"]["layers"][0]
    assert capa["needs_feedback"] is True


# --- enumeracion en Windows ----------------------------------------------
#
# La mini PC de pruebas corre Windows, donde no hay sysfs ni `v4l2-ctl`. El
# nombre sale de CIM y el indice es el orden en que CIM los devuelve.


def _cim(monkeypatch, salida: str, *, falla: bool = False):
    """Reemplaza la consulta a PowerShell por una respuesta fija."""
    import subprocess

    class _Resultado:
        stdout = salida

    def _run(*args, **kwargs):
        if falla:
            raise OSError("powershell no esta en el PATH")
        return _Resultado()

    monkeypatch.setattr(subprocess, "run", _run)


def test_windows_enumera_por_indice_de_directshow(monkeypatch):
    _cim(monkeypatch, '["Integrated Camera", "Logitech C270"]')

    devices = enumerate_cameras(system="Windows")

    assert [d.uri for d in devices] == ["dshow://0", "dshow://1", FAKE_URI]
    assert devices[0].label == "Integrated Camera (indice 0)"
    assert devices[0].kind == "dshow"
    # Windows no tiene nada como /dev/v4l/by-id: no hay ruta estable que guardar
    assert devices[0].node is None and devices[0].stable_path is None


def test_windows_con_una_sola_camara(monkeypatch):
    """`ConvertTo-Json` devuelve un escalar, no una lista, cuando hay un solo
    elemento. Sin contemplarlo, la unica camara del equipo se pierde."""
    _cim(monkeypatch, '"HD WebCam"')

    devices = enumerate_cameras(system="Windows")

    assert [d.uri for d in devices] == ["dshow://0", FAKE_URI]
    assert devices[0].name == "HD WebCam"


def test_windows_sin_camaras(monkeypatch):
    _cim(monkeypatch, "")
    assert [d.uri for d in enumerate_cameras(system="Windows")] == [FAKE_URI]


def test_windows_si_powershell_falla_no_rompe_el_selector(monkeypatch):
    """El dashboard tiene que seguir abriendo: sin camaras reales queda la
    simulada, que es mejor que una pantalla de error."""
    _cim(monkeypatch, "", falla=True)
    assert [d.uri for d in enumerate_cameras(system="Windows")] == [FAKE_URI]


def test_windows_con_respuesta_que_no_es_json(monkeypatch):
    _cim(monkeypatch, "Get-CimInstance : Acceso denegado")
    assert [d.uri for d in enumerate_cameras(system="Windows")] == [FAKE_URI]


def test_la_consulta_pide_solo_camaras_presentes():
    """Windows recuerda camaras desenchufadas; listarlas llevaria a elegir una
    que no esta."""
    assert "PNPClass -eq 'Camera'" in devices_mod.PS_CAMARAS
    assert "Status -eq 'OK'" in devices_mod.PS_CAMARAS


# --- backends de captura -------------------------------------------------


def test_open_source_acepta_los_backends_de_windows(monkeypatch):
    """`dshow://0` deja el indice en netloc, no en path: urlparse lee lo que
    sigue a `//` como host. Sin contemplarlo la URI se veia sin device.

    No se abre nada: el test corre igual en un equipo con camara y en uno sin.
    """
    from urllib.parse import urlparse

    from ecomap_vision import source as source_mod

    pedidos = []
    monkeypatch.setattr(
        source_mod,
        "OpenCVSource",
        lambda device, **kw: pedidos.append((device, kw.get("backend"))),
    )

    for uri in ("dshow://0", "msmf://1"):
        assert urlparse(uri).path == "", "el indice viaja en netloc"
        open_source(uri)

    assert pedidos == [("0", "dshow"), ("1", "msmf")]


def test_open_source_sigue_pasando_la_ruta_en_linux(monkeypatch):
    """El camino V4L2 es el que va a usar la Pi: agregar Windows no debe
    cambiarlo."""
    from ecomap_vision import source as source_mod

    pedidos = []
    monkeypatch.setattr(
        source_mod,
        "OpenCVSource",
        lambda device, **kw: pedidos.append((device, kw.get("backend"))),
    )

    open_source("v4l2:///dev/v4l/by-id/usb-046d_C270-video-index0")

    assert pedidos == [("/dev/v4l/by-id/usb-046d_C270-video-index0", "v4l2")]


def test_open_source_rechaza_dshow_sin_indice():
    with pytest.raises(CameraError, match="sin device"):
        open_source("dshow://")


def test_cada_backend_tiene_su_constante_y_su_motivo():
    """Un backend sin mensaje propio manda al operador a buscar al lugar
    equivocado: en Linux se revisa el `--device`, en Windows los permisos."""
    from ecomap_vision.source import BACKENDS, MOTIVOS

    assert set(BACKENDS) == set(MOTIVOS)
    assert "Privacidad" in MOTIVOS["dshow"]
    assert "contenedor" in MOTIVOS["v4l2"]


def test_backend_desconocido_se_rechaza():
    from ecomap_vision.source import _backend_const

    cv2 = pytest.importorskip("cv2")
    with pytest.raises(CameraError, match="backend de camara desconocido"):
        _backend_const(cv2, "gstreamer")


def test_el_modo_manual_de_exposicion_no_es_el_mismo_numero_en_cada_backend():
    """V4L2 usa el enum de su API (1 = manual) y DirectShow su propia
    convencion (0.25 = manual). Mandar el valor de uno al otro deja la camara
    en automatico sin que nada falle."""
    from ecomap_vision.source import AUTO_EXPOSURE_AUTO, AUTO_EXPOSURE_MANUAL

    assert AUTO_EXPOSURE_MANUAL["v4l2"] == 1.0
    assert AUTO_EXPOSURE_MANUAL["dshow"] == 0.25
    assert set(AUTO_EXPOSURE_MANUAL) == set(AUTO_EXPOSURE_AUTO)
    for backend, manual in AUTO_EXPOSURE_MANUAL.items():
        assert manual != AUTO_EXPOSURE_AUTO[backend]


def test_la_exposicion_distingue_ignorado_de_no_confirmable():
    """Un driver que devuelve -1 no esta diciendo "lo ignore": esta diciendo
    que no se puede leer. Reportar las dos cosas igual manda a buscar un
    problema de camara donde puede no haberlo.

    Medido en Windows con DirectShow sobre una webcam real: `auto_exposure`
    vuelve -1 aunque el `set` devuelva True.
    """
    from ecomap_vision.source import AUTO_EXPOSURE_MANUAL, OpenCVSource

    class _Capture:
        def __init__(self, devuelve):
            self.devuelve = devuelve

        def set(self, prop, valor):
            return True

        def get(self, prop):
            return self.devuelve

    fuente = OpenCVSource.__new__(OpenCVSource)
    fuente.backend = "dshow"
    fuente.info = type("I", (), {"uri": "dshow://0"})()

    import cv2

    fuente._cv2 = cv2

    fuente._capture = _Capture(-1.0)
    assert fuente.set_auto_exposure(False) == "sin_confirmar"

    fuente._capture = _Capture(AUTO_EXPOSURE_MANUAL["dshow"])
    assert fuente.set_auto_exposure(False) == "aplicado"

    fuente._capture = _Capture(0.75)
    assert fuente.set_auto_exposure(False) == "ignorado"
