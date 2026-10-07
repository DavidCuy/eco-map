"""Cliente del bus IPC: el web se conecta al socket que publica el render.

Reconecta solo. Si el render esta caido, `send` devuelve False y la UI lo
muestra como "render offline"; al reconectar se dispara `on_connect` para que el
web reenvie el estado completo (ADR-006).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ecomap_core.protocol import LineDecoder, encode
from ecomap_core.settings import BusAddress

log = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], None]
ConnectHook = Callable[[], Awaitable[None]]

RETRY_SECONDS = 1.0
READ_CHUNK = 65536


class BusClient:
    def __init__(self, address: BusAddress) -> None:
        self._address = address
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._handlers: list[EventHandler] = []
        self._stopping = asyncio.Event()
        self.on_connect: ConnectHook | None = None

    # --- ciclo de vida ---

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="bus-client")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._close_writer()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    # --- uso ---

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def send(self, message: dict[str, Any]) -> bool:
        """Envia una operacion. False si el render no esta conectado."""
        writer = self._writer
        if writer is None or writer.is_closing():
            return False
        try:
            writer.write(encode(message))
            await writer.drain()
            return True
        except (OSError, ConnectionError) as exc:
            log.warning("bus: fallo al enviar (%s)", exc)
            await self._close_writer()
            return False

    # --- interno ---

    async def _open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._address[0] == "tcp":
            _, host, port = self._address
            return await asyncio.open_connection(host, port)
        _, path = self._address
        open_unix = getattr(asyncio, "open_unix_connection", None)
        if open_unix is None:  # Windows: hay que usar tcp://
            raise RuntimeError(
                "esta plataforma no soporta sockets Unix; usar ECOMAP_BUS=tcp://host:puerto"
            )
        return await open_unix(path)

    async def _run(self) -> None:
        warned = False
        while not self._stopping.is_set():
            try:
                reader, writer = await self._open()
            except (OSError, RuntimeError) as exc:
                if not warned:
                    log.warning("bus: render no disponible (%s); reintentando", exc)
                    warned = True
                await asyncio.sleep(RETRY_SECONDS)
                continue

            warned = False
            self._writer = writer
            log.info("bus: conectado al render")
            if self.on_connect:
                await self.on_connect()

            decoder = LineDecoder()
            try:
                while True:
                    chunk = await reader.read(READ_CHUNK)
                    if not chunk:
                        break
                    for message in decoder.feed(chunk):
                        self._dispatch(message)
            except (OSError, ConnectionError) as exc:
                log.warning("bus: conexion perdida (%s)", exc)
            finally:
                await self._close_writer()
                log.info("bus: desconectado del render")

            await asyncio.sleep(RETRY_SECONDS)

    def _dispatch(self, message: dict[str, Any]) -> None:
        for handler in self._handlers:
            try:
                handler(message)
            except Exception:  # noqa: BLE001 - un handler roto no debe cortar el bus
                log.exception("bus: handler fallo procesando %s", message.get("ev"))

    async def _close_writer(self) -> None:
        writer, self._writer = self._writer, None
        if writer is None:
            return
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
