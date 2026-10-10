"""API de escenas y capas.

Una capa es efecto + superficie; una escena es un conjunto de capas activable
de un golpe. Toda mutación empuja la escena al render.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse

from ecomap_core.schemas import (
    LayerCreate,
    LayerOut,
    LayerUpdate,
    ReorderIn,
    SceneCreate,
    SceneOut,
    SceneUpdate,
)
from ecomap_web.deps import BusDep, DbDep, StateDep
from ecomap_web.routers.pages import render_fragment
from ecomap_web.services import scenes as service
from ecomap_web.services import surfaces as surface_service

router = APIRouter(tags=["scenes"])

HTTP_422 = 422


def panel(request: Request, db, state) -> Response:
    """Fragmento con el panel entero.

    Se devuelve completo y no solo la parte tocada: mover una capa cambia el
    orden de las demas, borrar una escena cambia cual esta activa. Reconstruir
    el panel es mas barato que coordinar varios intercambios parciales.
    """
    from ecomap_web.routers.effects import catalogo

    return render_fragment(
        request,
        "partials/scenes.html",
        {
            "scenes": service.listar(db),
            "surfaces": surface_service.listar(db),
            "effects": catalogo(db, state),
        },
    )


def _no_encontrada(scene_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"escena {scene_id} inexistente")


def _capa_no_encontrada(layer_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"capa {layer_id} inexistente")


# --- escenas -------------------------------------------------------------


@router.get("/api/scenes", response_model=list[SceneOut])
def listar(db: DbDep) -> list[dict]:
    return service.listar(db)


@router.get("/api/scenes/panel", response_class=HTMLResponse)
def panel_actual(request: Request, db: DbDep, state: StateDep) -> Response:
    """El panel de capas, sin tocar nada.

    Sirve para volver a pintar lo que el servidor cree que hay. Lo usa el
    reordenamiento por arrastre cuando el servidor rechaza un orden: la lista
    ya se movio en pantalla, y dejarla asi seria mostrar algo que no es.
    """
    return panel(request, db, state)


@router.post("/api/scenes", response_model=SceneOut, status_code=status.HTTP_201_CREATED)
async def crear(
    payload: SceneCreate, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> dict | Response:
    escena = service.crear(db, payload.name)
    await service.push(bus, db)
    return _salida(request, db, state, escena)


@router.get("/api/scenes/{scene_id}", response_model=SceneOut)
def obtener(scene_id: int, db: DbDep) -> dict:
    try:
        return service.obtener(db, scene_id)
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc


@router.patch("/api/scenes/{scene_id}", response_model=SceneOut)
def renombrar(scene_id: int, payload: SceneUpdate, db: DbDep) -> dict:
    if payload.name is None:
        return obtener(scene_id, db)
    try:
        return service.renombrar(db, scene_id, payload.name)
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc


@router.post("/api/scenes/{scene_id}/activate", response_model=SceneOut)
async def activar(
    scene_id: int, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> dict | Response:
    try:
        escena = service.activar(db, scene_id)
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc
    await service.push(bus, db)
    return _salida(request, db, state, escena)


@router.post("/api/scenes/{scene_id}/default", response_model=SceneOut)
def marcar_default(scene_id: int, request: Request, db: DbDep, state: StateDep) -> dict | Response:
    """La escena de arranque. No cambia lo que se proyecta ahora."""
    try:
        return _salida(request, db, state, service.marcar_default(db, scene_id))
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc


@router.post("/api/scenes/{scene_id}/duplicate", response_model=SceneOut, status_code=201)
def duplicar(scene_id: int, request: Request, db: DbDep, state: StateDep) -> dict | Response:
    try:
        return _salida(request, db, state, service.duplicar(db, scene_id))
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc


@router.delete("/api/scenes/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(
    scene_id: int, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> Response:
    try:
        service.borrar(db, scene_id)
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc
    await service.push(bus, db)
    if request.headers.get("HX-Request"):
        return panel(request, db, state)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- capas ---------------------------------------------------------------


@router.post(
    "/api/scenes/{scene_id}/layers", response_model=LayerOut, status_code=status.HTTP_201_CREATED
)
async def crear_capa(
    scene_id: int, payload: LayerCreate, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> dict | Response:
    try:
        capa = service.crear_capa(
            db, scene_id, payload.surface_id, payload.effect_id, payload.blend_mode, payload.params
        )
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc
    except service.TooManyLayers as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    except service.InvalidLayer as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    await service.push(bus, db)
    return _salida(request, db, state, capa)


@router.patch("/api/layers/{layer_id}", response_model=LayerOut)
async def actualizar_capa(
    layer_id: int, payload: LayerUpdate, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> dict | Response:
    try:
        capa = service.actualizar_capa(db, layer_id, payload.model_dump())
    except service.LayerNotFound as exc:
        raise _capa_no_encontrada(layer_id) from exc
    await service.push(bus, db)
    return _salida(request, db, state, capa)


@router.delete("/api/layers/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_capa(
    layer_id: int, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> Response:
    try:
        service.borrar_capa(db, layer_id)
    except service.LayerNotFound as exc:
        raise _capa_no_encontrada(layer_id) from exc
    await service.push(bus, db)
    if request.headers.get("HX-Request"):
        return panel(request, db, state)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/layers/{layer_id}/move", response_model=SceneOut)
async def mover_capa(
    layer_id: int, direction: str, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> dict | Response:
    """Sube o baja una capa un lugar. `direction` es `up` o `down`."""
    if direction not in ("up", "down"):
        raise HTTPException(HTTP_422, "direction tiene que ser up o down")
    try:
        escena = service.mover_capa(db, layer_id, direction)
    except service.LayerNotFound as exc:
        raise _capa_no_encontrada(layer_id) from exc
    await service.push(bus, db)
    return _salida(request, db, state, escena)


@router.put("/api/scenes/{scene_id}/layers/order", response_model=SceneOut)
async def reordenar(
    scene_id: int, payload: ReorderIn, request: Request, db: DbDep, bus: BusDep, state: StateDep
) -> dict | Response:
    try:
        escena = service.reordenar(db, scene_id, payload.layer_ids)
    except service.SceneNotFound as exc:
        raise _no_encontrada(scene_id) from exc
    except service.InvalidLayer as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc
    await service.push(bus, db)
    return _salida(request, db, state, escena)


def _salida(request: Request, db, state, datos: dict) -> dict | Response:
    """JSON para la API, panel completo para HTMX."""
    if request.headers.get("HX-Request"):
        return panel(request, db, state)
    return datos
