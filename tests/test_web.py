"""Pruebas del proceso web sin render conectado: es el caso normal al arrancar."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.protocol import EV_TELE, ev
from ecomap_core.settings import Settings
from ecomap_web.main import create_app

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
EFFECTS_DIR = Path(__file__).resolve().parent.parent / "effects"


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def cliente(tmp_path: Path):
    settings = Settings(
        db=tmp_path / "ecomap.db",
        migrations_dir=MIGRATIONS,
        bus=f"tcp://127.0.0.1:{_puerto_libre()}",  # nadie escucha: render offline
        effects_dir=EFFECTS_DIR,
        media_dir=tmp_path / "media",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client, app


async def test_status_reporta_render_offline(cliente):
    client, _ = cliente
    respuesta = await client.get("/api/system/status")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["render_up"] is False
    assert cuerpo["blackout"] is False


async def test_dashboard_se_renderiza(cliente):
    client, _ = cliente
    respuesta = await client.get("/")

    assert respuesta.status_code == 200
    assert "Eco-Map" in respuesta.text
    assert "/static/vendor/htmx.min.js" in respuesta.text  # sin CDN (ADR-002)


async def test_blackout_se_persiste_aunque_el_render_este_caido(cliente):
    client, app = cliente

    respuesta = await client.post("/api/system/blackout", json={"on": True})

    assert respuesta.status_code == 200
    assert respuesta.json()["blackout"] is True
    fila = app.state.db.execute("SELECT value FROM setting WHERE key = 'blackout'").fetchone()
    assert fila["value"] == "1"
    # Y queda anotado que el render no lo recibio.
    eventos = app.state.db.execute("SELECT message FROM event_log").fetchall()
    assert any("render no estaba conectado" in row["message"] for row in eventos)


async def test_hx_request_devuelve_fragmento_html(cliente):
    client, _ = cliente

    respuesta = await client.post(
        "/api/system/blackout",
        json={"on": True},
        headers={"HX-Request": "true"},
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/html")
    assert "hx-post" in respuesta.text


async def test_telemetria_del_bus_actualiza_el_estado(cliente):
    client, app = cliente
    app.state.app_state.handle_event(ev(EV_TELE, fps=59.4, frame_ms=16.8, temp=54.1))

    cuerpo = (await client.get("/api/system/status")).json()

    assert cuerpo["fps"] == 59.4
    assert cuerpo["temp"] == 54.1
    # El socket sigue caido, asi que el render no cuenta como vivo.
    assert cuerpo["render_up"] is False


async def test_el_dashboard_es_el_workspace_de_calibracion(cliente):
    """El dashboard dejo de ser una pila de tarjetas: ahora el canvas manda."""
    client, _ = cliente
    await client.post("/api/surfaces", json={"name": "frontal"})

    html = (await client.get("/")).text

    assert 'workspace(JSON.parse(' in html
    assert "<canvas" in html
    assert "/static/calibrate.js" in html
    # La configuracion viaja como JSON embebido: la malla puede tener cientos
    # de puntos y no entra en atributos sueltos.
    assert '"surfaces"' in html and '"frontal"' in html
    assert '"previewUrl"' in html and '"output"' in html


async def test_el_dashboard_conserva_la_telemetria(cliente):
    """Lo tecnico no se pierde con el rediseno: es lo que dice si el equipo
    esta sufriendo, y ninguna app comercial lo muestra."""
    client, _ = cliente

    html = (await client.get("/")).text

    for campo in ("fps", "frame_ms", "render_up", "temp"):
        assert campo in html


async def test_el_dashboard_funciona_sin_superficies(cliente):
    client, _ = cliente
    html = (await client.get("/")).text
    assert '"surfaces": []' in html


async def test_un_nombre_de_superficie_no_puede_inyectar_html(cliente):
    """El JSON del workspace va dentro de un <script>: si un nombre pudiera
    cerrar la etiqueta, seria inyeccion de codigo."""
    client, _ = cliente
    await client.post("/api/surfaces", json={"name": "</script><img src=x>"})

    html = (await client.get("/")).text

    assert "</script><img src=x>" not in html
    assert "\u003c/script" in html
