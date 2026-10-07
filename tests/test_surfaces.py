"""API de superficies: CRUD, puntos, subdivision y envio de la escena al render."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.geometry import default_mesh
from ecomap_core.settings import Settings
from ecomap_web.main import create_app

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def cliente(tmp_path: Path):
    """Web con el render caido, y un espia de lo que se manda al bus."""
    settings = Settings(
        db=tmp_path / "ecomap.db",
        migrations_dir=MIGRATIONS,
        bus=f"tcp://127.0.0.1:{_puerto_libre()}",
        effects_dir=tmp_path / "effects",
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


async def test_crear_superficie_arranca_como_quad_a_pantalla_completa(cliente):
    client, _, _ = cliente

    respuesta = await client.post("/api/surfaces", json={"name": "cara frontal"})

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["name"] == "cara frontal"
    assert (cuerpo["mesh_cols"], cuerpo["mesh_rows"]) == (1, 1)
    assert cuerpo["kind"] == "quad"  # derivado de la subdivision, no elegido
    assert [tuple(p) for p in cuerpo["points"]] == default_mesh(1, 1)
    assert cuerpo["enabled"] is True


async def test_crear_con_subdivision_es_malla(cliente):
    client, _, _ = cliente

    cuerpo = (
        await client.post("/api/surfaces", json={"name": "columna", "mesh_cols": 3, "mesh_rows": 3})
    ).json()

    assert cuerpo["kind"] == "mesh"
    assert len(cuerpo["points"]) == 16


async def test_varias_caras_conviven(cliente):
    client, _, _ = cliente
    for nombre in ("frontal", "lateral", "superior"):
        await client.post("/api/surfaces", json={"name": nombre})

    listado = (await client.get("/api/surfaces")).json()

    assert [s["name"] for s in listado] == ["frontal", "lateral", "superior"]


async def test_guardar_puntos_persiste_y_avisa_al_render(cliente):
    client, app, enviados = cliente
    surface_id = (await client.post("/api/surfaces", json={"name": "cara"})).json()["id"]
    puntos = [[0.1, 0.1], [0.9, 0.12], [0.08, 0.9], [0.95, 0.88]]

    respuesta = await client.put(f"/api/surfaces/{surface_id}/points", json={"points": puntos})

    assert respuesta.status_code == 200
    assert [list(p) for p in respuesta.json()["points"]] == puntos
    fila = app.state.db.execute("SELECT points FROM surface WHERE id = ?", (surface_id,)).fetchone()
    assert json.loads(fila["points"])[0] == [0.1, 0.1]
    escenas = [m for m in enviados if m.get("op") == "scene"]
    assert escenas, "cada cambio de calibracion debe empujar la escena al render"
    primer_punto = escenas[-1]["scene"]["surfaces"][0]["points"][0]
    assert list(primer_punto) == [0.1, 0.1]


async def test_guardar_puntos_rechaza_cantidad_incorrecta(cliente):
    client, _, _ = cliente
    surface_id = (await client.post("/api/surfaces", json={"name": "cara"})).json()["id"]

    respuesta = await client.put(
        f"/api/surfaces/{surface_id}/points",
        json={"points": [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]]},
    )

    assert respuesta.status_code == 422
    assert "4 puntos" in respuesta.text


async def test_subdividir_conserva_las_esquinas(cliente):
    client, _, _ = cliente
    surface_id = (await client.post("/api/surfaces", json={"name": "cara"})).json()["id"]
    esquinas = [[0.2, 0.1], [0.8, 0.15], [0.1, 0.9], [0.9, 0.85]]
    await client.put(f"/api/surfaces/{surface_id}/points", json={"points": esquinas})

    cuerpo = (
        await client.post(f"/api/surfaces/{surface_id}/subdivide", json={"cols": 3, "rows": 3})
    ).json()

    assert cuerpo["kind"] == "mesh"
    assert len(cuerpo["points"]) == 16
    assert cuerpo["points"][0] == pytest.approx(esquinas[0])
    assert cuerpo["points"][3] == pytest.approx(esquinas[1])
    assert cuerpo["points"][12] == pytest.approx(esquinas[2])
    assert cuerpo["points"][15] == pytest.approx(esquinas[3])


async def test_resetear_vuelve_a_pantalla_completa_sin_perder_la_subdivision(cliente):
    client, _, _ = cliente
    surface_id = (
        await client.post("/api/surfaces", json={"name": "cara", "mesh_cols": 2, "mesh_rows": 2})
    ).json()["id"]
    await client.put(
        f"/api/surfaces/{surface_id}/points",
        json={"points": [[0.3, 0.3]] * 9},
    )

    cuerpo = (await client.post(f"/api/surfaces/{surface_id}/reset")).json()

    assert [tuple(p) for p in cuerpo["points"]] == default_mesh(2, 2)
    assert (cuerpo["mesh_cols"], cuerpo["mesh_rows"]) == (2, 2)


async def test_desactivar_una_cara_la_saca_de_la_escena(cliente):
    client, _, enviados = cliente
    surface_id = (await client.post("/api/surfaces", json={"name": "cara"})).json()["id"]

    await client.patch(f"/api/surfaces/{surface_id}", json={"enabled": False})

    escena = [m for m in enviados if m.get("op") == "scene"][-1]["scene"]
    assert escena["surfaces"] == []


async def test_borrar_superficie(cliente):
    client, _, _ = cliente
    surface_id = (await client.post("/api/surfaces", json={"name": "cara"})).json()["id"]

    assert (await client.delete(f"/api/surfaces/{surface_id}")).status_code == 204
    assert (await client.get(f"/api/surfaces/{surface_id}")).status_code == 404


async def test_operaciones_sobre_superficie_inexistente(cliente):
    client, _, _ = cliente
    assert (await client.get("/api/surfaces/999")).status_code == 404
    assert (await client.patch("/api/surfaces/999", json={"name": "x"})).status_code == 404
    assert (await client.post("/api/surfaces/999/reset")).status_code == 404
    assert (await client.delete("/api/surfaces/999")).status_code == 404


async def test_la_version_de_calibracion_sube_con_cada_cambio(cliente):
    client, app, _ = cliente

    def version() -> int:
        fila = app.state.db.execute(
            "SELECT value FROM setting WHERE key = 'calibration_version'"
        ).fetchone()
        return int(fila["value"])

    inicial = version()
    surface_id = (await client.post("/api/surfaces", json={"name": "cara"})).json()["id"]
    assert version() > inicial

    despues = version()
    await client.post(f"/api/surfaces/{surface_id}/reset")
    assert version() > despues
