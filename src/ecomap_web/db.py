"""Conexion a SQLite con los pragmas de ADR-004.

Solo el proceso web abre la base. El render nunca la toca: recibe el estado por
el bus. Las escrituras son cortas y se hacen desde el threadpool de FastAPI.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA busy_timeout = 5000",
)


def connect(path: Path) -> sqlite3.Connection:
    """Abre la base creando el directorio si hace falta y aplica los pragmas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaccion explicita: con isolation_level=None hay que abrirla a mano."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO setting (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def log_event(conn: sqlite3.Connection, level: str, source: str, message: str) -> None:
    """Deja rastro en event_log y lo poda para que no crezca sin limite."""
    conn.execute(
        "INSERT INTO event_log (level, source, message) VALUES (?, ?, ?)",
        (level, source, message),
    )
    conn.execute("DELETE FROM event_log WHERE id <= (SELECT MAX(id) - 5000 FROM event_log)")
