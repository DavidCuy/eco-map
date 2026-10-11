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
    """Una cara y la escena **activa**, que es el minimo para tener una capa.

    Se renombra la que ya existe en vez de crear otra: el arranque deja una
    escena de trabajo activa, y una creada despues queda inactiva — sus capas
    no se proyectan y no aparecen en lo que se le manda al render.
    """
    surface_id = (await client.post("/api/surfaces", json={"name": "frontal"})).json()["id"]
    activa = next(e for e in (await client.get("/api/scenes")).json() if e["is_active"])
    await client.patch(f"/api/scenes/{activa['id']}", json={"name": "principal"})
    return surface_id, activa["id"]


def _ultima_escena(enviados: list[dict]) -> dict:
    return [m for m in enviados if m.get("op") == "scene"][-1]["scene"]


# --- escenas -------------------------------------------------------------


async def test_siempre_hay_exactamente_una_escena_activa(cliente):
    """Si no, se podrian crear escenas y no proyectar nada.

    La primera la crea el arranque: un equipo recien instalado ya tiene escena
    de trabajo, porque al sacar el boton "+ escena" de la UI no quedaba forma
    de crear una. Lo que se comprueba es la invariante: una activa, siempre.
    """
    client, _, _ = cliente

    def activas(escenas):
        return [e for e in escenas if e["is_active"]]

    assert len(activas((await client.get("/api/scenes")).json())) == 1

    await client.post("/api/scenes", json={"name": "principal"})

    assert len(activas((await client.get("/api/scenes")).json())) == 1


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
    # La activa es la que creo el arranque: se activa otra a proposito para
    # que el borrado sea el de la que esta proyectando.
    primera = (await client.post("/api/scenes", json={"name": "a"})).json()["id"]
    await client.post(f"/api/scenes/{primera}/activate")
    await client.post("/api/scenes", json={"name": "b"})

    await client.delete(f"/api/scenes/{primera}")

    activas = [e for e in (await client.get("/api/scenes")).json() if e["is_active"]]
    assert len(activas) == 1 and activas[0]["name"] != "a"


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

    # Camino de reconexion: la escena serializada lo lleva, una vez que la
    # escritura diferida se volco (US-14).
    await app.state.writer.flush()
    from ecomap_web.services import scenes as scene_service

    escena = scene_service.serializar(app.state.db)
    assert escena["layers"] == []
    assert escena["fallback_effect"] == "grid_test"
    assert escena["fallback_params"] == {"cells": 8}


async def test_la_ui_avisa_cuando_proyecta_a_pantalla_completa(cliente):
    """El fallback es intencional, pero con caras calibradas y sin capas es
    indistinguible de que el warp este roto. Paso de verdad durante el
    desarrollo: hay que decirlo, no dejarlo adivinar."""
    client, _, _ = cliente
    await client.post("/api/surfaces", json={"name": "frontal"})
    # La capa va en la escena **activa**: una creada aparte no se proyecta, y
    # el aviso seguiria siendo correcto.
    scene_id = next(
        e["id"] for e in (await client.get("/api/scenes")).json() if e["is_active"]
    )

    html = (await client.get("/")).text
    assert "ninguna capa las usa" in html

    caras = (await client.get("/api/surfaces")).json()
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": caras[0]["id"], "effect_id": "solid"},
    )

    html = (await client.get("/")).text
    assert "ninguna capa las usa" not in html


async def test_sin_caras_no_hay_aviso(cliente):
    """Sin nada calibrado, pantalla completa es exactamente lo que se espera."""
    client, _, _ = cliente
    assert "ninguna capa las usa" not in (await client.get("/")).text


# --- el panel de capas: filtrado por cara, blend editable, arrastre --------


async def test_el_panel_trae_todas_las_capas_pero_marcadas_por_cara(cliente):
    """El filtrado por cara pasa en el cliente, no en el servidor.

    En el DOM van **todas** las capas de la escena en su orden de apilado, y
    cada una dice de que cara es. Dos razones: cambiar de cara no cuesta un
    viaje —se hace todo el tiempo al calibrar— y al arrastrar hay que poder
    mandar la lista completa, porque el orden es de la escena entera.
    """
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    otra = (await client.post("/api/surfaces", json={"name": "otra"})).json()["id"]
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "solid"},
    )
    await client.post(
        f"/api/scenes/{scene_id}/layers", json={"surface_id": otra, "effect_id": "plasma"}
    )

    html = (await client.get("/api/scenes/panel")).text

    assert html.count('data-id=') == 2, "las dos capas tienen que estar en el DOM"
    # Cada una se muestra solo cuando su cara es la activa
    assert f"activeId === {surface_id}" in html
    assert f"activeId === {otra}" in html


async def test_el_modo_de_mezcla_se_puede_cambiar_despues(cliente):
    """Antes el blend se elegia al crear la capa y quedaba fijo: para
    cambiarlo habia que borrarla y rehacerla."""
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    capa = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "solid", "blend_mode": "normal"},
        )
    ).json()

    html = (await client.get("/api/scenes/panel")).text
    assert f'hx-patch="/api/layers/{capa["id"]}"' in html
    assert "blend_mode" in html

    await client.patch(f"/api/layers/{capa['id']}", json={"blend_mode": "screen"})

    capas = (await client.get(f"/api/scenes/{scene_id}")).json()["layers"]
    assert capas[0]["blend_mode"] == "screen"


async def test_el_panel_ya_no_tiene_flechas_de_orden(cliente):
    """Se reordena arrastrando: con flechas hacia falta un viaje al servidor
    por cada posicion, y en el celular los botones quedaban diminutos."""
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "solid"},
    )

    html = (await client.get("/api/scenes/panel")).text

    assert "/move?direction=" not in html
    assert 'class="tirador"' in html
    assert 'id="layers-sortable"' in html


async def test_reordenar_respeta_las_capas_de_las_otras_caras(cliente):
    """Al ver una sola cara, arrastrar reordena lo visible y lo demas se queda
    donde esta. El cliente manda el orden completo del DOM, asi que esto es lo
    que el backend tiene que aceptar."""
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    otra = (await client.post("/api/surfaces", json={"name": "otra"})).json()["id"]
    a = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "solid"},
        )
    ).json()
    b = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "waves"},
        )
    ).json()
    oculta = (
        await client.post(
            f"/api/scenes/{scene_id}/layers", json={"surface_id": otra, "effect_id": "plasma"}
        )
    ).json()

    # Se invierten las dos visibles; la de la otra cara queda al final
    respuesta = await client.put(
        f"/api/scenes/{scene_id}/layers/order",
        json={"layer_ids": [b["id"], a["id"], oculta["id"]]},
    )

    assert respuesta.status_code == 200
    capas = (await client.get(f"/api/scenes/{scene_id}")).json()["layers"]
    assert [c["id"] for c in capas] == [b["id"], a["id"], oculta["id"]]


async def test_un_orden_incompleto_se_rechaza(cliente):
    """Mandar solo las capas visibles borraria el orden de las demas."""
    client, _, _ = cliente
    surface_id, scene_id = await _montar(client)
    a = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "solid"},
        )
    ).json()
    await client.post(
        f"/api/scenes/{scene_id}/layers",
        json={"surface_id": surface_id, "effect_id": "waves"},
    )

    respuesta = await client.put(
        f"/api/scenes/{scene_id}/layers/order", json={"layer_ids": [a["id"]]}
    )

    assert respuesta.status_code == 422


# --- parametros por capa --------------------------------------------------
#
# Hasta ahora los unicos sliders del dashboard eran los del efecto global, que
# ni siquiera se proyecta cuando la escena tiene capas: cada capa corria con
# los valores por defecto y no habia forma de cambiarlos, aunque la base los
# guardaba y la API los aceptaba.


async def _una_capa(client, efecto: str = "waves") -> dict:
    surface_id, scene_id = await _montar(client)
    return (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": efecto},
        )
    ).json()


async def test_el_panel_de_una_capa_trae_los_controles_de_su_efecto(cliente):
    """Se generan desde el manifiesto, igual que los del efecto global: un
    efecto con un parametro nuevo aparece sin tocar el frontend."""
    client, _, _ = cliente
    capa = await _una_capa(client)

    html = (await client.get(f"/api/layers/{capa['id']}/panel")).text

    assert f'data-params-url="/api/layers/{capa["id"]}/params"' in html
    assert 'data-param="speed"' in html
    # La miniatura del efecto, que es como se identifica la capa de un vistazo
    assert f'/api/effects/{capa["effect_id"]}/preview' in html


async def test_el_panel_de_una_capa_que_no_existe_da_404(cliente):
    client, _, _ = cliente
    assert (await client.get("/api/layers/999/panel")).status_code == 404


async def test_cambiar_un_parametro_de_capa_no_pisa_los_otros(cliente):
    """Mezcla parcial: mover un slider no puede resetear el resto."""
    client, app, _ = cliente
    capa = await _una_capa(client)

    await client.put(f"/api/layers/{capa['id']}/params", json={"params": {"speed": 2.5}})
    await client.put(f"/api/layers/{capa['id']}/params", json={"params": {"scale": 12.0}})

    # La escritura esta diferida: sin volcarla, la base todavia no los tiene.
    await app.state.writer.flush()
    capas = (await client.get(f"/api/scenes/{capa['scene_id']}")).json()["layers"]
    assert capas[0]["params"] == {"speed": 2.5, "scale": 12.0}


async def test_el_parametro_viaja_al_render_antes_de_escribirse_en_disco(cliente):
    """Lo que se ve viaja siempre; lo que se guarda se difiere (ADR-004).

    Si la escena que se le manda al render se armara solo desde la base, el
    render recibiria el valor viejo hasta que la escritura diferida se volcara
    medio segundo despues: el slider se moveria y la proyeccion no.
    """
    client, app, enviados = cliente
    capa = await _una_capa(client)
    enviados.clear()

    await client.put(f"/api/layers/{capa['id']}/params", json={"params": {"speed": 4.0}})

    escena = [m for m in enviados if m.get("op") == "scene"][-1]["scene"]
    assert escena["layers"][0]["params"]["speed"] == 4.0
    # Y todavia no toco la base
    assert app.state.app_state.layer_params[capa["id"]] == {"speed": 4.0}


async def test_muchos_cambios_seguidos_terminan_en_una_sola_escritura(cliente):
    """Un arrastre genera decenas de valores por segundo. En la Pi la SD es la
    causa numero uno de muerte, asi que las escrituras se agrupan."""
    client, app, _ = cliente
    capa = await _una_capa(client)
    writer = app.state.writer
    antes = writer.writes

    for valor in range(10):
        await client.put(
            f"/api/layers/{capa['id']}/params", json={"params": {"speed": float(valor)}}
        )

    assert writer.writes == antes, "no deberia haber escrito todavia"
    await writer.flush()
    assert writer.writes - antes == 1, "diez cambios, una sola escritura"

    capas = (await client.get(f"/api/scenes/{capa['scene_id']}")).json()["layers"]
    assert capas[0]["params"]["speed"] == 9.0, "el ultimo valor no se pierde"


async def test_restaurar_descarta_los_overrides(cliente):
    """Se descartan, no se copian los defaults: asi la capa sigue heredando si
    el efecto cambia de version (ADR-011)."""
    client, _, _ = cliente
    capa = await _una_capa(client)
    await client.put(f"/api/layers/{capa['id']}/params", json={"params": {"speed": 7.0}})

    await client.post(f"/api/layers/{capa['id']}/params/reset")

    capas = (await client.get(f"/api/scenes/{capa['scene_id']}")).json()["layers"]
    assert capas[0]["params"] == {}


async def test_cada_capa_tiene_sus_propios_parametros(cliente):
    """Dos capas del mismo efecto sobre la misma cara no comparten valores."""
    client, app, _ = cliente
    surface_id, scene_id = await _montar(client)
    a = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "waves"},
        )
    ).json()
    b = (
        await client.post(
            f"/api/scenes/{scene_id}/layers",
            json={"surface_id": surface_id, "effect_id": "waves"},
        )
    ).json()

    await client.put(f"/api/layers/{a['id']}/params", json={"params": {"speed": 1.0}})
    await client.put(f"/api/layers/{b['id']}/params", json={"params": {"speed": 9.0}})

    await app.state.writer.flush()
    escena = (await client.get(f"/api/scenes/{scene_id}")).json()
    capas = {c["id"]: c["params"] for c in escena["layers"]}
    assert capas[a["id"]]["speed"] == 1.0
    assert capas[b["id"]]["speed"] == 9.0


async def test_el_fragmento_no_trae_avisos_que_puedan_quedar_viejos(cliente):
    """Regresion: «Primero hace falta una cara» se renderizaba en el servidor.

    Crear una cara no recarga este fragmento —lo hace Alpine contra la API—,
    asi que el aviso se quedaba en pantalla **contradiciendo** al boton de
    agregar capa, que ya estaba habilitado. Lo que dependa del numero de caras
    tiene que evaluarse en el cliente, que es quien lo sabe al instante.
    """
    client, _, _ = cliente

    html = (await client.get("/api/scenes/panel")).text

    assert "Primero hace falta una cara" not in html
    # Los mensajes que quedan son condicionales de Alpine, no texto fijo
    assert 'x-show="surfaces.length' in html


async def test_sin_caras_el_dashboard_ofrece_crear_una(cliente):
    """Con cero caras el formulario de capa queda inutil: su boton se ve
    deshabilitado y se lee como que no existe. En vez de eso se ofrece la
    salida, que es crear la cara."""
    client, _, _ = cliente

    html = (await client.get("/")).text

    assert "crear la primera cara" in html
    assert 'class="sin-caras"' in html
    # Y el formulario solo aparece cuando hay caras
    assert 'class="nueva-capa" x-show="surfaces.length"' in html
