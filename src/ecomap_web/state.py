"""Estado en memoria del proceso web: ultima telemetria del render y suscriptores
de WebSocket.

Un solo worker de Uvicorn (ADR-001), asi que este estado es seguro sin locks
entre peticiones: todo vive en el mismo event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from ecomap_core.protocol import EV_CALIB, EV_CAMERA, EV_EFFECTS, EV_ERROR, EV_TELE
from ecomap_core.schemas import CameraStatus, Telemetry

log = logging.getLogger(__name__)

MAX_LOG_LINES = 50


class AppState:
    def __init__(self) -> None:
        self.telemetry = Telemetry()
        self.last_telemetry_at: float | None = None
        self.blackout = False
        self.effect: str | None = None
        self.effect_params: dict[str, Any] = {}
        self.effect_error: str | None = None
        # Lo que el render reporto que NO compila, por id. Es lo unico que el
        # web no puede saber solo: el manifiesto puede estar perfecto y el
        # shader fallar en el driver de turno.
        self.effect_errors: dict[str, str] = {}
        self.calibration: dict[str, Any] = {"running": False, "progress": 0.0, "stage": ""}
        # Lo pone el web cuando llega un resultado valido, para que el router
        # lo guarde en la base sin tener que hablar con el bus.
        self.on_calibration: Any | None = None
        self.camera = CameraStatus()
        self.camera_source: str | None = None
        self.logs: list[dict[str, Any]] = []
        self._clients: set[Any] = set()

    # --- entrada desde el bus ---

    def handle_event(self, message: dict[str, Any]) -> None:
        kind = message.get("ev")
        if kind == EV_TELE:
            payload = {k: v for k, v in message.items() if k != "ev"}
            try:
                self.telemetry = Telemetry.model_validate(payload)
            except Exception:  # noqa: BLE001 - telemetria malformada no debe romper el web
                log.warning("telemetria invalida: %s", payload)
                return
            self.last_telemetry_at = time.monotonic()
        elif kind == EV_CAMERA:
            payload = {k: v for k, v in message.items() if k != "ev"}
            try:
                self.camera = CameraStatus.model_validate(payload)
            except Exception:  # noqa: BLE001 - estado malformado no debe romper el web
                log.warning("estado de camara invalido: %s", payload)
                return
            if self.camera.source:
                self.camera_source = self.camera.source
        elif kind == EV_CALIB:
            self._calibracion(message)
        elif kind == EV_EFFECTS:
            errores = message.get("errors") or {}
            self.effect_errors = {str(k): str(v) for k, v in errores.items()}
        elif kind == EV_ERROR:
            if message.get("source") == "effect":
                # El render no pudo usar el efecto pedido: queda visible en la
                # UI en vez de perderse en el log.
                self.effect_error = str(message.get("msg", ""))
            self.push_log(
                level=str(message.get("level", "error")),
                source=str(message.get("source", "render")),
                message=str(message.get("msg", "")),
            )
        self.broadcast_soon(message)

    def _calibracion(self, message: dict[str, Any]) -> None:
        if message.get("done"):
            self.calibration = {
                "running": False,
                "progress": 1.0,
                "stage": "terminada",
                "ok": bool(message.get("ok")),
                "message": str(message.get("msg", "")),
                "homography": message.get("homography"),
                "rms": message.get("rms"),
                "inliers": int(message.get("inliers") or 0),
                "coverage": float(message.get("coverage") or 0.0),
                "camera_size": message.get("camera_size"),
                "proj_size": message.get("proj_size"),
            }
            if self.on_calibration and message.get("ok"):
                self.on_calibration(self.calibration)
            return
        self.calibration = {
            "running": True,
            "progress": float(message.get("progress") or 0.0),
            "stage": str(message.get("stage", "")),
        }

    def push_log(self, level: str, source: str, message: str) -> None:
        self.logs.append({"level": level, "source": source, "msg": message, "ts": time.time()})
        del self.logs[:-MAX_LOG_LINES]

    # --- WebSocket ---

    def add_client(self, websocket: Any) -> None:
        self._clients.add(websocket)

    def discard_client(self, websocket: Any) -> None:
        self._clients.discard(websocket)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def broadcast_soon(self, message: dict[str, Any]) -> None:
        """Encola el envio sin bloquear a quien produjo el mensaje."""
        if not self._clients:
            return
        with contextlib.suppress(RuntimeError):  # sin event loop corriendo (tests sincronos)
            asyncio.get_running_loop().create_task(self.broadcast(message))

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for client in list(self._clients):
            try:
                await client.send_json(message)
            except Exception:  # noqa: BLE001 - cliente que se fue sin avisar
                dead.append(client)
        for client in dead:
            self._clients.discard(client)
