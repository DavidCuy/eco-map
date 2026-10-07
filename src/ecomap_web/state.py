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

from ecomap_core.protocol import EV_CAMERA, EV_ERROR, EV_TELE
from ecomap_core.schemas import CameraStatus, Telemetry, TestPattern

log = logging.getLogger(__name__)

MAX_LOG_LINES = 50


class AppState:
    def __init__(self) -> None:
        self.telemetry = Telemetry()
        self.last_telemetry_at: float | None = None
        self.blackout = False
        self.pattern: TestPattern = "off"
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
        elif kind == EV_ERROR:
            self.push_log(
                level=str(message.get("level", "error")),
                source=str(message.get("source", "render")),
                message=str(message.get("msg", "")),
            )
        self.broadcast_soon(message)

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
