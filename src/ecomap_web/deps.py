"""Dependencias compartidas por los routers."""

from __future__ import annotations

import sqlite3
import time
from typing import Annotated

from fastapi import Depends, Request

from ecomap_core.schemas import SystemStatus
from ecomap_core.settings import Settings
from ecomap_web.bus import BusClient
from ecomap_web.state import AppState

# Si no llega telemetria en este tiempo, el render se considera caido aunque el
# socket siga abierto.
TELEMETRY_STALE_SECONDS = 5.0


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def get_bus(request: Request) -> BusClient:
    return request.app.state.bus


def get_state(request: Request) -> AppState:
    return request.app.state.app_state


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
BusDep = Annotated[BusClient, Depends(get_bus)]
StateDep = Annotated[AppState, Depends(get_state)]


def render_up(bus: BusClient, state: AppState) -> bool:
    if not bus.connected:
        return False
    if state.last_telemetry_at is None:
        return True  # recien conectado, todavia no llego el primer tele
    return (time.monotonic() - state.last_telemetry_at) < TELEMETRY_STALE_SECONDS


def build_status(bus: BusClient, state: AppState, version: str) -> SystemStatus:
    tele = state.telemetry
    return SystemStatus(
        render_up=render_up(bus, state),
        blackout=state.blackout,
        pattern=state.pattern,
        fps=tele.fps,
        frame_ms=tele.frame_ms,
        frame_ms_max=tele.frame_ms_max,
        temp=tele.temp,
        dropped=tele.dropped,
        scene_id=tele.scene_id,
        mode=tele.mode,
        version=version,
    )
