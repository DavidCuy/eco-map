"""Reglas de negocio de las superficies.

Una superficie por cada cara fisica del objeto, y toda superficie es una malla
(ADR-015). Toda mutacion pasa por aca: ningun router habla con el repositorio
directo, y despues de cada cambio se empuja la escena al render.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ecomap_core.geometry import (
    GeometryError,
    Mesh,
    default_mesh,
    resample,
    validate_mesh,
    validate_subdivision,
)
from ecomap_web.bus import BusClient
from ecomap_web.db import get_setting, set_setting
from ecomap_web.repo import surfaces as repo


class InvalidOrder(ValueError):
    """El reordenamiento no coincide con las caras que existen."""


class SurfaceNotFound(LookupError):
    pass


def kind_for(cols: int, rows: int) -> str:
    """`kind` es derivado, no una eleccion del usuario: 1x1 es un quad, el resto
    es malla. Se guarda igual para poder consultarlo y mostrarlo."""
    return "quad" if cols == 1 and rows == 1 else "mesh"


def listar(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return repo.listar(conn)


def obtener(conn: sqlite3.Connection, surface_id: int) -> dict[str, Any]:
    superficie = repo.obtener(conn, surface_id)
    if superficie is None:
        raise SurfaceNotFound(surface_id)
    return superficie


def crear(
    conn: sqlite3.Connection, name: str, mesh_cols: int = 1, mesh_rows: int = 1
) -> dict[str, Any]:
    validate_subdivision(mesh_cols, mesh_rows)
    puntos = default_mesh(mesh_cols, mesh_rows)
    surface_id = repo.crear(
        conn, name, kind_for(mesh_cols, mesh_rows), mesh_cols, mesh_rows, puntos
    )
    _bump_calibration(conn)
    return obtener(conn, surface_id)


def actualizar(conn: sqlite3.Connection, surface_id: int, campos: dict[str, Any]) -> dict[str, Any]:
    obtener(conn, surface_id)  # 404 si no existe
    permitidos = {k: v for k, v in campos.items() if v is not None}
    if "enabled" in permitidos:
        permitidos["enabled"] = int(bool(permitidos["enabled"]))
    repo.actualizar(conn, surface_id, permitidos)
    return obtener(conn, surface_id)


def guardar_puntos(conn: sqlite3.Connection, surface_id: int, points: Mesh) -> dict[str, Any]:
    superficie = obtener(conn, surface_id)
    cols, rows = superficie["mesh_cols"], superficie["mesh_rows"]
    validate_mesh(points, cols, rows)  # lanza GeometryError si no calza
    repo.guardar_malla(conn, surface_id, points, cols, rows, kind_for(cols, rows))
    _bump_calibration(conn)
    return obtener(conn, surface_id)


def subdividir(conn: sqlite3.Connection, surface_id: int, cols: int, rows: int) -> dict[str, Any]:
    """Cambia la subdivision conservando la forma.

    Subir la resolucion refina sin deformar: los puntos nuevos salen de
    interpolar la malla actual. Bajarla descarta ajustes finos, y por eso la UI
    tiene que avisar antes.
    """
    superficie = obtener(conn, surface_id)
    nuevos = resample(
        superficie["points"], superficie["mesh_cols"], superficie["mesh_rows"], cols, rows
    )
    repo.guardar_malla(conn, surface_id, nuevos, cols, rows, kind_for(cols, rows))
    _bump_calibration(conn)
    return obtener(conn, surface_id)


def resetear(conn: sqlite3.Connection, surface_id: int) -> dict[str, Any]:
    """Vuelve a la malla regular a pantalla completa, conservando la subdivision."""
    superficie = obtener(conn, surface_id)
    cols, rows = superficie["mesh_cols"], superficie["mesh_rows"]
    repo.guardar_malla(conn, surface_id, default_mesh(cols, rows), cols, rows, kind_for(cols, rows))
    _bump_calibration(conn)
    return obtener(conn, surface_id)


def reordenar(conn: sqlite3.Connection, surface_ids: list[int]) -> list[dict[str, Any]]:
    """Cambia el orden de la tira de caras.

    No toca el render: el apilado lo decide el z_order de las capas. Esto es
    navegacion — con el canvas mostrando una cara por vez, poder ordenarlas
    como estan fisicamente es la diferencia entre buscar y señalar.
    """
    actuales = {s["id"] for s in listar(conn)}
    if set(surface_ids) != actuales:
        raise InvalidOrder(
            "el reordenamiento tiene que incluir exactamente las caras que existen"
        )
    repo.reordenar(conn, surface_ids)
    return listar(conn)


def borrar(conn: sqlite3.Connection, surface_id: int) -> None:
    if not repo.borrar(conn, surface_id):
        raise SurfaceNotFound(surface_id)
    _bump_calibration(conn)


# --- escena hacia el render ---------------------------------------------


def serializar_escena(conn: sqlite3.Connection) -> dict[str, Any]:
    """La escena tal como la necesita el render.

    Solo lo que afecta al dibujo: el render no sabe de nombres ni de fechas. Las
    capas y los efectos por superficie llegan con el Hito 2; por ahora cada
    superficie dibuja lo que el render tenga activo.
    """
    return {
        "calibration_version": int(get_setting(conn, "calibration_version", "1") or 1),
        "surfaces": [
            {
                "id": s["id"],
                "cols": s["mesh_cols"],
                "rows": s["mesh_rows"],
                "points": s["points"],
                "opacity": s["opacity"],
            }
            for s in repo.listar(conn)
            if s["enabled"]
        ],
    }


async def push_escena(bus: BusClient, conn: sqlite3.Connection) -> bool:
    """Empuja la escena al render tras un cambio de calibracion.

    Delega en el servicio de escenas: desde US-13 lo que el render dibuja son
    capas, y una superficie sola no significa nada para el. False si el render
    no esta conectado; al reconectar se reenvia completa.
    """
    from ecomap_web.services import scenes as scene_service

    return await scene_service.push(bus, conn)


def _bump_calibration(conn: sqlite3.Connection) -> None:
    """Invalida las cachés de geometria del render."""
    actual = int(get_setting(conn, "calibration_version", "1") or 1)
    set_setting(conn, "calibration_version", str(actual + 1))


__all__ = [
    "GeometryError",
    "SurfaceNotFound",
    "actualizar",
    "borrar",
    "crear",
    "guardar_puntos",
    "listar",
    "obtener",
    "push_escena",
    "resetear",
    "serializar_escena",
    "subdividir",
]
