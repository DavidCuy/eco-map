"""API de cámara: qué hay disponible y cuál se usa.

El web **enumera** (lee sysfs, no abre nada) y el render **abre**: es quien tiene
el device montado y el contexto GL donde va a vivir la textura. Si el device
elegido no se puede abrir, el render lo reporta por el bus y la UI lo muestra.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ecomap_core.protocol import OP_CAMERA, op
from ecomap_core.schemas import CameraDeviceOut, CameraSelectRequest, CameraStatus
from ecomap_vision.devices import enumerate_cameras
from ecomap_web.db import log_event, set_setting
from ecomap_web.deps import BusDep, DbDep, SettingsDep, StateDep
from ecomap_web.routers.pages import render_fragment

router = APIRouter(prefix="/api/camera", tags=["camera"])


def devices_out() -> list[CameraDeviceOut]:
    return [
        CameraDeviceOut(
            uri=device.uri,
            name=device.name,
            label=device.label,
            kind=device.kind,
            node=device.node,
            stable_path=device.stable_path,
        )
        for device in enumerate_cameras()
    ]


@router.get("/devices", response_model=list[CameraDeviceOut])
def list_devices(
    request: Request, state: StateDep, settings: SettingsDep
) -> Response | list[CameraDeviceOut]:
    devices = devices_out()
    if request.headers.get("HX-Request"):
        return render_fragment(
            request,
            "partials/camera.html",
            {
                "devices": devices,
                "selected": state.camera_source or settings.camera,
                "camera": state.camera,
            },
        )
    return devices


@router.get("/status", response_model=CameraStatus)
def get_status(state: StateDep) -> CameraStatus:
    return state.camera


@router.post("/select", response_model=CameraStatus)
async def select(
    payload: CameraSelectRequest,
    request: Request,
    bus: BusDep,
    state: StateDep,
    db: DbDep,
    settings: SettingsDep,
) -> Response | CameraStatus:
    state.camera_source = payload.source
    delivered = await bus.send(op(OP_CAMERA, source=payload.source))
    set_setting(db, "camera", payload.source)

    if delivered:
        # El estado real lo define el render, y su evento llega despues: hasta
        # entonces se muestra "abriendo", no el estado anterior (que podria ser
        # el error de la camara que acabamos de descartar).
        state.camera = CameraStatus(state="opening", source=payload.source)
    else:
        # Queda guardado y se reenvía al reconectar; el estado real lo dirá el
        # render cuando vuelva.
        log_event(db, "warn", "web", "camara guardada pero el render no estaba conectado")
        state.camera = CameraStatus(
            state="closed",
            source=payload.source,
            message="render offline: se aplica al reconectar",
        )

    if request.headers.get("HX-Request"):
        return render_fragment(
            request,
            "partials/camera.html",
            {
                "devices": devices_out(),
                "selected": payload.source,
                "camera": state.camera,
            },
        )
    return state.camera
