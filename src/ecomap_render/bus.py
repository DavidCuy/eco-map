"""Servidor del bus IPC dentro del render.

Corre en un hilo aparte con `selectors`, de modo que el loop de render solo hace
`poll()` una vez por frame y nunca se bloquea (ADR-006). Acepta un cliente a la
vez: el proceso web. Si llega uno nuevo, reemplaza al anterior.
"""

from __future__ import annotations

import contextlib
import logging
import os
import selectors
import socket
import threading
from collections import deque
from pathlib import Path
from typing import Any

from ecomap_core.protocol import LineDecoder, encode
from ecomap_core.settings import BusAddress

log = logging.getLogger(__name__)

SELECT_TIMEOUT = 0.05
MAX_OUTBOX = 256


class BusServer:
    def __init__(self, address: BusAddress) -> None:
        self._address = address
        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._selector = selectors.DefaultSelector()
        self._decoder = LineDecoder()
        self._inbox: deque[dict[str, Any]] = deque()
        self._outbox: deque[bytes] = deque()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.dropped_events = 0

    # --- ciclo de vida ---

    def start(self) -> None:
        self._listener = self._listen()
        self._selector.register(self._listener, selectors.EVENT_READ)
        self._thread = threading.Thread(target=self._loop, name="bus-server", daemon=True)
        self._thread.start()
        log.info("bus: escuchando en %s", self._describe())

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._drop_client()
        if self._listener is not None:
            with contextlib.suppress(Exception):
                self._selector.unregister(self._listener)
            self._listener.close()
            if self._address[0] == "unix":
                with contextlib.suppress(OSError):
                    os.unlink(self._address[1])
            self._listener = None
        self._selector.close()

    # --- uso desde el loop de render ---

    @property
    def client_connected(self) -> bool:
        with self._lock:
            return self._client is not None

    def poll(self) -> list[dict[str, Any]]:
        """Devuelve y vacia las operaciones recibidas. No bloquea."""
        with self._lock:
            messages = list(self._inbox)
            self._inbox.clear()
        return messages

    def publish(self, message: dict[str, Any]) -> None:
        """Encola un evento hacia el web. Se descarta si nadie escucha."""
        with self._lock:
            if self._client is None:
                return
            if len(self._outbox) >= MAX_OUTBOX:
                self._outbox.popleft()
                self.dropped_events += 1
            self._outbox.append(encode(message))

    # --- interno ---

    def _describe(self) -> str:
        if self._address[0] == "tcp":
            return f"tcp://{self._address[1]}:{self._address[2]}"
        return self._address[1]

    def _listen(self) -> socket.socket:
        if self._address[0] == "tcp":
            _, host, port = self._address
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        else:
            if not hasattr(socket, "AF_UNIX"):
                raise RuntimeError(
                    "esta plataforma no soporta sockets Unix; usar ECOMAP_BUS=tcp://host:puerto"
                )
            path = Path(self._address[1])
            path.parent.mkdir(parents=True, exist_ok=True)
            # Un socket huerfano de una corrida anterior impide el bind.
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(path))
            os.chmod(path, 0o600)  # solo el usuario del servicio (Seguridad-y-Red)
        sock.listen(1)
        sock.setblocking(False)
        return sock

    def _loop(self) -> None:
        while not self._stop.is_set():
            for key, mask in self._selector.select(timeout=SELECT_TIMEOUT):
                if key.fileobj is self._listener:
                    self._accept()
                elif mask & selectors.EVENT_READ:
                    self._read()
            self._flush()

    def _accept(self) -> None:
        assert self._listener is not None
        try:
            client, _ = self._listener.accept()
        except OSError:
            return
        self._drop_client()
        client.setblocking(False)
        self._decoder = LineDecoder()
        with self._lock:
            self._client = client
            self._outbox.clear()
        self._selector.register(client, selectors.EVENT_READ)
        log.info("bus: cliente conectado")

    def _read(self) -> None:
        with self._lock:
            client = self._client
        if client is None:
            return
        try:
            chunk = client.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if not chunk:
            log.info("bus: cliente desconectado")
            self._drop_client()
            return
        messages = list(self._decoder.feed(chunk))
        if messages:
            with self._lock:
                self._inbox.extend(messages)

    def _flush(self) -> None:
        while True:
            with self._lock:
                if self._client is None or not self._outbox:
                    return
                client = self._client
                payload = self._outbox.popleft()
            try:
                client.sendall(payload)
            except (BlockingIOError, InterruptedError):
                with self._lock:
                    self._outbox.appendleft(payload)
                return
            except OSError:
                log.info("bus: cliente perdido al escribir")
                self._drop_client()
                return

    def _drop_client(self) -> None:
        with self._lock:
            client, self._client = self._client, None
            self._outbox.clear()
        if client is None:
            return
        with contextlib.suppress(Exception):
            self._selector.unregister(client)
        with contextlib.suppress(Exception):
            client.close()
