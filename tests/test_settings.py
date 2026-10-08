"""Nombres de las variables de entorno.

El caso que motiva estos tests: ECOMAP_EFFECTS aparece en los tres compose y en
el Dockerfile desde el Hito 0, pero el nombre que pydantic deriva del campo
`effects_dir` es ECOMAP_EFFECTS_DIR. Dentro del contenedor la variable corta
coincidia con el default, asi que no hacia falta que funcionara; fuera del
contenedor el default /effects apunta a la raiz del disco en Windows y el
catalogo no carga. Se aceptan las dos formas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ecomap_core.settings import Settings


@pytest.fixture(autouse=True)
def sin_env_heredado(monkeypatch, tmp_path):
    """Aisla del .env del repo y de las ECOMAP_ que tenga la maquina."""
    for nombre in list(__import__("os").environ):
        if nombre.startswith("ECOMAP_"):
            monkeypatch.delenv(nombre, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize(
    ("variable", "campo"),
    [
        ("ECOMAP_EFFECTS_DIR", "effects_dir"),
        ("ECOMAP_EFFECTS", "effects_dir"),
        ("ECOMAP_MEDIA_DIR", "media_dir"),
        ("ECOMAP_MEDIA", "media_dir"),
        ("ECOMAP_MIGRATIONS_DIR", "migrations_dir"),
        ("ECOMAP_MIGRATIONS", "migrations_dir"),
    ],
)
def test_las_dos_formas_del_nombre_funcionan(monkeypatch, variable, campo):
    monkeypatch.setenv(variable, "ruta/elegida")

    assert getattr(Settings(), campo) == Path("ruta/elegida")


def test_la_forma_explicita_gana_sobre_la_corta(monkeypatch):
    """Si alguien tiene las dos puestas, manda la que nombra el campo."""
    monkeypatch.setenv("ECOMAP_EFFECTS_DIR", "explicita")
    monkeypatch.setenv("ECOMAP_EFFECTS", "corta")

    assert Settings().effects_dir == Path("explicita")


def test_se_puede_construir_por_nombre_de_campo(tmp_path):
    """Los tests arman Settings a mano; validation_alias no debe estorbarlo."""
    settings = Settings(effects_dir=tmp_path, media_dir=tmp_path, migrations_dir=tmp_path)

    assert settings.effects_dir == tmp_path
