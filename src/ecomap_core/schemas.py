"""Esquemas compartidos. Las entidades de dominio (superficies, escenas, capas)
entran a partir del Hito 1; aqui solo esta lo que necesita el esqueleto.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TestPattern = Literal["grid", "white", "off"]


class Telemetry(BaseModel):
    """Lo que el render mide de si mismo."""

    fps: float = 0.0
    frame_ms: float = 0.0
    frame_ms_max: float = 0.0
    temp: float | None = None
    dropped: int = 0
    scene_id: int | None = None
    mode: str = "headless"


class SystemStatus(BaseModel):
    """Respuesta de GET /api/system/status."""

    render_up: bool
    blackout: bool
    pattern: TestPattern
    fps: float
    frame_ms: float
    frame_ms_max: float
    temp: float | None
    dropped: int
    scene_id: int | None
    mode: str
    version: str


class BlackoutRequest(BaseModel):
    on: bool


class PatternRequest(BaseModel):
    pattern: TestPattern = Field(description="grid, white u off")
