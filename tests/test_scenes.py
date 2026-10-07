"""Escenas y capas: CRUD, orden, blend, tope y lo que llega al render."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.settings import Settings
from ecomap_web.main import create_app

RAIZ = Path(__file__).resolve().parent.parent
MIGRATIONS = RAIZ / "migrations"
EFFECTS_DIR = RAIZ / "effects"


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


async def _montar(client) -> tuple[int, int]:
    """Una cara y una escena, que es el minimo para tener una capa."""
    surface_id = (await client.post("/api/surfaces", json={"name": "frontal"})).json()["id"]
    scene_id = (await client.post("/api/scenes", json={"name": "principal"})).json()["id"]
    return surface_id, scene_id


def _ultima_escena(enviados: list[dict]) -> dict:
    return [m for m in enviados if m.get("op") == "scene"][-1]["scene"]


# --- escenas -------------------------------------------------------------


async def test_la_primera_escena_queda_activa(cliente):
    """Si no, se podrian crear escenas y no proyectar nada."""
    client, _, _ = cliente

    escena = (await client.post("/api/scenes", json={"name": "principal"})).json()

    assert escena["is_active"] is True


async def test_activar_una_escena_cambia_lo_que_se_proyecta(cliente):
    client, _, enviados = cliente
    surface_id, primera = await _montar(client)
    await client.post(
        f"/api/scenes/{primera}/layers",
        json={"surface_id": surface_id, "effect_id": "grid_test"},
    )
    segunda = (await client.post("/api/scenes", json={"name": "vacia"})).json()["id"]

    await client.post(f"/api/scenes/{segunda}/activate")

    escena = _ultima_escena(enviados)
    assert escena["scene_id"] == segunda
    assert escena["layers"] == []  # la escena nueva no tiene capas


async def test_duplicar_copia_las_capas(cliente):
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "solid", "blend_mode": "add"},
    )

    copia = (await client.post(f"/api/scenes/{scene_id}/duplicate")).json()

    assert copia["name"] == "principal (copia)"
    assert len(copia["layers"]) == 1
    assert copia["layers"][0]["blend_mode"] == "add"
    assert copia["is_active"] is False  # duplicar no cambia lo que se proyecta


async def test_marcar_default_es_excluyente(cliente):
    client, _, _ = cliente
    primera = (await client.post("/api/scenes", json={"name": "a"})).json()["id"]
    segunda = (await client.post("/api/scenes", json={"name": "b"})).json()["id"]

    await client.post(f"/api/scenes/{primera}/default")
    await client.post(f"/api/scenes/{segunda}/default")

    escenas = {e["id"]: e for e in (await client.get("/api/scenes")).json()}
    assert escenas[primera]["is_default"] is False
    assert escenas[segunda]["is_default"] is True


async def test_borrar_la_escena_activa_pasa_a_otra(cliente):
    client, _, _ = cliente
    primera = (await client.post("/api/scenes", json={"name": "a"})).json()["id"]
    await client.post("/api/scenes", json={"name": "b"})

    await client.delete(f"/api/scenes/{primera}")

    activas = [e for e in (await client.get("/api/scenes")).json() if e["is_active"]]
    assert len(activas) == 1 and activas[0]["name"] == "b"


async def test_borrar_escena_borra_sus_capas(cliente):
    client, app, _ = cliente
    surface_id, scene_id = await _montar(client)
    await client.post(
        f"/api/scenes/{scene_id}/layers", json={"surface_id": surface_id, "effect_id": "solid"}
    )

    await client.delete(f"/api/scenes/{scene_id}")

    assert app.state.db.execute("SELECT COUNT(*) AS n FROM layer").fetchone()["n"] == 0


# --- capas ---------------------------------------------------------------


async def test_crear_capa_asigna_un_efecto_a_una_cara(cliente):
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)

    capa = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "grid_test"},
        )
    ).json()

    assert capa["surface_name"] == "frontal"
    assert capa["effect_name"] == "Grilla de calibracion"
    assert capa["z_order"] == 0
    assert capa["blend_mode"] == "normal"
    assert capa["enabled"] is True


async def test_las_capas_se_apilan_en_orden(cliente):
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)

    for effect in ("solid", "grid_test"):
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": effect},
        )

    capas = (await client.get(f"/api/scenes/{scene_id}")).json()["layers"]
    assert [c["z_order"] for c in capas] == [0, 1]


async def test_reordenar_capas(cliente):
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    ids = [
        (
            await client.post(
                f"/api/scenes/{scene_id}/layers",
                json={"surface_id": surface_id, "effect_id": e},
            )
        ).json()["id"]
        for e in ("solid", "grid_test")
    ]

    escena = (
        await client.put(
            f"/api/scenes/{scene_id}/layers/order", json={"layer_ids": list(reversed(ids))}
        )
    ).json()

    assert [c["id"] for c in escena["layers"]] == list(reversed(ids))


async def test_reordenar_tiene_que_incluir_todas_las_capas(cliente):
    """Un reordenamiento parcial dejaria capas con z duplicado y el apilado
    pasaria a depender del id, que no es lo que el usuario ve."""
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    primera = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "solid"},
        )
    ).json()["id"]
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "grid_test"},
    )

    respuesta = await client.put(
        f"/api/scenes/{scene_id}/layers/order", json={"layer_ids": [primera]}
    )

    assert respuesta.status_code == 422


async def test_tope_de_capas(cliente):
    client, app, _ = cliente
    surface_id, scene_id = await _montar(client)
    app.state.db.execute("UPDATE setting SET value = '2' WHERE key = 'max_layers'")
    app.state.db.execute("INSERT OR IGNORE INTO setting (key, value) VALUES ('max_layers', '2')")

    for _ in range(2):
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "solid"},
        )
    respuesta = await client.post(
        f"/api/scenes/{scene_id}/layers", json={"surface_id": surface_id, "effect_id": "solid"}
    )

    assert respuesta.status_code == 422
    assert "tope" in respuesta.text


async def test_capa_con_efecto_inexistente(cliente):
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)

    respuesta = await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "fantasma"},
    )

    assert respuesta.status_code == 422
    assert "catalogo" in respuesta.text


async def test_capa_con_superficie_inexistente(cliente):
    client, _, _ = cliente
    _, scene_id = await _montar(client)

    respuesta = await client.post(
        f"/api/scenes/{scene_id}/layers", json={"surface_id": 999, "effect_id": "solid"}
    )

    assert respuesta.status_code == 422


async def test_actualizar_capa_es_mezcla_parcial(cliente):
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    layer_id = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "grid_test", "params": {"cells": 20}},
        )
    ).json()["id"]

    capa = (
        await client.patch(f"/api/layers/{layer_id}", json={"params": {"contrast": 0.3}})
    ).json()

    assert capa["params"] == {"cells": 20, "contrast": 0.3}


async def test_modos_de_blend(cliente):
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    layer_id = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "solid"},
        )
    ).json()["id"]

    for modo in ("add", "multiply", "screen", "normal"):
        capa = (await client.patch(f"/api/layers/{layer_id}", json={"blend_mode": modo})).json()
        assert capa["blend_mode"] == modo

    assert (
        await client.patch(f"/api/layers/{layer_id}", json={"blend_mode": "inventado"})
    ).status_code == 422


# --- lo que llega al render ----------------------------------------------


async def test_la_escena_lleva_la_geometria_dentro_de_cada_capa(cliente):
    """El render no tiene indice de superficies: con un solo mensaje tiene que
    poder redibujar todo."""
    client, _, enviados = cliente
    surface_id, scene_id = await _montar(client)
    puntos = [[0.1, 0.1], [0.9, 0.12], [0.08, 0.9], [0.95, 0.88]]
    await client.put(f"/api/surfaces/{surface_id}/points", json={"points": puntos})
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "grid_test", "blend_mode": "add"},
    )

    escena = _ultima_escena(enviados)

    assert len(escena["layers"]) == 1
    capa = escena["layers"][0]
    assert capa["effect"] == "grid_test"
    assert capa["blend"] == "add"
    assert [list(p) for p in capa["surface"]["points"]] == puntos


async def test_una_capa_deshabilitada_no_llega_al_render(cliente):
    client, _, enviados = cliente
    surface_id, scene_id = await _montar(client)
    layer_id = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "solid"},
        )
    ).json()["id"]

    await client.patch(f"/api/layers/{layer_id}", json={"enabled": False})

    assert _ultima_escena(enviados)["layers"] == []


async def test_una_cara_deshabilitada_saca_sus_capas(cliente):
    """El render recibe lo que se dibuja: no tiene que razonar sobre estados."""
    client, _, enviados = cliente
    surface_id, scene_id = await _montar(client)
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "solid"},
    )

    await client.patch(f"/api/surfaces/{surface_id}", json={"enabled": False})

    assert _ultima_escena(enviados)["layers"] == []


async def test_el_efecto_de_fallback_viaja_por_dos_caminos(cliente):
    """Es lo que permite apuntar el proyector antes de configurar nada.

    Cambiarlo manda su propio op, que es el camino de baja latencia; y ademas
    queda dentro de la escena, que es lo que el render recibe al reconectar.
    """
    client, app, enviados = cliente
    await client.post("/api/effects/active", json={"id": "grid_test", "params": {"cells": 8}})

    # Camino inmediato
    efectos = [m for m in enviados if m.get("op") == "effect"]
    assert efectos[-1]["id"] == "grid_test"
    assert efectos[-1]["params"] == {"cells": 8}

    # Camino de reconexion: la escena serializada lo lleva
    from ecomap_web.services import scenes as scene_service

    escena = scene_service.serializar(app.state.db)
    assert escena["layers"] == []
    assert escena["fallback_effect"] == "grid_test"
    assert escena["fallback_params"] == {"cells": 8}
