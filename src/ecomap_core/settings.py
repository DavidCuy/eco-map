"""Configuracion compartida por web y render.

Todo se lee de variables de entorno con prefijo ECOMAP_. Los valores por defecto
apuntan a las rutas de los volumenes Docker; en desarrollo local se sobreescriben
con un .env (ver .env.example).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RenderMode = Literal["kms", "window", "headless"]

# Direccion del bus IPC: un socket Unix (ruta) o tcp://host:puerto.
# En Windows no hay AF_UNIX usable desde CPython, asi que ahi hay que usar tcp://.
BusAddress = tuple[Literal["unix"], str] | tuple[Literal["tcp"], str, int]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ECOMAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Los campos con validation_alias se construyen por nombre igual, que es
        # como los arman los tests.
        populate_by_name=True,
    )

    # --- almacenamiento ---
    # Los compose y el Dockerfile usan ECOMAP_EFFECTS y ECOMAP_MEDIA desde el
    # Hito 0, pero el nombre que pydantic deriva del campo es ECOMAP_EFFECTS_DIR:
    # las variables cortas nunca hicieron nada. No se noto porque dentro del
    # contenedor el valor coincidia con el default, asi que daba igual. Fuera del
    # contenedor no: en Windows el default /effects se vuelve \effects y el
    # catalogo no carga. Se aceptan las dos formas para no romper despliegues.
    # El prefijo ECOMAP_ no se aplica a los campos con validation_alias, por eso
    # los alias van con el nombre completo.
    db: Path = Path("/data/ecomap.db")
    effects_dir: Path = Field(
        default=Path("/effects"),
        validation_alias=AliasChoices("ECOMAP_EFFECTS_DIR", "ECOMAP_EFFECTS"),
    )
    media_dir: Path = Field(
        default=Path("/media"),
        validation_alias=AliasChoices("ECOMAP_MEDIA_DIR", "ECOMAP_MEDIA"),
    )
    migrations_dir: Path = Field(
        default=Path("migrations"),
        validation_alias=AliasChoices("ECOMAP_MIGRATIONS_DIR", "ECOMAP_MIGRATIONS"),
    )

    # --- bus IPC entre web y render ---
    bus: str = "/run/ecomap/bus.sock"

    # --- web ---
    host: str = "0.0.0.0"  # noqa: S104 - red local de proposito unico, ver Seguridad-y-Red
    port: int = 8000
    reload: bool = False

    # --- render ---
    render_mode: RenderMode = "headless"
    width: int = 1920
    height: int = 1080
    fps: int = 60
    # Backend de contexto GL para el modo headless: egl en la Pi y en contenedores,
    # None deja que moderngl elija (escritorio con GPU).
    gl_backend: str | None = None
    # --- modo window ---
    # Pantalla completa a la resolucion nativa del monitor. Imprescindible al
    # proyectar: una ventana con barra de titulo corre la imagen unos pixeles y
    # la calibracion deja de corresponder con lo que se ve.
    window_fullscreen: bool = False
    # Monitor destino, 0 = primario. En la mini PC con dos salidas HDMI el
    # proyector no siempre es el primario, y GLFW va al primario por defecto.
    window_monitor: int = Field(default=0, ge=0)

    # --- preview MJPEG que publica el render en modo headless ---
    preview_port: int = 8001
    preview_fps: int = 5
    preview_width: int = 480

    # --- camara (se usa a partir del Hito 4) ---
    camera: str = "fake://"

    # --- calibracion ---
    # Error de reproyeccion, en pixeles de camara, a partir del cual la UI
    # desconfia de la homografia y ofrece calibrar a mano. Es configurable
    # porque el valor util depende de la resolucion de la camara y de cuan
    # exigente sea el montaje.
    calibration_rms_warn: float = Field(default=2.0, gt=0)

    # --- telemetria ---
    telemetry_hz: float = Field(default=2.0, gt=0)

    def bus_address(self) -> BusAddress:
        """Traduce `bus` a una direccion concreta de socket."""
        raw = self.bus
        if raw.startswith("tcp://"):
            parsed = urlparse(raw)
            if not parsed.hostname or not parsed.port:
                raise ValueError(f"bus tcp mal formado: {raw!r} (esperado tcp://host:puerto)")
            return ("tcp", parsed.hostname, parsed.port)
        if raw.startswith("unix://"):
            raw = raw[len("unix://") :]
        return ("unix", raw)


def load_settings() -> Settings:
    return Settings()
