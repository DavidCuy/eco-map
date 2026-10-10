"""API de escenas guardadas como archivos.

Guardar y abrir, con la semantica de un documento. Lo que se esta tocando es
siempre la escena actual y se autoguarda sola en la base; estos endpoints son
para quedarse con una copia con nombre y volver a ella.

Abrir **reemplaza la instalacion entera**, calibracion incluida, y por eso
siempre deja antes un respaldo automatico.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from ecomap_core.protocol import OP_SCENE, op
from ecomap_core.schemas import SnapshotSave
from ecomap_web.deps import BusDep, DbDep, SettingsDep
from ecomap_web.routers.pages import render_fragment
from ecomap_web.services import scenes as scene_service
from ecomap_web.services import snapshots as service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])

HTTP_422 = 422
MAX_SUBIDA = 2 * 1024 * 1024  # un JSON de escena son unos pocos KB


def _fragmento_o_json(request: Request, db, settings, cuerpo: dict) -> Response:
    if request.headers.get("HX-Request"):
        return render_fragment(
            request,
            "partials/snapshots.html",
            {
                "snapshots": service.listar_archivos(settings.scenes_dir),
                "scene": scene_service.listar(db)[0] if scene_service.listar(db) else None,
                "aviso": cuerpo.get("aviso"),
            },
        )
    return JSONResponse(cuerpo)


async def _empujar_escena(bus, db) -> None:
    """Avisa al render que la geometria cambio.

    Abrir una escena cambia caras y capas de golpe; sin esto el render seguiria
    proyectando la instalacion anterior hasta el proximo cambio suelto.
    """
    await bus.send(op(OP_SCENE, **scene_service.serializar(db)))


@router.get("")
def listar(request: Request, db: DbDep, settings: SettingsDep) -> Response:
    """Las escenas guardadas, de la mas reciente a la mas vieja."""
    return _fragmento_o_json(
        request, db, settings, {"snapshots": service.listar_archivos(settings.scenes_dir)}
    )


@router.post("")
def guardar(
    payload: SnapshotSave, request: Request, db: DbDep, settings: SettingsDep
) -> Response:
    """Guarda la instalacion actual con un nombre."""
    try:
        guardada = service.guardar(db, settings.scenes_dir, payload.name)
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    return _fragmento_o_json(
        request, db, settings, {**guardada, "aviso": f"Guardada como «{payload.name}»"}
    )


@router.post("/{archivo}/open")
async def abrir(
    archivo: str, request: Request, db: DbDep, settings: SettingsDep, bus: BusDep
) -> Response:
    """Carga una escena guardada encima de la instalacion actual.

    Reemplaza caras, capas y calibracion. Deja un respaldo automatico de lo que
    habia: recalibrar cuesta veinte minutos y nadie se acuerda de respaldar
    antes de probar algo.
    """
    try:
        informe = service.abrir(db, settings.scenes_dir, archivo)
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    await _empujar_escena(bus, db)

    aviso = f"Abierta «{informe['nombre']}»: {informe['caras']} caras, {informe['capas']} capas"
    if informe["omitidas"]:
        aviso += f". {len(informe['omitidas'])} capas omitidas: " + "; ".join(
            informe["omitidas"][:3]
        )
    return _fragmento_o_json(request, db, settings, {**informe, "aviso": aviso})


@router.delete("/{archivo}")
def borrar(archivo: str, request: Request, db: DbDep, settings: SettingsDep) -> Response:
    try:
        service.borrar(settings.scenes_dir, archivo)
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    return _fragmento_o_json(request, db, settings, {"aviso": f"Borrada {archivo}"})


@router.get("/{archivo}/download")
def descargar(archivo: str, settings: SettingsDep) -> Response:
    """El JSON tal cual, para respaldarlo fuera del equipo o moverlo a otro."""
    try:
        datos = service.leer(settings.scenes_dir, archivo)
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    return Response(
        content=json.dumps(datos, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{archivo}"'},
    )


@router.post("/upload")
async def subir(
    archivo: UploadFile, request: Request, db: DbDep, settings: SettingsDep
) -> Response:
    """Sube un JSON de escena sin abrirlo.

    Separado de abrir a proposito: subir y aplicar en un solo paso haria que un
    archivo equivocado pisara la calibracion antes de que nadie lo mire.
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

    nombre = datos.get("nombre") or (archivo.filename or "escena").removesuffix(".json")
    settings.scenes_dir.mkdir(parents=True, exist_ok=True)
    try:
        ruta = service._ruta(settings.scenes_dir, nombre)  # noqa: SLF001
    except service.SnapshotError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    datos["nombre"] = nombre
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")

    return _fragmento_o_json(
        request,
        db,
        settings,
        {"archivo": ruta.name, "aviso": f"Subida «{nombre}». Abrila para aplicarla."},
    )
