"""La escena como documento: se abre y se guarda como archivo.

Guardar baja un JSON a la computadora de quien lo usa; abrir sube uno y lo
aplica. No hay escenas guardadas en el equipo ni lista que navegar: el
documento abierto es el que esta en la base.

Abrir reemplaza la instalacion entera, calibracion incluida. Lo que se prueba
aca es sobre todo que eso sea **reversible**: que el respaldo exista y que
deshacer sirva para volver.
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
    """Dos caras, una con una esquina movida, y dos capas."""
    frontal = (await client.post("/api/surfaces", json={"name": "frontal"})).json()
    lateral = (
        await client.post("/api/surfaces", json={"name": "lateral", "mesh_cols": 3, "mesh_rows": 3})
    ).json()
    # Mover una esquina representa el trabajo de calibrar
    puntos = list(frontal["points"])
    puntos[0] = [0.17, 0.23]
    await client.put(f"/api/surfaces/{frontal['id']}/points", json={"points": puntos})

    escena = next(e for e in (await client.get("/api/scenes")).json() if e["is_active"])
    await client.post(
        f"/api/scenes/{escena['id']}/layers",
        json={"surface_id": frontal["id"], "effect_id": "plasma", "blend_mode": "add"},
    )
    await client.post(
        f"/api/scenes/{escena['id']}/layers",
        json={"surface_id": lateral["id"], "effect_id": "waves"},
    )
    return {"frontal": frontal, "lateral": lateral, "escena": escena}


async def _descargar(client) -> dict:
    return json.loads((await client.get("/api/scene/file")).text)


async def _abrir(client, datos: dict):
    return await client.post(
        "/api/scene/file",
        files={"archivo": ("escena.json", json.dumps(datos), "application/json")},
    )


# --- nombres de archivo --------------------------------------------------


def test_el_nombre_se_limpia_para_ser_un_archivo():
    assert service.nombre_de_archivo("  demo 2  ") == "demo-2.json"


def test_un_nombre_no_puede_escribir_fuera_del_directorio():
    """El nombre llega por HTTP y termina siendo una ruta: sin limpiarlo, un
    `../` escribe donde no debe."""
    seguro = service.nombre_de_archivo("../../etc/passwd")
    assert "/" not in seguro and ".." not in seguro

    for peligroso in ("..", "///", "   ", "."):
        with pytest.raises(service.SnapshotError):
            service.nombre_de_archivo(peligroso)


# --- guardar: una descarga, no un archivo en el equipo -------------------


async def test_guardar_baja_un_archivo_y_no_deja_nada_en_el_equipo(cliente):
    """El archivo es de quien lo usa. Si el equipo guardara una copia habria
    dos verdades y ninguna forma de saber cual es la buena."""
    client, _, scenes_dir = cliente
    await _instalacion(client)

    respuesta = await client.get("/api/scene/file")

    assert respuesta.status_code == 200
    assert "attachment" in respuesta.headers["content-disposition"]
    assert ".json" in respuesta.headers["content-disposition"]
    datos = json.loads(respuesta.text)
    assert len(datos["caras"]) == 2
    assert len(datos["capas"]) == 2
    # Nada escrito del lado del servidor
    assert not scenes_dir.exists() or list(scenes_dir.glob("*.json")) == []


async def test_el_archivo_lleva_la_instalacion_entera(cliente):
    client, _, _ = cliente
    await _instalacion(client)

    datos = await _descargar(client)

    assert {c["nombre"] for c in datos["caras"]} == {"frontal", "lateral"}
    # Por nombre y no por id: los ids no significan nada en otro equipo
    assert {c["cara"] for c in datos["capas"]} == {"frontal", "lateral"}
    assert all("surface_id" not in c for c in datos["capas"])
    assert "calibracion" in datos and "efecto_global" in datos


# --- ida y vuelta ---------------------------------------------------------


async def test_guardar_y_abrir_devuelve_la_misma_instalacion(cliente):
    """Exportar, destruir, importar, y comprobar que quedo igual."""
    client, _, _ = cliente
    await _instalacion(client)
    archivo = await _descargar(client)

    for cara in (await client.get("/api/surfaces")).json():
        await client.delete(f"/api/surfaces/{cara['id']}")
    assert (await client.get("/api/surfaces")).json() == []

    respuesta = await _abrir(client, archivo)

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


# --- deshacer, que es lo que hace que abrir no de miedo ------------------


async def test_abrir_se_puede_deshacer(cliente):
    """Abrir pisa la calibracion. Equivocarse de archivo no deberia costar
    veinte minutos de volver a ajustar esquinas."""
    client, _, _ = cliente
    await _instalacion(client)
    otra = {
        "ecomap": 1,
        "nombre": "otra cosa",
        "caras": [
            {
                "nombre": "unica",
                "mesh_cols": 1,
                "mesh_rows": 1,
                "points": [[0, 0], [1, 0], [0, 1], [1, 1]],
            }
        ],
        "capas": [],
    }

    informe = (await _abrir(client, otra)).json()
    assert informe["puede_deshacer"] is True
    assert [c["name"] for c in (await client.get("/api/surfaces")).json()] == ["unica"]

    respuesta = await client.post("/api/scene/undo")

    assert respuesta.status_code == 200
    caras = {c["name"]: c for c in (await client.get("/api/surfaces")).json()}
    assert set(caras) == {"frontal", "lateral"}
    assert caras["frontal"]["points"][0] == pytest.approx([0.17, 0.23])


async def test_deshacer_sin_nada_que_deshacer_se_rechaza(cliente):
    client, _, _ = cliente

    respuesta = await client.post("/api/scene/undo")

    assert respuesta.status_code == 422
    assert "nada que deshacer" in respuesta.text


async def test_los_respaldos_no_crecen_sin_limite(cliente, monkeypatch):
    """Son una red, no un historial: en una SD, uno por apertura la llena."""
    monkeypatch.setattr(service, "MAX_RESPALDOS", 3)
    client, _, scenes_dir = cliente
    await _instalacion(client)
    archivo = await _descargar(client)

    for _ in range(6):
        await _abrir(client, archivo)

    assert len(list(scenes_dir.glob("respaldo-*.json"))) <= 3


# --- archivos que no cuadran ---------------------------------------------


async def test_una_capa_cuyo_efecto_no_existe_se_omite_y_se_reporta(cliente):
    """Mover una instalacion a un equipo donde falta un efecto no deberia
    rechazar el archivo entero."""
    client, _, _ = cliente
    await _instalacion(client)
    archivo = await _descargar(client)
    archivo["capas"].append({"cara": "frontal", "efecto": "no-instalado", "blend": "normal"})
    archivo["capas"].append({"cara": "no-existe", "efecto": "plasma", "blend": "normal"})

    informe = (await _abrir(client, archivo)).json()

    assert informe["capas"] == 2
    assert len(informe["omitidas"]) == 2
    assert any("no-instalado" in m for m in informe["omitidas"])
    assert any("no-existe" in m for m in informe["omitidas"])


async def test_un_archivo_de_otro_formato_se_rechaza(cliente):
    client, _, _ = cliente

    respuesta = await _abrir(client, {"ecomap": 99, "caras": [], "capas": []})

    assert respuesta.status_code == 422
    assert "formato" in respuesta.text


async def test_algo_que_no_es_json_se_rechaza(cliente):
    client, _, _ = cliente

    respuesta = await client.post(
        "/api/scene/file",
        files={"archivo": ("x.json", b"\x00\x01binario", "application/json")},
    )

    assert respuesta.status_code == 422


async def test_una_malla_incompleta_se_rechaza_antes_de_tocar_la_base(cliente):
    """Un archivo con puntos de menos dejaria una superficie que el render no
    puede triangular. Mejor rechazarlo que escribirlo."""
    client, _, _ = cliente
    await _instalacion(client)
    archivo = await _descargar(client)
    archivo["caras"][0]["points"] = [[0, 0], [1, 0]]  # faltan dos

    respuesta = await _abrir(client, archivo)

    assert respuesta.status_code == 422
    assert len((await client.get("/api/surfaces")).json()) == 2, "la instalacion sigue en pie"


# --- rescate de lo que guardo una version anterior -----------------------


async def test_las_escenas_viejas_del_equipo_se_pueden_bajar(cliente):
    """Existio un panel que las guardaba del lado del servidor. Las que
    quedaron no se tiran: se pueden bajar una vez y despues la linea
    desaparece sola. No es un historial."""
    client, _, scenes_dir = cliente
    scenes_dir.mkdir(parents=True, exist_ok=True)
    (scenes_dir / "vieja.json").write_text(
        json.dumps({"ecomap": 1, "nombre": "vieja", "caras": [], "capas": []}),
        encoding="utf-8",
    )

    listado = (await client.get("/api/scene/legacy")).json()["snapshots"]
    assert [s["nombre"] for s in listado] == ["vieja"]

    bajada = await client.get("/api/scene/legacy/vieja.json")
    assert bajada.status_code == 200
    assert json.loads(bajada.text)["nombre"] == "vieja"


async def test_los_respaldos_no_se_ofrecen_como_escenas_viejas(cliente):
    """Son una red para deshacer, no documentos que elegir. Mezclarlos
    traeria de vuelta justo el ruido que se saco."""
    client, _, _ = cliente
    await _instalacion(client)
    await _abrir(client, await _descargar(client))  # deja un respaldo

    listado = (await client.get("/api/scene/legacy")).json()["snapshots"]

    assert listado == []


async def test_el_dashboard_ya_no_tiene_panel_de_escenas_guardadas(cliente):
    """Un historial al lado del documento abierto compite con el: deja de
    estar claro sobre cual se esta trabajando."""
    client, _, _ = cliente

    html = (await client.get("/")).text

    assert "Escenas guardadas" not in html
    # Lo que queda es el documento abierto, con su nombre
    assert 'class="barra-escena"' in html
    assert "nombreEscena" in html
