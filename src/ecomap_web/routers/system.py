"""API de sistema: estado, blackout y patron de prueba.

Convencion de doble representacion: si viene la cabecera HX-Request se devuelve
un fragmento HTML listo para intercambiar; si no, JSON. Un solo router, dos
representaciones (Modulo-Web-API).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ecomap_core.protocol import OP_BLACKOUT, op
from ecomap_core.schemas import BlackoutRequest, SystemStatus
from ecomap_web.db import log_event, set_setting
from ecomap_web.deps import BusDep, DbDep, StateDep, build_status
from ecomap_web.routers.pages import render_fragment

router = APIRouter(prefix="/api/system", tags=["system"])


def _status(request: Request, bus: BusDep, state: StateDep) -> SystemStatus:
    return build_status(bus, state, request.app.state.version)


@router.get("/status", response_model=SystemStatus)
def get_status(request: Request, bus: BusDep, state: StateDep) -> Response | SystemStatus:
    status = _status(request, bus, state)
    if request.headers.get("HX-Request"):
        return render_fragment(request, "partials/status.html", {"status": status})
    return status


@router.post("/blackout", response_model=SystemStatus)
async def set_blackout(
    payload: BlackoutRequest,
    request: Request,
    bus: BusDep,
    state: StateDep,
    db: DbDep,
) -> Response | SystemStatus:
    state.blackout = payload.on
    delivered = await bus.send(op(OP_BLACKOUT, on=payload.on))
    set_setting(db, "blackout", "1" if payload.on else "0")
    if not delivered:
        log_event(db, "warn", "web", "blackout guardado pero el render no estaba conectado")
    if request.headers.get("HX-Request"):
        # El contexto completo, no solo el estado: el boton de blackout
        # reemplaza todo el bloque de controles, y con un contexto parcial el
        # selector de efectos volvia vacio y los parametros desaparecian.
        from ecomap_web.routers.effects import contexto_controles

        return render_fragment(
            request, "partials/controls.html", contexto_controles(request, db, state)
        )
    return _status(request, bus, state)
