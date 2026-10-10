"""Esquemas compartidos. Las entidades de dominio (superficies, escenas, capas)
entran a partir del Hito 1; aqui solo esta lo que necesita el esqueleto.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# El patron de prueba del esqueleto desaparecio: ahora es un efecto mas del
# catalogo (`grid_test`), leido de archivos.


class Telemetry(BaseModel):
    """Lo que el render mide de si mismo."""

    fps: float = 0.0
    frame_ms: float = 0.0
    frame_ms_max: float = 0.0
    # De operacion recibida a frame presentado: el tramo de la latencia que el
    # render controla (RNF-2).
    apply_ms: float = 0.0
    # Camara: lo que mide el hilo de vision. En dos nucleos es el riesgo
    # principal, asi que se publica.
    camera_fps: float = 0.0
    camera_read_ms: float = 0.0
    camera_motion_ms: float = 0.0
    motion: float = 0.0
    temp: float | None = None
    dropped: int = 0
    scene_id: int | None = None
    mode: str = "headless"


class SystemStatus(BaseModel):
    """Respuesta de GET /api/system/status."""

    render_up: bool
    blackout: bool
    fps: float
    frame_ms: float
    frame_ms_max: float
    apply_ms: float
    camera_fps: float
    camera_read_ms: float
    camera_motion_ms: float
    motion: float
    temp: float | None
    dropped: int
    scene_id: int | None
    mode: str
    version: str
    effect: str | None = None
    effect_error: str | None = None
    # Lo reporta el render, no el web: la UI necesita saber en vivo si hay
    # camara para habilitar la auto-calibracion, y el panel de camara se
    # recarga por htmx aparte.
    camera_state: str = "closed"


class BlackoutRequest(BaseModel):
    on: bool


class EffectParamOut(BaseModel):
    key: str
    label: str
    type: str
    min: float
    max: float
    default: Any
    step: float | None = None
    options: list[str] = []


class EffectOut(BaseModel):
    """Un efecto del catalogo, tal como lo ofrece la UI."""

    id: str
    name: str
    version: str
    tags: list[str] = []
    needs_camera: bool = False
    needs_feedback: bool = False
    cost: str = "low"
    params: list[EffectParamOut] = []
    available: bool = True
    # `available` dice que el manifiesto es valido y el directorio existe;
    # `compiled`, que el shader pasa el compilador de **este** driver. Un efecto
    # puede estar perfecto en disco y no compilar en la Pi.
    compiled: bool = True
    error: str | None = None


class EffectSelect(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class ParamsIn(BaseModel):
    """Mezcla parcial de parametros: lo que no viene, no se toca."""

    params: dict[str, Any] = Field(default_factory=dict)


class EffectActive(BaseModel):
    """Lo que el web acepto. Si el shader no compila, el render lo desmiente
    despues por el bus y queda en `SystemStatus.effect_error`."""

    id: str
    params: dict[str, Any] = Field(default_factory=dict)


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


class MotionSettings(BaseModel):
    """Ajustes de la deteccion de movimiento.

    Son las perillas contra la realimentacion optica: subir la banda muerta
    ignora el titileo de la proyeccion, bajar el suavizado hace que responda
    mas rapido pero realimente mas facil.
    """

    dead_band: float = Field(default=0.02, ge=0.0, le=0.5)
    smoothing: float = Field(default=0.25, gt=0.0, le=1.0)
    threshold: int = Field(default=25, ge=1, le=120)


class CalibrationStart(BaseModel):
    # Frames de camara a descartar tras cambiar el patron. El valor justo
    # depende del hardware: buffer del driver, latencia USB y refresco del
    # proyector. Por eso es un parametro y no una constante.
    settle: int = Field(default=2, ge=0, le=10)
    # Mas bits es mas resolucion y mas patrones que proyectar. 8 bits son 256
    # columnas distinguibles, de sobra para una homografia.
    max_bits: int = Field(default=8, ge=4, le=11)


class CalibrationOut(BaseModel):
    running: bool = False
    progress: float = 0.0
    stage: str = ""
    ok: bool | None = None
    message: str = ""
    homography: list[list[float]] | None = None
    rms: float | None = None
    inliers: int = 0
    coverage: float = 0.0
    camera_size: list[int] | None = None
    proj_size: list[int] | None = None
    method: str = "graycode"
    created_at: str | None = None


class SnapshotSave(BaseModel):
    """Guardar la instalacion actual con un nombre."""

    name: str = Field(min_length=1, max_length=60)


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


# --- escenas y capas -----------------------------------------------------

BlendMode = Literal["normal", "add", "multiply", "screen"]


class SceneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SceneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class LayerCreate(BaseModel):
    surface_id: int
    effect_id: str = Field(min_length=1, max_length=64)
    blend_mode: BlendMode = "normal"
    params: dict[str, Any] = Field(default_factory=dict)


class LayerUpdate(BaseModel):
    """PATCH: lo que no viene, no se toca."""

    blend_mode: BlendMode | None = None
    enabled: bool | None = None
    params: dict[str, Any] | None = None


class LayerOut(BaseModel):
    id: int
    scene_id: int
    surface_id: int
    surface_name: str
    effect_id: str
    effect_name: str
    effect_available: bool
    z_order: int
    blend_mode: BlendMode
    params: dict[str, Any]
    enabled: bool


class SceneOut(BaseModel):
    id: int
    name: str
    is_default: bool
    is_active: bool
    layers: list[LayerOut] = []


class ReorderIn(BaseModel):
    """Ids de capa en el orden deseado, de abajo hacia arriba."""

    layer_ids: list[int] = Field(min_length=1)
