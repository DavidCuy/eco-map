"""Acceso a la tabla `surface`.

SQL y nada mas: las reglas viven en `services/surfaces.py`. Los puntos van como
JSON en una columna porque siempre se leen y escriben enteros (ADR-011).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ecomap_core.geometry import Mesh

COLUMNAS = (
    "id, name, kind, mesh_cols, mesh_rows, points, mask, opacity, enabled, created_at, updated_at"
)


def _fila_a_dict(fila: sqlite3.Row) -> dict[str, Any]:
    datos = dict(fila)
    datos["points"] = [tuple(p) for p in json.loads(datos["points"])]
    datos["mask"] = json.loads(datos["mask"]) if datos["mask"] else None
    datos["enabled"] = bool(datos["enabled"])
    return datos


def listar(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    filas = conn.execute(f"SELECT {COLUMNAS} FROM surface ORDER BY id").fetchall()
    return [_fila_a_dict(f) for f in filas]


def obtener(conn: sqlite3.Connection, surface_id: int) -> dict[str, Any] | None:
    fila = conn.execute(f"SELECT {COLUMNAS} FROM surface WHERE id = ?", (surface_id,)).fetchone()
    return _fila_a_dict(fila) if fila else None


def crear(
    conn: sqlite3.Connection,
    name: str,
    kind: str,
    mesh_cols: int,
    mesh_rows: int,
    points: Mesh,
) -> int:
    cursor = conn.execute(
        "INSERT INTO surface (name, kind, mesh_cols, mesh_rows, points) VALUES (?, ?, ?, ?, ?)",
        (name, kind, mesh_cols, mesh_rows, json.dumps(points)),
    )
    return int(cursor.lastrowid)


def actualizar(conn: sqlite3.Connection, surface_id: int, campos: dict[str, Any]) -> None:
    if not campos:
        return
    asignaciones = ", ".join(f"{clave} = ?" for clave in campos)
    valores = list(campos.values())
    conn.execute(
        f"UPDATE surface SET {asignaciones}, updated_at = datetime('now') WHERE id = ?",
        (*valores, surface_id),
    )


def guardar_malla(
    conn: sqlite3.Connection,
    surface_id: int,
    points: Mesh,
    mesh_cols: int,
    mesh_rows: int,
    kind: str,
) -> None:
    conn.execute(
        "UPDATE surface SET points = ?, mesh_cols = ?, mesh_rows = ?, kind = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (json.dumps(points), mesh_cols, mesh_rows, kind, surface_id),
    )


def borrar(conn: sqlite3.Connection, surface_id: int) -> bool:
    cursor = conn.execute("DELETE FROM surface WHERE id = ?", (surface_id,))
    return cursor.rowcount > 0
