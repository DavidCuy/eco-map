"""Runner de migraciones: aplica migrations/NNN_*.sql en orden, una sola vez.

Sin Alembic a proposito (ADR-004). Idempotente: ejecutarlo dos veces no hace nada
la segunda. Corre al arrancar el web, y tambien a mano:

    uv run python -m ecomap_web.migrate
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from ecomap_core.settings import Settings, load_settings
from ecomap_web.db import connect

log = logging.getLogger(__name__)

MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")


def discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    """Devuelve (version, archivo) ordenado por version."""
    found: list[tuple[int, Path]] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        match = MIGRATION_RE.match(path.name)
        if not match:
            log.warning("migracion ignorada por nombre: %s", path.name)
            continue
        found.append((int(match.group(1)), path))
    found.sort(key=lambda item: item[0])
    duplicates = {v for v, _ in found if [x for x, _ in found].count(v) > 1}
    if duplicates:
        raise RuntimeError(f"versiones de migracion duplicadas: {sorted(duplicates)}")
    return found


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version    INTEGER PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    return {row["version"] for row in conn.execute("SELECT version FROM schema_version")}


def apply_all(conn: sqlite3.Connection, migrations_dir: Path) -> list[int]:
    """Aplica lo que falte. Devuelve las versiones aplicadas en esta corrida."""
    done = applied_versions(conn)
    applied: list[int] = []
    for version, path in discover(migrations_dir):
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        log.info("aplicando migracion %03d (%s)", version, path.name)
        # executescript hace COMMIT implicito, asi que la version se marca justo despues.
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        applied.append(version)
    return applied


def run(settings: Settings | None = None) -> list[int]:
    settings = settings or load_settings()
    conn = connect(settings.db)
    try:
        return apply_all(conn, settings.migrations_dir)
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    applied = run()
    if applied:
        print(f"migraciones aplicadas: {applied}")
    else:
        print("base al dia, nada que aplicar")


if __name__ == "__main__":
    main()
