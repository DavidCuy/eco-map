"""Catalogo de efectos: espejo en SQLite de lo que hay en disco.

La fuente de verdad son los archivos (ADR-011). El espejo existe para dos cosas
que los archivos no dan: integridad referencial con `layer`, y poder marcar un
efecto como no disponible **sin perder la fila** que las capas referencian.

Quien compila es el render, no el web, asi que el estado real de un efecto tiene
dos partes:

- `available` en la DB: el manifiesto es valido y el directorio existe.
- el reporte del render por el bus: el shader compila con **este** driver.

Un efecto puede estar perfecto en disco y no compilar en la Pi. Por eso la UI
muestra las dos cosas.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from ecomap_core.effects import Effect, discover
from ecomap_web.db import log_event

log = logging.getLogger(__name__)


def sincronizar(conn: sqlite3.Connection, effects_dir: Path) -> dict[str, Any]:
    """Escanea el disco y actualiza el espejo. Devuelve un resumen.

    Los efectos que ya no estan en disco quedan `available = 0`; **no se
    borran**, porque hay capas que los referencian y perder la fila romperia
    la escena en vez de degradarla.
    """
    efectos, errores = discover(effects_dir)
    vistos: set[str] = set()

    for efecto in efectos:
        _guardar(conn, efecto)
        vistos.add(efecto.id)

    for mensaje in errores:
        nombre = mensaje.split(":")[0].strip()
        log.warning("catalogo: %s", mensaje)
        log_event(conn, "warn", "effects", mensaje)
        _marcar_no_disponible(conn, nombre)

    faltantes = _marcar_faltantes(conn, vistos)
    if faltantes:
        log_event(
            conn,
            "warn",
            "effects",
            f"efectos ya no estan en disco: {', '.join(faltantes)}",
        )

    return {
        "cargados": sorted(vistos),
        "errores": errores,
        "faltantes": faltantes,
    }


def _guardar(conn: sqlite3.Connection, efecto: Effect) -> None:
    manifiesto = efecto.manifest
    conn.execute(
        "INSERT INTO effect (id, name, version, manifest, needs_camera, cost, available) "
        "VALUES (?, ?, ?, ?, ?, ?, 1) "
        "ON CONFLICT(id) DO UPDATE SET "
        "  name = excluded.name, version = excluded.version, "
        "  manifest = excluded.manifest, needs_camera = excluded.needs_camera, "
        "  cost = excluded.cost, available = 1",
        (
            manifiesto.id,
            manifiesto.name,
            manifiesto.version,
            manifiesto.model_dump_json(),
            int(manifiesto.needs_camera),
            manifiesto.cost,
        ),
    )


def _marcar_no_disponible(conn: sqlite3.Connection, effect_id: str) -> None:
    conn.execute("UPDATE effect SET available = 0 WHERE id = ?", (effect_id,))


def _marcar_faltantes(conn: sqlite3.Connection, vistos: set[str]) -> list[str]:
    filas = conn.execute("SELECT id FROM effect WHERE available = 1").fetchall()
    faltantes = [f["id"] for f in filas if f["id"] not in vistos]
    for effect_id in faltantes:
        _marcar_no_disponible(conn, effect_id)
    return faltantes


def olvidar(conn: sqlite3.Connection, effect_id: str) -> bool:
    """Saca el efecto del espejo si ninguna capa lo usa.

    Al borrar el directorio, el efecto quedaria para siempre en el catalogo
    como "no disponible" (ADR-011: no se borran porque hay capas que los
    referencian). Eso es correcto **mientras alguna capa lo use**; si no lo
    usa nadie, es basura que se acumula cada vez que se prueba y se descarta
    un efecto subido.

    Devuelve si lo saco.
    """
    usos = conn.execute(
        "SELECT COUNT(*) AS n FROM layer WHERE effect_id = ?", (effect_id,)
    ).fetchone()["n"]
    if usos:
        return False
    conn.execute("DELETE FROM effect WHERE id = ?", (effect_id,))
    conn.commit()
    return True


def fuente_de(conn: sqlite3.Connection, effect_id: str) -> str | None:
    """De que clase de archivo salio, segun el espejo.

    Se mira el espejo y no el disco a proposito: un efecto subido cuyo
    directorio ya no esta tiene que poder borrarse del catalogo igual.
    """
    fila = conn.execute("SELECT manifest FROM effect WHERE id = ?", (effect_id,)).fetchone()
    if fila is None:
        return None
    try:
        return (json.loads(fila["manifest"]).get("source") or {}).get("kind")
    except json.JSONDecodeError:
        return None


def listar(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Catalogo desde el espejo, con el manifiesto ya parseado."""
    filas = conn.execute(
        "SELECT id, name, version, manifest, needs_camera, cost, available "
        "FROM effect ORDER BY available DESC, id"
    ).fetchall()
    salida = []
    for fila in filas:
        manifiesto = json.loads(fila["manifest"])
        salida.append(
            {
                "id": fila["id"],
                "name": fila["name"],
                "version": fila["version"],
                "tags": manifiesto.get("tags", []),
                "needs_camera": bool(fila["needs_camera"]),
                # Sale del manifiesto y no de una columna: es un detalle de
                # como se dibuja, no algo por lo que se vaya a consultar.
                "needs_feedback": bool(manifiesto.get("needs_feedback")),
                "cost": fila["cost"],
                "params": manifiesto.get("params", []),
                "available": bool(fila["available"]),
                # Que clase de archivo lo genero, si es que lo genero uno.
                # Es lo que distingue un efecto subido de uno que vino con el
                # sistema, y por tanto si se puede borrar desde la web.
                "source_kind": (manifiesto.get("source") or {}).get("kind"),
            }
        )
    return salida


def obtener(conn: sqlite3.Connection, effect_id: str) -> dict[str, Any] | None:
    for efecto in listar(conn):
        if efecto["id"] == effect_id:
            return efecto
    return None
