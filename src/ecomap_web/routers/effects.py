"""API de efectos.

El catálogo son archivos del volumen; el web los **lee y espeja en SQLite**, el
render los **compila**. Un efecto puede estar perfecto en disco y no compilar en
el driver de la Pi, así que el estado que muestra la UI junta las dos fuentes:
`available` del espejo y el reporte de compilación del render.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from ecomap_core.effects import PREVIEW_NAME, EffectManifest, resolve_params
from ecomap_core.protocol import OP_EFFECT, OP_EFFECTS_RELOAD, op
from ecomap_core.schemas import EffectActive, EffectOut, EffectSelect, ParamsIn
from ecomap_web.db import log_event, set_setting
from ecomap_web.deps import BusDep, DbDep, SettingsDep, StateDep, WriterDep, build_status
from ecomap_web.routers.pages import render_fragment
from ecomap_web.services import effects as service
from ecomap_web.services import media_effects as media_service

router = APIRouter(prefix="/api/effects", tags=["effects"])

# 422 y no 400: es un problema de forma del contenido. Se usa el numero porque
# Starlette le cambio el nombre a la constante.
HTTP_422 = 422


def catalogo(db, state) -> list[EffectOut]:
    """Catálogo del espejo, cruzado con lo que el render pudo compilar."""
    return [
        EffectOut(
            **datos,
            error=state.effect_errors.get(datos["id"]),
            # Si el render todavía no reportó nada, se confía en el espejo:
            # mentir hacia "disponible" es peor que esperar el reporte.
            compiled=datos["id"] not in state.effect_errors,
        )
        for datos in service.listar(db)
    ]


def valores_efectivos(efecto: dict | None, overrides: dict) -> dict:
    """Defaults del manifiesto más los overrides guardados."""
    if efecto is None:
        return {}
    manifiesto = EffectManifest.model_validate(
        {
            "id": efecto["id"],
            "name": efecto["name"],
            "version": efecto["version"],
            "params": efecto["params"],
        }
    )
    return resolve_params(manifiesto, overrides)


@router.get("", response_model=list[EffectOut])
def listar(db: DbDep, state: StateDep) -> list[EffectOut]:
    return catalogo(db, state)


@router.post("/reload", response_model=list[EffectOut])
async def recargar(
    request: Request, db: DbDep, bus: BusDep, state: StateDep, settings: SettingsDep
) -> Response | list[EffectOut]:
    """Re-escanea el disco y le pide al render que recompile."""
    resumen = service.sincronizar(db, settings.effects_dir)
    await bus.send(op(OP_EFFECTS_RELOAD))
    log_event(
        db,
        "info",
        "effects",
        f"catalogo recargado: {len(resumen['cargados'])} efectos, "
        f"{len(resumen['errores'])} con error",
    )
    if request.headers.get("HX-Request"):
        return render_fragment(request, "partials/catalog.html", {"effects": catalogo(db, state)})
    return catalogo(db, state)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def subir(
    request: Request,
    db: DbDep,
    bus: BusDep,
    state: StateDep,
    settings: SettingsDep,
    archivo: UploadFile,
    nombre: str = Form(...),
    speed: float = Form(0.1),
    angle: float = Form(0.0),
) -> Response:
    """Crea un efecto a partir de una imagen, un gif o un video corto.

    Termina siendo un efecto como cualquier otro —directorio con manifiesto,
    shader y preview— asi que desde aca en adelante el catalogo, las capas y
    las escenas lo tratan igual que a uno escrito a mano.
    """
    crudo = await archivo.read(media_service.MAX_BYTES + 1)
    if len(crudo) > media_service.MAX_BYTES:
        raise HTTPException(
            HTTP_422,
            f"el archivo pasa de {media_service.MAX_BYTES // (1024 * 1024)} MB. "
            "Esto proyecta bucles cortos, no reproduce peliculas.",
        )

    # A disco antes de validarlo: OpenCV abre rutas, no buffers, y escribir un
    # temporal es mas barato que mantener una copia en memoria del render.
    with tempfile.NamedTemporaryFile(
        suffix=Path(archivo.filename or "").suffix, delete=False
    ) as temporal:
        temporal.write(crudo)
        ruta_temporal = Path(temporal.name)

    try:
        manifiesto = media_service.crear(
            settings.effects_dir,
            nombre,
            ruta_temporal,
            archivo.filename or "",
            defaults={"speed": speed, "angle": angle},
        )
    except media_service.MediaEffectError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    finally:
        ruta_temporal.unlink(missing_ok=True)

    await _resincronizar(db, bus, state, settings)
    return JSONResponse({"effect": manifiesto}, status_code=status.HTTP_201_CREATED)


@router.delete("/{effect_id}/upload", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_subido(
    effect_id: str, db: DbDep, bus: BusDep, state: StateDep, settings: SettingsDep
) -> Response:
    """Borra un efecto subido. Los que vienen con el sistema no se tocan.

    Las capas que lo usaban **no se borran**: quedan marcadas como no
    disponibles, igual que si el archivo hubiera desaparecido del volumen. Es
    el mismo camino que ya existia, y borrar capas de escenas guardadas por
    quitar un efecto seria una sorpresa desagradable.
    """
    try:
        media_service.borrar(settings.effects_dir, effect_id)
    except media_service.MediaEffectError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    await _resincronizar(db, bus, state, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _resincronizar(db, bus, state, settings) -> None:
    """Espeja el catalogo en SQLite y le dice al render que recargue.

    Las dos cosas: el web necesita el espejo para ofrecerlo en los selectores
    y el render necesita compilar el shader nuevo y cargar su archivo. Sin lo
    segundo, el efecto aparece en la lista y proyecta negro.
    """
    service.sincronizar(db, settings.effects_dir)
    await bus.send(op(OP_EFFECTS_RELOAD))


@router.get("/{effect_id}/media")
def media(effect_id: str, settings: SettingsDep) -> FileResponse:
    """El archivo original del efecto, para previsualizarlo en el navegador.

    El preview del catalogo es una imagen fija; para ver como se mueve un gif
    o un video hace falta el archivo de verdad.
    """
    directorio = settings.effects_dir / effect_id
    try:
        manifiesto = json.loads((directorio / "effect.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sin archivo") from exc
    fuente = manifiesto.get("source") or {}
    ruta = directorio / str(fuente.get("file", ""))
    if not fuente or not ruta.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "este efecto no tiene archivo")
    return FileResponse(ruta)


@router.get("/{effect_id}/preview")
def preview(effect_id: str, settings: SettingsDep) -> FileResponse:
    """Sirve el preview desde el volumen de efectos.

    No va como estático porque el catálogo vive en un volumen aparte, que se
    puede reemplazar entero sin tocar la imagen.
    """
    base = settings.effects_dir.resolve()
    ruta: Path = (base / effect_id / PREVIEW_NAME).resolve()
    # El id viene de la URL: se comprueba que no se escape del volumen con "..".
    if not ruta.is_relative_to(base):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "id invalido")
    if not ruta.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sin preview")
    return FileResponse(ruta, media_type="image/jpeg")


@router.post("/active", response_model=EffectActive)
async def activar(
    payload: EffectSelect,
    request: Request,
    bus: BusDep,
    state: StateDep,
    db: DbDep,
    writer: WriterDep,
) -> Response | EffectActive:
    elegido = service.obtener(db, payload.id)
    if elegido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"efecto {payload.id!r} no existe")
    if not elegido["available"]:
        raise HTTPException(HTTP_422, f"el efecto {payload.id!r} no esta disponible")

    state.effect = payload.id
    state.effect_params = payload.params
    state.effect_error = None
    await _aplicar(bus, db, state, writer)
    return _respuesta(request, db, state)


@router.put("/active/params", response_model=EffectActive)
async def actualizar_params(
    payload: ParamsIn,
    request: Request,
    bus: BusDep,
    state: StateDep,
    db: DbDep,
    writer: WriterDep,
) -> Response | EffectActive:
    """Mezcla parcial: lo que no viene, no se toca.

    Solo se guardan los overrides sobre el default del manifiesto (ADR-011): si
    el efecto agrega un parámetro en una versión nueva, se hereda solo.
    """
    if state.effect is None:
        raise HTTPException(HTTP_422, "no hay efecto activo")
    state.effect_params = {**state.effect_params, **payload.params}
    await _aplicar(bus, db, state, writer)
    return _respuesta(request, db, state)


@router.post("/active/reset", response_model=EffectActive)
async def resetear_params(
    request: Request, bus: BusDep, state: StateDep, db: DbDep, writer: WriterDep
) -> Response | EffectActive:
    """Vuelve a los valores por defecto: se **descartan los overrides**, no se
    copian los defaults. Así el efecto sigue heredando si cambia de versión."""
    if state.effect is None:
        raise HTTPException(HTTP_422, "no hay efecto activo")
    state.effect_params = {}
    await _aplicar(bus, db, state, writer)
    return _respuesta(request, db, state)


async def _aplicar(bus, db, state, writer) -> None:
    """El valor viaja **siempre** por el socket; el disco espera.

    Es lo que se ve contra lo que se desgasta: en medio de un arrastre, lo
    unico que importa es que el render lo aplique (ADR-004).
    """
    efecto = state.effect or ""
    params = json.dumps(state.effect_params)
    entregado = await bus.send(op(OP_EFFECT, id=state.effect, params=state.effect_params))

    writer.schedule("active_effect", lambda: set_setting(db, "active_effect", efecto))
    writer.schedule("active_effect_params", lambda: set_setting(db, "active_effect_params", params))

    if not entregado:
        log_event(db, "warn", "web", "efecto guardado pero el render no estaba conectado")


def contexto_controles(request: Request, db, state) -> dict:
    """Todo lo que `partials/controls.html` necesita para renderizarse entero.

    Vive aca y no en cada endpoint porque la plantilla se intercambia desde
    tres lugares distintos (efecto activo, parametros y blackout) y cada uno
    armaba su propio diccionario. Al que le faltaba `effects`, el `{% for %}`
    no iteraba nada y devolvia **un select vacio con HTTP 200**: sin error, sin
    log, y el desplegable de efectos quedaba en blanco hasta recargar la
    pagina. Un solo constructor hace que eso no se pueda repetir.
    """
    efecto = service.obtener(db, state.effect) if state.effect else None
    return {
        "status": build_status(request.app.state.bus, state, request.app.state.version),
        "effects": catalogo(db, state),
        "active_effect": efecto,
        "values": valores_efectivos(efecto, state.effect_params),
    }


def _respuesta(request: Request, db, state) -> Response | EffectActive:
    if request.headers.get("HX-Request"):
        return render_fragment(
            request, "partials/controls.html", contexto_controles(request, db, state)
        )
    return EffectActive(id=state.effect or "", params=state.effect_params)
