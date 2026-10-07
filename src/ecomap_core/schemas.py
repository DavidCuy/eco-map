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


# "opening" es transitorio: el web ya mando la orden y espera el evento del
# render, que es quien sabe si la camara abrio de verdad.
CameraState = Literal["closed", "opening", "open", "error"]


class CameraDeviceOut(BaseModel):
    """Una camara detectada, tal como la ofrece el selector."""

    uri: str
    name: str
    label: str
    kind: str
    node: str | None = None
    stable_path: str | None = None


class CameraStatus(BaseModel):
    """Lo que el render reporta sobre la camara que tiene abierta."""

    state: CameraState = "closed"
    source: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    backend: str | None = None
    message: str | None = None


class CameraSelectRequest(BaseModel):
    source: str = Field(
        description="URI de la camara: fake:// o v4l2:///dev/v4l/by-id/...",
        min_length=1,
        max_length=512,
    )


# --- superficies ---------------------------------------------------------

Punto = tuple[float, float]


class SurfaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mesh_cols: int = Field(default=1, ge=1, le=32)
    mesh_rows: int = Field(default=1, ge=1, le=32)


class SurfaceUpdate(BaseModel):
    """Todo opcional: es un PATCH. Lo que no viene, no se toca."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    enabled: bool | None = None


class PointsIn(BaseModel):
    points: list[Punto] = Field(min_length=4)


class SubdivideIn(BaseModel):
    cols: int = Field(ge=1, le=32)
    rows: int = Field(ge=1, le=32)


class SurfaceOut(BaseModel):
    id: int
    name: str
    kind: str
    mesh_cols: int
    mesh_rows: int
    points: list[Punto]
    opacity: float
    enabled: bool
    updated_at: str
