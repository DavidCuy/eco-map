"""API de efectos.

El catálogo son archivos del volumen de efectos; el web los **lee**, el render
los **compila**. Mismo reparto que con las cámaras: quien puede fallar de verdad
es quien ejecuta, así que el error de compilación llega por el bus y no lo
inventa la UI.

Acá está lo mínimo de US-10: listar y elegir el efecto activo. El espejo en
SQLite, el marcado de `available` y la UI de parámetros autogenerada son el
Hito 2 (#11, #12).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from ecomap_core.effects import discover
from ecomap_core.protocol import OP_EFFECT, op
from ecomap_core.schemas import EffectActive, EffectOut, EffectSelect
from ecomap_web.db import log_event, set_setting
from ecomap_web.deps import BusDep, DbDep, SettingsDep, StateDep
from ecomap_web.routers.pages import render_fragment

router = APIRouter(prefix="/api/effects", tags=["effects"])


def catalogo(effects_dir) -> list[EffectOut]:
    efectos, errores = discover(effects_dir)
    salida = [
        EffectOut(
            id=e.manifest.id,
            name=e.manifest.name,
            version=e.manifest.version,
            tags=e.manifest.tags,
            needs_camera=e.manifest.needs_camera,
            cost=e.manifest.cost,
            params=[p.model_dump() for p in e.manifest.params],  # type: ignore[misc]
        )
        for e in efectos
    ]
    # Los directorios rotos se muestran igual, marcados: esconderlos haría que
    # un efecto que "desapareció" parezca que nunca existió.
    for mensaje in errores:
        nombre = mensaje.split(":")[0].strip()
        salida.append(
            EffectOut(id=nombre, name=nombre, version="?", available=False, error=mensaje)
        )
    return salida


@router.get("", response_model=list[EffectOut])
def listar(settings: SettingsDep) -> list[EffectOut]:
    return catalogo(settings.effects_dir)


@router.post("/active", response_model=EffectActive)
async def activar(
    payload: EffectSelect,
    request: Request,
    bus: BusDep,
    state: StateDep,
    db: DbDep,
    settings: SettingsDep,
) -> Response | EffectActive:
    disponibles = {e.id: e for e in catalogo(settings.effects_dir)}
    elegido = disponibles.get(payload.id)
    if elegido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"efecto {payload.id!r} no existe")
    if not elegido.available:
        raise HTTPException(422, elegido.error or f"el efecto {payload.id!r} no se puede usar")

    state.effect = payload.id
    state.effect_params = payload.params
    state.effect_error = None

    entregado = await bus.send(op(OP_EFFECT, id=payload.id, params=payload.params))
    set_setting(db, "active_effect", payload.id)
    if not entregado:
        log_event(db, "warn", "web", "efecto guardado pero el render no estaba conectado")

    if request.headers.get("HX-Request"):
        return render_fragment(
            request,
            "partials/controls.html",
            {"status": _status(request, bus, state), "effects": list(disponibles.values())},
        )
    return EffectActive(id=payload.id, params=payload.params)


def _status(request: Request, bus, state):
    from ecomap_web.deps import build_status

    return build_status(bus, state, request.app.state.version)
