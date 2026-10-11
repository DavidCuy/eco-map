"""API de superficies.

Una superficie por cada cara física (ADR-015). Toda mutación empuja la escena
al render: la persistencia y el tiempo real son dos caminos distintos, y acá se
disparan los dos.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from ecomap_core.geometry import GeometryError
from ecomap_core.schemas import (
    PointsIn,
    SubdivideIn,
    SurfaceCreate,
    SurfaceOut,
    SurfaceReorder,
    SurfaceUpdate,
)
from ecomap_web.deps import BusDep, DbDep
from ecomap_web.services import surfaces as service

router = APIRouter(prefix="/api/surfaces", tags=["surfaces"])


def _no_encontrada(surface_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"superficie {surface_id} inexistente")


# 422 y no 400: es un problema de forma del contenido, igual que lo que devuelve
# Pydantic cuando el cuerpo no valida. Se usa el numero y no la constante porque
# Starlette le cambio el nombre (UNPROCESSABLE_ENTITY -> UNPROCESSABLE_CONTENT).
HTTP_422 = 422


def _geometria_invalida(exc: GeometryError) -> HTTPException:
    return HTTPException(HTTP_422, str(exc))


@router.get("", response_model=list[SurfaceOut])
def listar(db: DbDep) -> list[dict]:
    return service.listar(db)


@router.post("", response_model=SurfaceOut, status_code=status.HTTP_201_CREATED)
async def crear(payload: SurfaceCreate, db: DbDep, bus: BusDep) -> dict:
    try:
        superficie = service.crear(db, payload.name, payload.mesh_cols, payload.mesh_rows)
    except GeometryError as exc:
        raise _geometria_invalida(exc) from exc
    await service.push_escena(bus, db)
    return superficie


@router.put("/order", response_model=list[SurfaceOut])
def reordenar(payload: SurfaceReorder, db: DbDep) -> list[dict]:
    """Cambia el orden de la tira de caras.

    No avisa al render: el orden de las caras es navegacion del dashboard, y
    lo que se proyecta no cambia. Mandar la escena entera por esto seria hacer
    trabajar al render para nada.
    """
    try:
        return service.reordenar(db, payload.surface_ids)
    except service.InvalidOrder as exc:
        # 422 por numero: Starlette le cambio el nombre a la constante, y el
        # resto de los routers ya lo escribe asi.
        raise HTTPException(422, str(exc)) from exc


@router.get("/{surface_id}", response_model=SurfaceOut)
def obtener(surface_id: int, db: DbDep) -> dict:
    try:
        return service.obtener(db, surface_id)
    except service.SurfaceNotFound as exc:
        raise _no_encontrada(surface_id) from exc


@router.patch("/{surface_id}", response_model=SurfaceOut)
async def actualizar(surface_id: int, payload: SurfaceUpdate, db: DbDep, bus: BusDep) -> dict:
    try:
        superficie = service.actualizar(db, surface_id, payload.model_dump())
    except service.SurfaceNotFound as exc:
        raise _no_encontrada(surface_id) from exc
    await service.push_escena(bus, db)
    return superficie


@router.put("/{surface_id}/points", response_model=SurfaceOut)
async def guardar_puntos(surface_id: int, payload: PointsIn, db: DbDep, bus: BusDep) -> dict:
    try:
        superficie = service.guardar_puntos(db, surface_id, payload.points)
    except service.SurfaceNotFound as exc:
        raise _no_encontrada(surface_id) from exc
    except GeometryError as exc:
        raise _geometria_invalida(exc) from exc
    await service.push_escena(bus, db)
    return superficie


@router.post("/{surface_id}/subdivide", response_model=SurfaceOut)
async def subdividir(surface_id: int, payload: SubdivideIn, db: DbDep, bus: BusDep) -> dict:
    try:
        superficie = service.subdividir(db, surface_id, payload.cols, payload.rows)
    except service.SurfaceNotFound as exc:
        raise _no_encontrada(surface_id) from exc
    except GeometryError as exc:
        raise _geometria_invalida(exc) from exc
    await service.push_escena(bus, db)
    return superficie


@router.post("/{surface_id}/reset", response_model=SurfaceOut)
async def resetear(surface_id: int, db: DbDep, bus: BusDep) -> dict:
    try:
        superficie = service.resetear(db, surface_id)
    except service.SurfaceNotFound as exc:
        raise _no_encontrada(surface_id) from exc
    await service.push_escena(bus, db)
    return superficie


@router.delete("/{surface_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(surface_id: int, db: DbDep, bus: BusDep) -> Response:
    try:
        service.borrar(db, surface_id)
    except service.SurfaceNotFound as exc:
        raise _no_encontrada(surface_id) from exc
    await service.push_escena(bus, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
