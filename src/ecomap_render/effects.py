"""Catalogo de efectos en el render: compila y mantiene los programas GLSL.

El catalogo completo con espejo en SQLite y validacion en la UI es el Hito 2
(#11). Aca esta lo minimo para que los efectos vivan en archivos y no en el
codigo: descubrir, compilar, y poder cambiar de efecto en vivo.

Un shader que no compila **no tumba el render**: se reporta y se sigue con el
anterior, o con negro si no habia ninguno.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import moderngl

from ecomap_core.effects import Effect, build_fragment, color_to_rgb, discover, resolve_params

log = logging.getLogger(__name__)

# Triangulo unico que cubre la pantalla: mas barato que dos triangulos de quad.
_VERTEX = """
out vec2 v_uv;
void main() {
    vec2 pos = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = pos;
    gl_Position = vec4(pos * 2.0 - 1.0, 0.0, 1.0);
}
"""


class CompiledEffect:
    def __init__(
        self, effect: Effect, program: moderngl.Program, vao: moderngl.VertexArray
    ) -> None:
        self.effect = effect
        self.program = program
        self.vao = vao

    @property
    def id(self) -> str:
        return self.effect.id

    def apply_params(self, overrides: dict[str, Any] | None) -> None:
        valores = resolve_params(self.effect.manifest, overrides)
        for param in self.effect.manifest.params:
            miembro = self.program.get(param.uniform_name(), None)
            if miembro is None:
                continue  # el compilador lo elimino por no usarse
            valor = valores.get(param.key, param.default)
            if param.type == "color":
                miembro.value = color_to_rgb(valor)  # type: ignore[union-attr]
            elif param.type == "bool":
                miembro.value = bool(valor)  # type: ignore[union-attr]
            elif param.type == "enum":
                miembro.value = int(valor)  # type: ignore[union-attr]
            else:
                miembro.value = float(valor)  # type: ignore[union-attr]

    def set_common(self, **uniforms: Any) -> None:
        for nombre, valor in uniforms.items():
            miembro = self.program.get(nombre, None)
            if miembro is not None:
                miembro.value = valor  # type: ignore[union-attr]

    def render(self) -> None:
        self.vao.render(moderngl.TRIANGLES, vertices=3)

    def release(self) -> None:
        self.vao.release()
        self.program.release()


class EffectLibrary:
    """Efectos compilados, por id."""

    def __init__(self, ctx: moderngl.Context, effects_dir: Path, header: str) -> None:
        self.ctx = ctx
        self.effects_dir = effects_dir
        self.header = header
        self.compiled: dict[str, CompiledEffect] = {}
        self.errors: dict[str, str] = {}

    def reload(self) -> None:
        """Re-escanea el directorio y recompila. Los errores quedan guardados
        para que el web los pueda mostrar."""
        for compilado in self.compiled.values():
            compilado.release()
        self.compiled.clear()
        self.errors.clear()

        efectos, errores_descubrimiento = discover(self.effects_dir)
        for mensaje in errores_descubrimiento:
            log.warning("efectos: %s", mensaje)
            self.errors[mensaje.split(":")[0]] = mensaje

        for efecto in efectos:
            try:
                programa = self.ctx.program(
                    vertex_shader=self.header + _VERTEX,
                    fragment_shader=build_fragment(efecto, self.header),
                )
            except Exception as exc:  # moderngl.Error: el shader no compila
                log.error("efecto %s no compila: %s", efecto.id, exc)
                self.errors[efecto.id] = str(exc)
                continue
            vao = self.ctx.vertex_array(programa, [])
            self.compiled[efecto.id] = CompiledEffect(efecto, programa, vao)

        log.info(
            "efectos: %d cargados (%s), %d con error",
            len(self.compiled),
            ", ".join(sorted(self.compiled)) or "ninguno",
            len(self.errors),
        )

    def get(self, effect_id: str) -> CompiledEffect | None:
        return self.compiled.get(effect_id)

    def release(self) -> None:
        for compilado in self.compiled.values():
            compilado.release()
        self.compiled.clear()
