"""La escena actual, como archivo.

Guardar baja un JSON a la computadora de quien lo usa; abrir sube uno y lo
aplica. No hay escenas guardadas en el equipo ni lista que navegar: el
documento abierto es el que esta en la base, y se autoguarda solo.

Lo unico que vive en el servidor son los **respaldos automaticos** que se
toman justo antes de abrir. No se listan ni se ofrecen como historial: son lo
que hace que «deshacer» exista, porque abrir reemplaza la calibracion y eso
cuesta veinte minutos de ajustar esquinas.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse

from ecomap_core.protocol import OP_SCENE, op
from ecomap_web.deps import BusDep, DbDep, SettingsDep
from ecomap_web.services import scenes as scene_service
from ecomap_web.services import snapshots as service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scene", tags=["scene"])

HTTP_422 = 422
MAX_SUBIDA = 2 * 1024 * 1024  # un JSON de escena son unos pocos KB


async def _empujar(bus, db) -> None:
    """Avisa al render que la geometria cambio de golpe.

    Sin esto el render seguiria proyectando la instalacion anterior hasta el
    proximo cambio suelto.
    """
    await bus.send(op(OP_SCENE, **scene_service.serializar(db)))


def _nombre_actual(db) -> str:
    escenas = scene_service.listar(db)
    activa = next((e for e in escenas if e["is_active"]), None)
    return (activa or {}).get("name") or "escena"


@router.get("/file")
def descargar(db: DbDep) -> Response:
    """La instalacion actual como archivo, para guardarla donde se quiera.

    Va como descarga y no se escribe en el equipo: el archivo es de quien lo
    usa. Lleva caras con su malla, capas, calibracion y efecto global.
    """
    nombre = _nombre_actual(db)
    datos = service.exportar(db, nombre)
    archivo = service.nombre_de_archivo(nombre)
    return Response(
        content=json.dumps(datos, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{archivo}"'},
    )


@router.post("/file")
async def abrir(
    archivo: UploadFile, db: DbDep, bus: BusDep, settings: SettingsDep
) -> JSONResponse:
    """Aplica un archivo de escena subido desde la computadora.

    Reemplaza caras, capas y calibracion. Antes se guarda un respaldo
    automatico de lo que habia, que es lo que permite deshacer.
    """
    crudo = await archivo.read(MAX_SUBIDA + 1)
    if len(crudo) > MAX_SUBIDA:
        raise HTTPException(HTTP_422, "el archivo es demasiado grande para ser una escena")
    try:
        datos = service.validar(json.loads(crudo.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(HTTP_422, f"no es un JSON valido: {exc}") from exc
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    settings.scenes_dir.mkdir(parents=True, exist_ok=True)
    respaldo = service.respaldar(db, settings.scenes_dir)
    informe = service.importar(db, datos)
    await _empujar(bus, db)

    nombre = datos.get("nombre") or (archivo.filename or "escena").removesuffix(".json")
    log.info("escena abierta: %s (%s caras, %s capas)", nombre, informe["caras"], informe["capas"])
    return JSONResponse({**informe, "nombre": nombre, "puede_deshacer": bool(respaldo)})


@router.post("/undo")
async def deshacer(db: DbDep, bus: BusDep, settings: SettingsDep) -> JSONResponse:
    """Vuelve al estado anterior a la ultima apertura.

    Es deshacer, no navegar un historial: solo el ultimo. Abrir reemplaza la
    calibracion, y equivocarse de archivo no deberia costar veinte minutos de
    volver a ajustar esquinas.
    """
    nombre = service.ultimo_respaldo(settings.scenes_dir)
    if nombre is None:
        raise HTTPException(HTTP_422, "no hay nada que deshacer")
    try:
        datos = service.leer(settings.scenes_dir, nombre)
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    informe = service.importar(db, datos)
    await _empujar(bus, db)
    return JSONResponse({**informe, "nombre": "estado anterior"})


@router.get("/legacy")
def guardadas_en_el_equipo(settings: SettingsDep) -> JSONResponse:
    """Escenas que quedaron guardadas en el equipo de una version anterior.

    Existio un panel que las guardaba del lado del servidor. Ya no, pero las
    que estaban no se tiran: se listan una sola vez para poder bajarlas, y
    cuando no queda ninguna la linea desaparece sola. No es un historial.
    """
    guardadas = [
        s
        for s in service.listar_archivos(settings.scenes_dir)
        if not s.get("respaldo") and not s.get("roto")
    ]
    return JSONResponse({"snapshots": guardadas})


@router.get("/legacy/{nombre}")
def bajar_legacy(nombre: str, settings: SettingsDep) -> Response:
    try:
        datos = service.leer(settings.scenes_dir, nombre)
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    return Response(
        content=json.dumps(datos, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
