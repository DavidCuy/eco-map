"""Acceso a las tablas `scene` y `layer`.

SQL y nada mas: las reglas viven en `services/scenes.py`.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

LAYER_COLUMNAS = """
    l.id, l.scene_id, l.surface_id, l.effect_id, l.z_order, l.blend_mode,
    l.params, l.enabled,
    s.name AS surface_name,
    COALESCE(e.name, l.effect_id) AS effect_name,
    COALESCE(e.available, 0) AS effect_available
"""


def _layer(fila: sqlite3.Row) -> dict[str, Any]:
    datos = dict(fila)
    datos["params"] = json.loads(datos["params"])
    datos["enabled"] = bool(datos["enabled"])
    datos["effect_available"] = bool(datos["effect_available"])
    return datos


# --- escenas -------------------------------------------------------------


def listar(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    filas = conn.execute("SELECT id, name, is_default FROM scene ORDER BY id").fetchall()
    return [{**dict(f), "is_default": bool(f["is_default"])} for f in filas]


def obtener(conn: sqlite3.Connection, scene_id: int) -> dict[str, Any] | None:
    fila = conn.execute(
        "SELECT id, name, is_default FROM scene WHERE id = ?", (scene_id,)
    ).fetchone()
    if fila is None:
        return None
    return {**dict(fila), "is_default": bool(fila["is_default"])}


def crear(conn: sqlite3.Connection, name: str) -> int:
    cursor = conn.execute("INSERT INTO scene (name) VALUES (?)", (name,))
    return int(cursor.lastrowid)


def renombrar(conn: sqlite3.Connection, scene_id: int, name: str) -> None:
    conn.execute(
        "UPDATE scene SET name = ?, updated_at = datetime('now') WHERE id = ?",
        (name, scene_id),
    )


def borrar(conn: sqlite3.Connection, scene_id: int) -> bool:
    return conn.execute("DELETE FROM scene WHERE id = ?", (scene_id,)).rowcount > 0


def marcar_default(conn: sqlite3.Connection, scene_id: int) -> None:
    """Solo una escena puede ser la de arranque."""
    conn.execute("UPDATE scene SET is_default = 0")
    conn.execute("UPDATE scene SET is_default = 1 WHERE id = ?", (scene_id,))


def escena_default(conn: sqlite3.Connection) -> int | None:
    fila = conn.execute("SELECT id FROM scene WHERE is_default = 1").fetchone()
    return int(fila["id"]) if fila else None


# --- capas ---------------------------------------------------------------


def listar_capas(conn: sqlite3.Connection, scene_id: int) -> list[dict[str, Any]]:
    filas = conn.execute(
        f"SELECT {LAYER_COLUMNAS} FROM layer l "
        "JOIN surface s ON s.id = l.surface_id "
        "LEFT JOIN effect e ON e.id = l.effect_id "
        "WHERE l.scene_id = ? ORDER BY l.z_order, l.id",
        (scene_id,),
    ).fetchall()
    return [_layer(f) for f in filas]


def obtener_capa(conn: sqlite3.Connection, layer_id: int) -> dict[str, Any] | None:
    fila = conn.execute(
        f"SELECT {LAYER_COLUMNAS} FROM layer l "
        "JOIN surface s ON s.id = l.surface_id "
        "LEFT JOIN effect e ON e.id = l.effect_id "
        "WHERE l.id = ?",
        (layer_id,),
    ).fetchone()
    return _layer(fila) if fila else None


def contar_capas(conn: sqlite3.Connection, scene_id: int) -> int:
    fila = conn.execute(
        "SELECT COUNT(*) AS n FROM layer WHERE scene_id = ?", (scene_id,)
    ).fetchone()
    return int(fila["n"])


def proximo_z(conn: sqlite3.Connection, scene_id: int) -> int:
    fila = conn.execute(
        "SELECT COALESCE(MAX(z_order), -1) + 1 AS z FROM layer WHERE scene_id = ?",
        (scene_id,),
    ).fetchone()
    return int(fila["z"])


def crear_capa(
    conn: sqlite3.Connection,
    scene_id: int,
    surface_id: int,
    effect_id: str,
    z_order: int,
    blend_mode: str,
    params: dict[str, Any],
) -> int:
    cursor = conn.execute(
        "INSERT INTO layer (scene_id, surface_id, effect_id, z_order, blend_mode, params) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (scene_id, surface_id, effect_id, z_order, blend_mode, json.dumps(params)),
    )
    return int(cursor.lastrowid)


def actualizar_capa(conn: sqlite3.Connection, layer_id: int, campos: dict[str, Any]) -> None:
    if not campos:
        return
    if "params" in campos:
        campos = {**campos, "params": json.dumps(campos["params"])}
    asignaciones = ", ".join(f"{clave} = ?" for clave in campos)
    conn.execute(f"UPDATE layer SET {asignaciones} WHERE id = ?", (*campos.values(), layer_id))


def borrar_capa(conn: sqlite3.Connection, layer_id: int) -> bool:
    return conn.execute("DELETE FROM layer WHERE id = ?", (layer_id,)).rowcount > 0


def reordenar(conn: sqlite3.Connection, scene_id: int, layer_ids: list[int]) -> None:
    for z, layer_id in enumerate(layer_ids):
        conn.execute(
            "UPDATE layer SET z_order = ? WHERE id = ? AND scene_id = ?",
            (z, layer_id, scene_id),
        )


def duplicar_capas(conn: sqlite3.Connection, origen: int, destino: int) -> None:
    conn.execute(
        "INSERT INTO layer (scene_id, surface_id, effect_id, z_order, blend_mode, params, enabled) "
        "SELECT ?, surface_id, effect_id, z_order, blend_mode, params, enabled "
        "FROM layer WHERE scene_id = ?",
        (destino, origen),
    )
