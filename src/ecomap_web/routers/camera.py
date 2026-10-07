"""API de cámara: qué hay disponible y cuál se usa.

El web **enumera** (lee sysfs, no abre nada) y el render **abre**: es quien tiene
el device montado y el contexto GL donde va a vivir la textura. Si el device
elegido no se puede abrir, el render lo reporta por el bus y la UI lo muestra.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ecomap_core.protocol import OP_CAMERA, OP_MOTION, op
from ecomap_core.schemas import (
    CameraDeviceOut,
    CameraSelectRequest,
    CameraStatus,
    MotionSettings,
)
from ecomap_vision.devices import enumerate_cameras
from ecomap_web.db import get_setting, log_event, set_setting
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


def _contexto(request: Request, devices, state, settings, selected=None, motion=None) -> dict:
    """Contexto del panel de camara. Esta en un solo lugar porque tres
    endpoints devuelven el mismo fragmento."""
    from ecomap_web.deps import get_db, get_settings

    settings = settings or get_settings(request)
    host = request.url.hostname or "localhost"
    return {
        "devices": devices,
        "selected": selected or state.camera_source or settings.camera,
        "camera": state.camera,
        "motion": motion or obtener_motion(get_db(request)),
        # El stream de camara lo sirve el render en su propio puerto, igual que
        # el de la proyeccion.
        "camera_stream": f"{request.url.scheme}://{host}:{settings.preview_port}/camera",
    }


@router.get("/devices", response_model=list[CameraDeviceOut])
def list_devices(
    request: Request, state: StateDep, settings: SettingsDep
) -> Response | list[CameraDeviceOut]:
    devices = devices_out()
    if request.headers.get("HX-Request"):
        return render_fragment(
            request, "partials/camera.html", _contexto(request, devices, state, settings)
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
            _contexto(request, devices_out(), state, settings, selected=payload.source),
        )
    return state.camera


@router.get("/motion", response_model=MotionSettings)
def obtener_motion(db: DbDep) -> MotionSettings:
    return MotionSettings(
        dead_band=float(get_setting(db, "motion_dead_band", "0.02") or 0.02),
        smoothing=float(get_setting(db, "motion_smoothing", "0.25") or 0.25),
        threshold=int(get_setting(db, "motion_threshold", "25") or 25),
    )


@router.put("/motion", response_model=MotionSettings)
async def ajustar_motion(
    payload: MotionSettings, request: Request, bus: BusDep, db: DbDep, state: StateDep
) -> Response | MotionSettings:
    """Ajustes de la deteccion. Son las perillas contra la realimentacion."""
    set_setting(db, "motion_dead_band", str(payload.dead_band))
    set_setting(db, "motion_smoothing", str(payload.smoothing))
    set_setting(db, "motion_threshold", str(payload.threshold))
    await bus.send(
        op(
            OP_MOTION,
            dead_band=payload.dead_band,
            smoothing=payload.smoothing,
            threshold=payload.threshold,
        )
    )
    if request.headers.get("HX-Request"):
        return render_fragment(
            request,
            "partials/camera.html",
            _contexto(request, devices_out(), state, None, motion=payload),
        )
    return payload
