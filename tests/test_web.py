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
        effects_dir=tmp_path / "effects",
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
    assert cuerpo["pattern"] == "off"


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
        "/api/system/testpattern",
        json={"pattern": "grid"},
        headers={"HX-Request": "true"},
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/html")
    assert "hx-post" in respuesta.text


async def test_patron_invalido_es_rechazado(cliente):
    client, _ = cliente
    respuesta = await client.post("/api/system/testpattern", json={"pattern": "arcoiris"})
    assert respuesta.status_code == 422


async def test_telemetria_del_bus_actualiza_el_estado(cliente):
    client, app = cliente
    app.state.app_state.handle_event(ev(EV_TELE, fps=59.4, frame_ms=16.8, temp=54.1))

    cuerpo = (await client.get("/api/system/status")).json()

    assert cuerpo["fps"] == 59.4
    assert cuerpo["temp"] == 54.1
    # El socket sigue caido, asi que el render no cuenta como vivo.
    assert cuerpo["render_up"] is False
