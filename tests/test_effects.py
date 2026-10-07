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


async def test_activar_efecto_persiste_y_avisa_al_render(cliente):
    client, app, enviados = cliente

    respuesta = await client.post("/api/effects/active", json={"id": "solid", "params": {}})

    assert respuesta.status_code == 200
    assert app.state.app_state.effect == "solid"
    fila = app.state.db.execute("SELECT value FROM setting WHERE key = 'active_effect'").fetchone()
    assert fila["value"] == "solid"
    assert [m for m in enviados if m.get("op") == "effect"][-1]["id"] == "solid"


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
