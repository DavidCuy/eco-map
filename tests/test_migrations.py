from pathlib import Path

from ecomap_core.settings import Settings
from ecomap_web import migrate
from ecomap_web.db import connect, get_setting, log_event, set_setting

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"

TABLAS_ESPERADAS = {
    "surface",
    "effect",
    "scene",
    "layer",
    "calibration",
    "setting",
    "event_log",
    "schema_version",
}


def _settings(tmp_path: Path) -> Settings:
    return Settings(db=tmp_path / "ecomap.db", migrations_dir=MIGRATIONS)


def test_migraciones_crean_el_esquema(tmp_path: Path):
    aplicadas = migrate.run(_settings(tmp_path))
    assert aplicadas == [1]

    conn = connect(tmp_path / "ecomap.db")
    tablas = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert TABLAS_ESPERADAS <= tablas


def test_migraciones_son_idempotentes(tmp_path: Path):
    settings = _settings(tmp_path)
    assert migrate.run(settings) == [1]
    assert migrate.run(settings) == []  # segunda corrida: nada que hacer


def test_pragmas_aplicados(tmp_path: Path):
    migrate.run(_settings(tmp_path))
    conn = connect(tmp_path / "ecomap.db")

    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_foreign_keys_en_cascada(tmp_path: Path):
    migrate.run(_settings(tmp_path))
    conn = connect(tmp_path / "ecomap.db")
    conn.execute("INSERT INTO surface (id, name, points) VALUES (1, 's', '[]')")
    conn.execute(
        "INSERT INTO effect (id, name, version, manifest) VALUES ('solid', 'Solid', '1', '{}')"
    )
    conn.execute("INSERT INTO scene (id, name) VALUES (1, 'principal')")
    conn.execute("INSERT INTO layer (scene_id, surface_id, effect_id) VALUES (1, 1, 'solid')")

    conn.execute("DELETE FROM scene WHERE id = 1")

    assert conn.execute("SELECT COUNT(*) FROM layer").fetchone()[0] == 0


def test_settings_semilla_y_escritura(tmp_path: Path):
    migrate.run(_settings(tmp_path))
    conn = connect(tmp_path / "ecomap.db")

    assert get_setting(conn, "blackout") == "0"
    set_setting(conn, "blackout", "1")
    assert get_setting(conn, "blackout") == "1"


def test_event_log_se_poda(tmp_path: Path):
    migrate.run(_settings(tmp_path))
    conn = connect(tmp_path / "ecomap.db")
    for i in range(5050):
        log_event(conn, "info", "test", f"linea {i}")

    total = conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
    assert total <= 5001
