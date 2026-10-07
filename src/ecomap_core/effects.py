"""Manifiestos de efectos y armado del shader.

Un efecto es un directorio con `effect.json` y `frag.glsl` (Modulo-Efectos). El
archivo GLSL **no** es un fragment shader completo: aporta la funcion

    vec3 effect(vec2 uv)

y el loader la envuelve con el header de version, los uniforms comunes y los
parametros declarados en el manifiesto. Asi un efecto nuevo no tiene que
acordarse de declarar nada ni de que version de GLSL corre debajo, que cambia
entre la Pi, la mini PC y el modo headless.

Este modulo es puro: parsea, valida y arma texto. No toca OpenGL ni SQLite, por
eso lo pueden usar los dos procesos.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger(__name__)

MANIFEST_NAME = "effect.json"
FRAGMENT_NAME = "frag.glsl"
PREVIEW_NAME = "preview.jpg"

ParamType = Literal["float", "color", "bool", "enum"]

# Prefijo de los uniforms de parametros, para que no choquen con los comunes.
PARAM_PREFIX = "p_"


class EffectParam(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    label: str
    type: ParamType = "float"
    min: float = 0.0
    max: float = 1.0
    default: Any = 0.0
    # Paso del control. Si no se declara, la UI usa un centesimo del rango.
    # Importa cuando el parametro es conceptualmente entero: "40.08 celdas" no
    # significa nada.
    step: float | None = Field(default=None, gt=0)
    options: list[str] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def _enum_tiene_opciones(cls, v: list[str], info: Any) -> list[str]:
        if info.data.get("type") == "enum" and not v:
            raise ValueError("un parametro enum necesita opciones")
        return v

    def glsl_type(self) -> str:
        return {"float": "float", "color": "vec3", "bool": "bool", "enum": "int"}[self.type]

    def uniform_name(self) -> str:
        return f"{PARAM_PREFIX}{self.key}"


class EffectManifest(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    name: str
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    needs_camera: bool = False
    cost: Literal["low", "medium", "high"] = "low"
    params: list[EffectParam] = Field(default_factory=list)

    def defaults(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params}


class Effect(BaseModel):
    """Manifiesto mas lo que hay en disco."""

    manifest: EffectManifest
    directory: Path
    fragment: str
    has_preview: bool = False

    @property
    def id(self) -> str:
        return self.manifest.id


class EffectError(RuntimeError):
    """El efecto no se pudo cargar."""


def load_effect(directory: Path) -> Effect:
    """Lee un directorio de efecto. Lanza EffectError si no sirve."""
    manifest_path = directory / MANIFEST_NAME
    fragment_path = directory / FRAGMENT_NAME
    try:
        datos = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EffectError(f"{directory.name}: falta {MANIFEST_NAME}") from exc
    except json.JSONDecodeError as exc:
        raise EffectError(f"{directory.name}: {MANIFEST_NAME} no es JSON valido ({exc})") from exc

    try:
        manifest = EffectManifest.model_validate(datos)
    except ValidationError as exc:
        raise EffectError(
            f"{directory.name}: manifiesto invalido ({exc.error_count()} errores)"
        ) from exc

    if manifest.id != directory.name:
        raise EffectError(
            f"{directory.name}: el id del manifiesto ({manifest.id}) no coincide con el directorio"
        )

    try:
        fragment = fragment_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EffectError(f"{directory.name}: falta {FRAGMENT_NAME}") from exc

    if "vec3 effect(" not in fragment:
        raise EffectError(f"{directory.name}: {FRAGMENT_NAME} debe definir `vec3 effect(vec2 uv)`")

    return Effect(
        manifest=manifest,
        directory=directory,
        fragment=fragment,
        has_preview=(directory / PREVIEW_NAME).is_file(),
    )


def discover(effects_dir: Path) -> tuple[list[Effect], list[str]]:
    """Escanea el directorio. Devuelve (efectos validos, errores).

    Un efecto roto no impide cargar los demas: se reporta y se sigue.
    """
    efectos: list[Effect] = []
    errores: list[str] = []
    try:
        candidatos = sorted(p for p in effects_dir.iterdir() if p.is_dir())
    except OSError as exc:
        return [], [f"no se pudo leer {effects_dir}: {exc}"]

    for directorio in candidatos:
        if not (directorio / MANIFEST_NAME).exists():
            continue  # no pretende ser un efecto
        try:
            efectos.append(load_effect(directorio))
        except EffectError as exc:
            errores.append(str(exc))
    return efectos, errores


# --- armado del shader ---------------------------------------------------

_COMMON_UNIFORMS = """
in vec2 v_uv;
out vec4 f_color;

uniform float u_time;
uniform vec2  u_resolution;
uniform float u_beat;
uniform float u_motion;
uniform vec2  u_motion_pos;
uniform sampler2D u_cam;
"""

_MAIN = """
void main() {
    f_color = vec4(effect(v_uv), 1.0);
}
"""


def build_fragment(effect: Effect, header: str) -> str:
    """Arma el fragment shader completo: header + uniforms + efecto + main."""
    declaraciones = "\n".join(
        f"uniform {p.glsl_type()} {p.uniform_name()};" for p in effect.manifest.params
    )
    return "\n".join([header, _COMMON_UNIFORMS, declaraciones, effect.fragment, _MAIN])


def resolve_params(manifest: EffectManifest, overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Mezcla los overrides sobre los valores por defecto del manifiesto.

    Solo se guardan los overrides (ADR-011): si el efecto agrega un parametro en
    una version nueva, las capas existentes lo heredan sin migracion.
    """
    valores = manifest.defaults()
    for clave, valor in (overrides or {}).items():
        if clave in valores:
            valores[clave] = valor
    return valores


def color_to_rgb(valor: Any) -> tuple[float, float, float]:
    """`#rrggbb` a tres floats 0..1. Un color invalido cae a negro en vez de
    romper el frame."""
    if isinstance(valor, (list, tuple)) and len(valor) == 3:
        return tuple(float(c) for c in valor)  # type: ignore[return-value]
    texto = str(valor).lstrip("#")
    if len(texto) != 6:
        return (0.0, 0.0, 0.0)
    try:
        return tuple(int(texto[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0.0, 0.0, 0.0)
