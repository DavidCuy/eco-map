"""Escenas como archivos: guardar, abrir, y no perder la calibracion.

Abrir una escena reemplaza la instalacion entera, calibracion incluida. Es una
decision tomada a sabiendas, y lo que se prueba aca es que sea **reversible**:
que el respaldo automatico exista y sirva para volver.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.settings import Settings
from ecomap_web.main import create_app
from ecomap_web.services import snapshots as service

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
        bus=f"tcp://127.0.0.1:{_puerto_libre()}",  # render offline
        effects_dir=EFFECTS_DIR,
        media_dir=tmp_path / "media",
        scenes_dir=tmp_path / "scenes",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client, app, settings.scenes_dir


async def _instalacion(client) -> dict:
    """Una instalacion de ejemplo: dos caras, una deformada, y dos capas."""
    frontal = (await client.post("/api/surfaces", json={"name": "frontal"})).json()
    lateral = (
        await client.post("/api/surfaces", json={"name": "lateral", "mesh_cols": 3, "mesh_rows": 3})
    ).json()
    # Mover una esquina: es lo que representa el trabajo de calibrar
    puntos = list(frontal["points"])
    puntos[0] = [0.17, 0.23]
    await client.put(f"/api/surfaces/{frontal['id']}/points", json={"points": puntos})

    escenas = (await client.get("/api/scenes")).json()
    escena = escenas[0] if escenas else (
        await client.post("/api/scenes", json={"name": "escena"})
    ).json()
    await client.post(
        f"/api/scenes/{escena['id']}/layers",
        json={"surface_id": frontal["id"], "effect_id": "plasma", "blend_mode": "add"},
    )
    await client.post(
        f"/api/scenes/{escena['id']}/layers",
        json={"surface_id": lateral["id"], "effect_id": "waves"},
    )
    return {"frontal": frontal, "lateral": lateral, "escena": escena}


# --- nombres de archivo --------------------------------------------------


def test_el_nombre_se_limpia_para_ser_un_archivo():
    # Los acentos se conservan: el sistema de archivos los acepta y el nombre
    # sigue siendo el que la persona escribio.
    assert service.nombre_de_archivo("Fiesta del Sábado") == "fiesta-del-sábado.json"
    assert service.nombre_de_archivo("  demo 2  ") == "demo-2.json"


def test_un_nombre_no_puede_escribir_fuera_del_directorio():
    """El nombre llega por HTTP y termina siendo una ruta: sin limpiarlo, un
    `../` escribe donde no debe."""
    seguro = service.nombre_de_archivo("../../etc/passwd")
    assert "/" not in seguro and ".." not in seguro

    # Un nombre que al limpiarse no deja nada no puede terminar en un archivo
    for peligroso in ("..", "///", "   ", "."):
        with pytest.raises(service.SnapshotError):
            service.nombre_de_archivo(peligroso)


# --- ida y vuelta --------------------------------------------------------


async def test_guardar_y_abrir_devuelve_la_misma_instalacion(cliente):
    """El criterio del #29: exportar, destruir, importar, y comprobar que
    quedo igual."""
    client, _, _ = cliente
    original = await _instalacion(client)

    assert (await client.post("/api/snapshots", json={"name": "fiesta"})).status_code == 200

    # Destruir: borrar las dos caras se lleva las capas por cascada
    for cara in (await client.get("/api/surfaces")).json():
        await client.delete(f"/api/surfaces/{cara['id']}")
    assert (await client.get("/api/surfaces")).json() == []

    respuesta = await client.post("/api/snapshots/fiesta.json/open")
    assert respuesta.status_code == 200
    informe = respuesta.json()
    assert informe["caras"] == 2
    assert informe["capas"] == 2
    assert informe["omitidas"] == []

    caras = {c["name"]: c for c in (await client.get("/api/surfaces")).json()}
    assert set(caras) == {"frontal", "lateral"}
    # La esquina movida volvio donde estaba: es lo que vale de una calibracion
    assert caras["frontal"]["points"][0] == pytest.approx([0.17, 0.23])
    assert caras["lateral"]["mesh_cols"] == 3

    capas = (await client.get("/api/scenes")).json()[0]["layers"]
    assert {(c["effect_id"], c["surface_name"], c["blend_mode"]) for c in capas} == {
        ("plasma", "frontal", "add"),
        ("waves", "lateral", "normal"),
    }
    assert original["frontal"]["name"] == "frontal"


async def test_las_capas_referencian_las_caras_por_nombre(cliente):
    """Los ids no significan nada en otro equipo: un archivo guardado aca
    tiene que poder abrirse alla."""
    client, _, scenes_dir = cliente
    await _instalacion(client)
    await client.post("/api/snapshots", json={"name": "demo"})

    datos = json.loads((scenes_dir / "demo.json").read_text(encoding="utf-8"))

    assert {c["cara"] for c in datos["capas"]} == {"frontal", "lateral"}
    assert all("surface_id" not in c for c in datos["capas"])


# --- la red de seguridad -------------------------------------------------


async def test_abrir_deja_un_respaldo_de_lo_que_habia(cliente):
    """Abrir pisa la calibracion. Que sea reversible no es un lujo:
    recalibrar cuesta veinte minutos y nadie respalda antes de probar algo."""
    client, _, scenes_dir = cliente
    await _instalacion(client)
    await client.post("/api/snapshots", json={"name": "buena"})

    # Se cambia la instalacion y se guarda otra distinta
    for cara in (await client.get("/api/surfaces")).json():
        await client.delete(f"/api/surfaces/{cara['id']}")
    await client.post("/api/surfaces", json={"name": "otra-cosa"})
    await client.post("/api/snapshots", json={"name": "mala"})

    informe = (await client.post("/api/snapshots/buena.json/open")).json()

    assert informe["respaldo"].startswith("respaldo-")
    respaldo = json.loads((scenes_dir / informe["respaldo"]).read_text(encoding="utf-8"))
    # El respaldo tiene lo que habia justo antes de abrir
    assert [c["nombre"] for c in respaldo["caras"]] == ["otra-cosa"]

    # Y se puede volver a el
    await client.post(f"/api/snapshots/{informe['respaldo']}/open")
    assert [c["name"] for c in (await client.get("/api/surfaces")).json()] == ["otra-cosa"]


async def test_los_respaldos_no_crecen_sin_limite(cliente, monkeypatch):
    """En una SD, un respaldo por apertura la termina llenando."""
    monkeypatch.setattr(service, "MAX_RESPALDOS", 3)
    client, _, scenes_dir = cliente
    await _instalacion(client)
    await client.post("/api/snapshots", json={"name": "base"})

    for _ in range(6):
        await client.post("/api/snapshots/base.json/open")

    respaldos = list(scenes_dir.glob("respaldo-*.json"))
    assert len(respaldos) <= 3


# --- archivos que no cuadran ---------------------------------------------


async def test_una_capa_cuyo_efecto_no_existe_se_omite_y_se_reporta(cliente):
    """Mover una instalacion a un equipo donde falta un efecto no deberia
    rechazar el archivo entero: se aplica lo que se puede y se dice que falto."""
    client, _, scenes_dir = cliente
    await _instalacion(client)
    await client.post("/api/snapshots", json={"name": "demo"})

    ruta = scenes_dir / "demo.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["capas"].append({"cara": "frontal", "efecto": "no-instalado", "blend": "normal"})
    datos["capas"].append({"cara": "no-existe", "efecto": "plasma", "blend": "normal"})
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    informe = (await client.post("/api/snapshots/demo.json/open")).json()

    assert informe["capas"] == 2  # las dos buenas entraron
    assert len(informe["omitidas"]) == 2
    assert any("no-instalado" in m for m in informe["omitidas"])
    assert any("no-existe" in m for m in informe["omitidas"])


async def test_un_archivo_de_otro_formato_se_rechaza(cliente):
    client, _, scenes_dir = cliente
    scenes_dir.mkdir(parents=True, exist_ok=True)
    (scenes_dir / "futura.json").write_text('{"ecomap": 99, "caras": [], "capas": []}')

    respuesta = await client.post("/api/snapshots/futura.json/open")

    assert respuesta.status_code == 422
    assert "formato" in respuesta.text


async def test_un_json_roto_no_rompe_la_lista(cliente):
    """Un archivo ilegible tiene que poder verse para poder borrarlo."""
    client, _, scenes_dir = cliente
    scenes_dir.mkdir(parents=True, exist_ok=True)
    (scenes_dir / "roto.json").write_text("{ esto no es json")

    listado = (await client.get("/api/snapshots")).json()["snapshots"]

    assert any(s["archivo"] == "roto.json" and s["roto"] for s in listado)


async def test_una_malla_incompleta_se_rechaza_antes_de_tocar_la_base(cliente):
    """Un archivo con puntos de menos dejaria una superficie que el render no
    puede triangular. Mejor rechazarlo que escribirlo."""
    client, _, scenes_dir = cliente
    await _instalacion(client)
    await client.post("/api/snapshots", json={"name": "demo"})
    ruta = scenes_dir / "demo.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["caras"][0]["points"] = [[0, 0], [1, 0]]  # faltan dos
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    respuesta = await client.post("/api/snapshots/demo.json/open")

    assert respuesta.status_code == 422
    # Y la instalacion sigue en pie
    assert len((await client.get("/api/surfaces")).json()) == 2


# --- subir y descargar ---------------------------------------------------


async def test_descargar_devuelve_el_json(cliente):
    client, _, _ = cliente
    await _instalacion(client)
    await client.post("/api/snapshots", json={"name": "demo"})

    respuesta = await client.get("/api/snapshots/demo.json/download")

    assert respuesta.status_code == 200
    assert "attachment" in respuesta.headers["content-disposition"]
    assert json.loads(respuesta.text)["ecomap"] == service.FORMATO


async def test_subir_guarda_pero_no_aplica(cliente):
    """Subir y aplicar en un paso haria que un archivo equivocado pisara la
    calibracion antes de que nadie lo mire."""
    client, _, scenes_dir = cliente
    await _instalacion(client)
    antes = [c["name"] for c in (await client.get("/api/surfaces")).json()]

    archivo = json.dumps(
        {
            "ecomap": service.FORMATO,
            "nombre": "de-otro-equipo",
            "caras": [
                {"nombre": "unica", "mesh_cols": 1, "mesh_rows": 1,
                 "points": [[0, 0], [1, 0], [0, 1], [1, 1]]}
            ],
            "capas": [],
        }
    )
    respuesta = await client.post(
        "/api/snapshots/upload",
        files={"archivo": ("otra.json", archivo, "application/json")},
    )

    assert respuesta.status_code == 200
    assert (scenes_dir / "de-otro-equipo.json").exists()
    # La instalacion no se toco
    assert [c["name"] for c in (await client.get("/api/surfaces")).json()] == antes


async def test_subir_algo_que_no_es_json_se_rechaza(cliente):
    client, _, _ = cliente
    respuesta = await client.post(
        "/api/snapshots/upload",
        files={"archivo": ("x.json", b"\x00\x01binario", "application/json")},
    )
    assert respuesta.status_code == 422


async def test_un_equipo_nuevo_ya_tiene_escena_de_trabajo(cliente):
    """Al sacar el boton "+ escena", una instalacion recien hecha se quedaba
    sin ninguna y sin forma de crear capas: el panel salia vacio y sin
    explicacion. La escena actual existe desde el primer arranque."""
    client, _, _ = cliente

    escenas = (await client.get("/api/scenes")).json()

    assert len(escenas) == 1
    assert escenas[0]["is_active"] is True
    # Y se le pueden agregar capas sin crear nada antes
    cara = (await client.post("/api/surfaces", json={"name": "unica"})).json()
    respuesta = await client.post(
        f"/api/scenes/{escenas[0]['id']}/layers",
        json={"surface_id": cara["id"], "effect_id": "solid"},
    )
    assert respuesta.status_code == 201
