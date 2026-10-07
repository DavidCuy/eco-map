"""Catalogo de efectos: manifiestos, armado del shader y seleccion desde la API."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.effects import (
    EffectError,
    build_fragment,
    color_to_rgb,
    discover,
    load_effect,
    resolve_params,
)
from ecomap_core.settings import Settings
from ecomap_web.main import create_app

RAIZ = Path(__file__).resolve().parent.parent
MIGRATIONS = RAIZ / "migrations"
EFFECTS_DIR = RAIZ / "effects"

MANIFIESTO_MINIMO = {
    "id": "prueba",
    "name": "Prueba",
    "params": [
        {"key": "color", "label": "Color", "type": "color", "default": "#ff8000"},
        {"key": "cantidad", "label": "Cantidad", "type": "float", "min": 1, "max": 9, "default": 4},
    ],
}
FRAGMENTO_MINIMO = "vec3 effect(vec2 uv) { return p_color * p_cantidad; }"


def _efecto(tmp_path: Path, manifiesto=None, fragmento=None, nombre="prueba") -> Path:
    directorio = tmp_path / nombre
    directorio.mkdir(parents=True)
    if manifiesto is not None:
        (directorio / "effect.json").write_text(json.dumps(manifiesto), encoding="utf-8")
    if fragmento is not None:
        (directorio / "frag.glsl").write_text(fragmento, encoding="utf-8")
    return directorio


# --- manifiestos ---------------------------------------------------------


def test_cargar_efecto_valido(tmp_path: Path):
    efecto = load_effect(_efecto(tmp_path, MANIFIESTO_MINIMO, FRAGMENTO_MINIMO))

    assert efecto.id == "prueba"
    assert [p.key for p in efecto.manifest.params] == ["color", "cantidad"]
    assert efecto.has_preview is False


def test_el_id_debe_coincidir_con_el_directorio(tmp_path: Path):
    # Si no coinciden, elegir un efecto por id dejaria de ser determinista.
    manifiesto = MANIFIESTO_MINIMO | {"id": "otro"}
    with pytest.raises(EffectError, match="no coincide"):
        load_effect(_efecto(tmp_path, manifiesto, FRAGMENTO_MINIMO))


def test_falta_el_fragmento(tmp_path: Path):
    with pytest.raises(EffectError, match="falta frag.glsl"):
        load_effect(_efecto(tmp_path, MANIFIESTO_MINIMO, None))


def test_el_fragmento_debe_definir_la_funcion_effect(tmp_path: Path):
    with pytest.raises(EffectError, match="vec3 effect"):
        load_effect(_efecto(tmp_path, MANIFIESTO_MINIMO, "void main() {}"))


def test_manifiesto_invalido(tmp_path: Path):
    with pytest.raises(EffectError, match="no es JSON valido"):
        directorio = tmp_path / "prueba"
        directorio.mkdir()
        (directorio / "effect.json").write_text("{roto", encoding="utf-8")
        load_effect(directorio)


def test_un_efecto_roto_no_impide_cargar_los_demas(tmp_path: Path):
    _efecto(tmp_path, MANIFIESTO_MINIMO, FRAGMENTO_MINIMO, nombre="prueba")
    _efecto(tmp_path, {"id": "roto", "name": "Roto"}, None, nombre="roto")

    efectos, errores = discover(tmp_path)

    assert [e.id for e in efectos] == ["prueba"]
    assert len(errores) == 1 and "roto" in errores[0]


def test_directorio_sin_manifiesto_se_ignora_en_silencio(tmp_path: Path):
    (tmp_path / "notas").mkdir()
    (tmp_path / "notas" / "leeme.txt").write_text("hola", encoding="utf-8")

    efectos, errores = discover(tmp_path)

    assert efectos == [] and errores == []


# --- armado del shader ---------------------------------------------------


def test_el_shader_declara_los_uniforms_del_manifiesto(tmp_path: Path):
    efecto = load_effect(_efecto(tmp_path, MANIFIESTO_MINIMO, FRAGMENTO_MINIMO))

    fragmento = build_fragment(efecto, "#version 330 core")

    assert fragmento.startswith("#version 330 core")
    assert "uniform vec3 p_color;" in fragmento
    assert "uniform float p_cantidad;" in fragmento
    assert "uniform sampler2D u_cam;" in fragmento  # uniforms comunes siempre
    assert "void main()" in fragmento  # el loader agrega el main


def test_el_header_cambia_con_el_contexto(tmp_path: Path):
    efecto = load_effect(_efecto(tmp_path, MANIFIESTO_MINIMO, FRAGMENTO_MINIMO))
    assert "precision mediump float;" in build_fragment(
        efecto, "#version 300 es\nprecision mediump float;\n"
    )


def test_los_parametros_sin_override_toman_el_default(tmp_path: Path):
    efecto = load_effect(_efecto(tmp_path, MANIFIESTO_MINIMO, FRAGMENTO_MINIMO))

    assert resolve_params(efecto.manifest, None) == {"color": "#ff8000", "cantidad": 4}
    assert resolve_params(efecto.manifest, {"cantidad": 7})["cantidad"] == 7
    # Un override de algo que el efecto no declara se ignora, no explota.
    assert "inventado" not in resolve_params(efecto.manifest, {"inventado": 1})


def test_conversion_de_color():
    assert color_to_rgb("#ffffff") == pytest.approx((1.0, 1.0, 1.0))
    assert color_to_rgb("#000000") == pytest.approx((0.0, 0.0, 0.0))
    assert color_to_rgb("#ff8000") == pytest.approx((1.0, 0.502, 0.0), abs=1e-3)
    # Un color invalido cae a negro en vez de romper el frame.
    assert color_to_rgb("verde") == (0.0, 0.0, 0.0)


# --- los efectos reales del repo -----------------------------------------


def test_los_efectos_base_del_repo_cargan():
    efectos, errores = discover(EFFECTS_DIR)

    assert errores == []
    assert {e.id for e in efectos} >= {"solid", "grid_test"}


def test_los_efectos_base_no_asumen_resolucion_fija():
    efectos, _ = discover(EFFECTS_DIR)
    for efecto in efectos:
        assert "1920" not in efecto.fragment
        assert "1080" not in efecto.fragment


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


async def test_listar_efectos(cliente):
    client, _, _ = cliente

    cuerpo = (await client.get("/api/effects")).json()

    ids = {e["id"] for e in cuerpo}
    assert {"solid", "grid_test"} <= ids
    grid = next(e for e in cuerpo if e["id"] == "grid_test")
    assert grid["available"] is True
    assert {p["key"] for p in grid["params"]} == {"cells", "contrast", "corners"}


async def test_activar_efecto_avisa_al_render_al_instante_y_al_disco_despues(cliente):
    """Lo que se ve viaja ya; lo que desgasta la tarjeta espera (US-14)."""
    client, app, enviados = cliente

    respuesta = await client.post("/api/effects/active", json={"id": "solid", "params": {}})

    assert respuesta.status_code == 200
    assert app.state.app_state.effect == "solid"
    assert [m for m in enviados if m.get("op") == "effect"][-1]["id"] == "solid"

    # En disco sigue el valor anterior: la escritura todavia no salio
    def guardado() -> str:
        return app.state.db.execute(
            "SELECT value FROM setting WHERE key = 'active_effect'"
        ).fetchone()["value"]

    assert guardado() == "grid_test"  # el que siembra la migracion 002

    await app.state.writer.flush()

    assert guardado() == "solid"


async def test_activar_efecto_inexistente(cliente):
    client, _, _ = cliente
    assert (await client.post("/api/effects/active", json={"id": "fantasma"})).status_code == 404


async def test_el_error_de_compilacion_del_render_queda_visible(cliente):
    client, app, _ = cliente
    app.state.app_state.handle_event(
        {"ev": "error", "source": "effect", "level": "error", "msg": "plasma: no compila"}
    )

    cuerpo = (await client.get("/api/system/status")).json()

    assert cuerpo["effect_error"] == "plasma: no compila"


# --- espejo en SQLite (#11) ----------------------------------------------


async def test_el_catalogo_se_espeja_al_arrancar(cliente):
    client, app, _ = cliente

    filas = app.state.db.execute("SELECT id, available FROM effect ORDER BY id").fetchall()

    assert {f["id"] for f in filas} >= {"grid_test", "solid"}
    assert all(f["available"] == 1 for f in filas)


async def test_un_efecto_que_desaparece_queda_no_disponible_pero_no_se_borra(
    cliente, tmp_path: Path
):
    """Borrar la fila rompería las capas que lo referencian: se degrada, no se
    pierde."""
    client, app, _ = cliente
    app.state.db.execute(
        "INSERT INTO effect (id, name, version, manifest, available) "
        "VALUES ('fantasma', 'Fantasma', '1', '{}', 1)"
    )

    await client.post("/api/effects/reload")

    fila = app.state.db.execute("SELECT available FROM effect WHERE id = 'fantasma'").fetchone()
    assert fila is not None, "la fila no se debe borrar"
    assert fila["available"] == 0


async def test_un_manifiesto_invalido_queda_registrado_en_event_log(tmp_path: Path):
    from ecomap_web import migrate
    from ecomap_web.db import connect
    from ecomap_web.services import effects as service

    settings = Settings(db=tmp_path / "e.db", migrations_dir=MIGRATIONS)
    migrate.run(settings)
    conn = connect(settings.db)
    roto = tmp_path / "efectos" / "roto"
    roto.mkdir(parents=True)
    (roto / "effect.json").write_text("{no es json", encoding="utf-8")

    resumen = service.sincronizar(conn, tmp_path / "efectos")

    assert resumen["errores"]
    eventos = conn.execute("SELECT message FROM event_log WHERE source = 'effects'").fetchall()
    assert any("roto" in e["message"] for e in eventos)


async def test_reload_reescanea_y_avisa_al_render(cliente):
    client, _, enviados = cliente

    respuesta = await client.post("/api/effects/reload")

    assert respuesta.status_code == 200
    assert any(m.get("op") == "effects_reload" for m in enviados)


async def test_el_render_manda_que_no_compila_y_la_ui_lo_marca(cliente):
    """El manifiesto puede estar perfecto y el shader fallar en el driver: eso
    solo lo sabe el render."""
    client, app, _ = cliente
    app.state.app_state.handle_event(
        {"ev": "effects", "compiled": ["solid"], "errors": {"grid_test": "line 12: syntax error"}}
    )

    cuerpo = (await client.get("/api/effects")).json()

    grid = next(e for e in cuerpo if e["id"] == "grid_test")
    solid = next(e for e in cuerpo if e["id"] == "solid")
    assert grid["compiled"] is False and "syntax error" in grid["error"]
    assert grid["available"] is True  # el archivo esta bien; lo que falla es el driver
    assert solid["compiled"] is True


async def test_el_preview_se_sirve_desde_el_volumen(cliente):
    client, _, _ = cliente

    respuesta = await client.get("/api/effects/grid_test/preview")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/jpeg"


async def test_el_preview_no_deja_escapar_del_volumen(cliente):
    client, _, _ = cliente
    respuesta = await client.get("/api/effects/..%2F..%2Fmigrations/preview")
    assert respuesta.status_code in (400, 404)


# --- parametros (#12) -----------------------------------------------------


async def test_actualizar_un_parametro_es_mezcla_parcial(cliente):
    client, app, _ = cliente
    await client.post("/api/effects/active", json={"id": "grid_test", "params": {"cells": 24}})

    await client.put("/api/effects/active/params", json={"params": {"contrast": 0.9}})

    assert app.state.app_state.effect_params == {"cells": 24, "contrast": 0.9}


async def test_solo_se_guardan_los_overrides(cliente):
    """Si el efecto agrega un parametro en una version nueva, se hereda solo."""
    client, app, _ = cliente

    await client.post("/api/effects/active", json={"id": "grid_test", "params": {"cells": 24}})
    await app.state.writer.flush()

    guardado = app.state.db.execute(
        "SELECT value FROM setting WHERE key = 'active_effect_params'"
    ).fetchone()
    assert json.loads(guardado["value"]) == {"cells": 24}  # no estan contrast ni corners


async def test_resetear_descarta_los_overrides(cliente):
    client, app, _ = cliente
    await client.post("/api/effects/active", json={"id": "grid_test", "params": {"cells": 24}})

    await client.post("/api/effects/active/reset")

    assert app.state.app_state.effect_params == {}


async def test_los_params_sin_efecto_activo_son_rechazados(cliente):
    client, app, _ = cliente
    app.state.app_state.effect = None
    assert (
        await client.put("/api/effects/active/params", json={"params": {"x": 1}})
    ).status_code == 422


async def test_la_ui_de_parametros_se_genera_desde_el_manifiesto(cliente):
    """Un efecto con un parametro nuevo debe mostrar su control sin tocar el
    frontend: por eso el control sale del manifiesto y no de una plantilla
    escrita a mano por efecto."""
    client, _, _ = cliente

    html = (
        await client.post(
            "/api/effects/active",
            json={"id": "grid_test"},
            headers={"HX-Request": "true"},
        )
    ).text

    assert 'type="range"' in html  # cells y contrast son float
    assert 'type="checkbox"' in html  # corners es bool
    assert 'data-param="cells"' in html and 'data-param="corners"' in html
    assert 'min="4.0"' in html and 'max="48.0"' in html  # rango del manifiesto
    assert "Restaurar valores por defecto" in html
    # Los controles no llevan HTMX: los maneja params.js, porque intercambiar
    # el fragmento mientras se arrastra arranca el slider del dedo (US-14).
    bloque_params = html.split('class="params"')[1].split("</div>")[0]
    assert "hx-put" not in bloque_params


async def test_el_color_se_renderiza_como_color_picker(cliente):
    client, _, _ = cliente

    html = (
        await client.post(
            "/api/effects/active", json={"id": "solid"}, headers={"HX-Request": "true"}
        )
    ).text

    assert 'type="color"' in html
    assert 'value="#ffffff"' in html  # default del manifiesto


async def test_el_paso_del_control_sale_del_manifiesto(cliente):
    """`cells` es un conteo: sin `step` la UI mostraba "40.08 celdas"."""
    client, _, _ = cliente

    html = (
        await client.post(
            "/api/effects/active", json={"id": "grid_test"}, headers={"HX-Request": "true"}
        )
    ).text

    assert 'data-param="cells"' in html
    assert 'step="1.0"' in html or 'step="1"' in html


# --- los tres efectos del catalogo v1 (#15) ------------------------------

EFECTOS_V1 = ("plasma", "waves", "noise_flow")


@pytest.mark.parametrize("effect_id", EFECTOS_V1)
def test_los_efectos_v1_cargan_con_preview(effect_id: str):
    efecto = load_effect(EFFECTS_DIR / effect_id)

    assert efecto.has_preview, "el catalogo los muestra con preview"
    assert efecto.manifest.name


@pytest.mark.parametrize("effect_id", EFECTOS_V1)
def test_los_efectos_v1_tienen_velocidad_escala_y_color(effect_id: str):
    efecto = load_effect(EFFECTS_DIR / effect_id)
    claves = {p.key for p in efecto.manifest.params}
    tipos = {p.key: p.type for p in efecto.manifest.params}

    assert "speed" in claves and "scale" in claves
    assert any(t == "color" for t in tipos.values())


@pytest.mark.parametrize("effect_id", EFECTOS_V1)
def test_los_shaders_no_usan_bucles_de_cota_dinamica(effect_id: str):
    """El compilador del V3D no puede desenrollar un bucle de cota dinamica.

    Es el tipo de cosa que compila en el escritorio y falla o se arrastra en la
    Pi, y no lo podemos detectar sin hardware: por eso se revisa el fuente.
    """
    import re

    fuente = (EFFECTS_DIR / effect_id / "frag.glsl").read_text(encoding="utf-8")
    for condicion in re.findall(r"for\s*\([^;]*;([^;]*);", fuente):
        assert re.search(r"<\s*\d+", condicion), (
            f"{effect_id}: bucle con cota no literal ({condicion.strip()})"
        )


@pytest.mark.parametrize("effect_id", EFECTOS_V1)
def test_los_shaders_no_usan_pow_dentro_de_bucles(effect_id: str):
    fuente = (EFFECTS_DIR / effect_id / "frag.glsl").read_text(encoding="utf-8")
    dentro = False
    for linea in fuente.splitlines():
        if "for (" in linea or "for(" in linea:
            dentro = True
        if dentro and "pow(" in linea:
            raise AssertionError(f"{effect_id}: pow() dentro de un bucle")
        if dentro and "}" in linea:
            dentro = False


def test_el_ruido_usa_highp_en_el_hash():
    """Con `mediump`, fract(sin(x) * 43758.0) pierde bits y el ruido se
    degrada en bandas. El header global declara mediump, asi que el hash tiene
    que pedir highp explicito. Otro caso que solo se ve en la Pi."""
    fuente = (EFFECTS_DIR / "noise_flow" / "frag.glsl").read_text(encoding="utf-8")
    hash_fn = fuente.split("float hash(")[1].split("}")[0]
    assert "highp" in hash_fn


def test_waves_cae_al_centro_sin_camara():
    """Sin camara `u_motion` vale 0; el origen tiene que quedar en el centro en
    vez de pegarse a una esquina."""
    fuente = (EFFECTS_DIR / "waves" / "frag.glsl").read_text(encoding="utf-8")
    assert "mix(vec2(0.5), u_motion_pos" in fuente


# --- escritura diferida (#14) --------------------------------------------


async def test_un_arrastre_largo_termina_en_una_sola_escritura(cliente):
    """El criterio de la US: un arrastre no puede escribir una vez por frame.

    Son 40 cambios, los que genera mover un slider un par de segundos.
    """
    client, app, enviados = cliente
    await client.post("/api/effects/active", json={"id": "grid_test"})
    await app.state.writer.flush()
    escrituras_antes = app.state.writer.writes

    for valor in range(4, 44):
        await client.put("/api/effects/active/params", json={"params": {"cells": valor}})

    # Durante el arrastre: ninguna escritura nueva...
    assert app.state.writer.writes == escrituras_antes
    # ...pero el render recibio los 40 valores, porque es lo que se ve.
    efectos = [m for m in enviados if m.get("op") == "effect"]
    assert efectos[-1]["params"]["cells"] == 43
    assert len([m for m in efectos if "cells" in m.get("params", {})]) >= 40

    await app.state.writer.flush()

    # Al calmarse, una sola escritura por clave, con el ultimo valor.
    assert app.state.writer.writes - escrituras_antes <= 2
    guardado = app.state.db.execute(
        "SELECT value FROM setting WHERE key = 'active_effect_params'"
    ).fetchone()
    assert json.loads(guardado["value"])["cells"] == 43


async def test_el_ultimo_valor_no_se_pierde_al_cerrar(cliente):
    """flush() corre en el cierre de la app: cerrar la pestana en medio de un
    arrastre no puede perder el valor."""
    client, app, _ = cliente
    await client.post("/api/effects/active", json={"id": "grid_test", "params": {"cells": 31}})

    await app.state.writer.flush()  # es lo que hace el lifespan al cerrar

    guardado = app.state.db.execute(
        "SELECT value FROM setting WHERE key = 'active_effect_params'"
    ).fetchone()
    assert json.loads(guardado["value"])["cells"] == 31


async def test_con_el_render_caido_el_valor_igual_se_persiste(cliente):
    client, app, _ = cliente

    async def caido(_message):
        return False

    app.state.bus.send = caido
    await client.post("/api/effects/active", json={"id": "solid", "params": {"brightness": 0.5}})
    await app.state.writer.flush()

    guardado = app.state.db.execute(
        "SELECT value FROM setting WHERE key = 'active_effect_params'"
    ).fetchone()
    assert json.loads(guardado["value"])["brightness"] == 0.5
    eventos = app.state.db.execute("SELECT message FROM event_log").fetchall()
    assert any("render no estaba conectado" in e["message"] for e in eventos)
