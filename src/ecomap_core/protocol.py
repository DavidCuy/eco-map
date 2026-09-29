"""Protocolo del bus IPC entre ecomap-web y ecomap-render.

JSON Lines: un objeto JSON por linea, terminado en \\n. Sin versionado: ambos
procesos se despliegan juntos (ADR-006).

Sentido web -> render: {"op": ...}
Sentido render -> web: {"ev": ...}
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

# --- operaciones (web -> render) ---
OP_PING = "ping"
OP_SCENE = "scene"
OP_PARAM = "param"
OP_POINTS = "points"
OP_BLACKOUT = "blackout"
OP_PATTERN = "pattern"

OPS = frozenset({OP_PING, OP_SCENE, OP_PARAM, OP_POINTS, OP_BLACKOUT, OP_PATTERN})

# --- eventos (render -> web) ---
EV_PONG = "pong"
EV_TELE = "tele"
EV_ERROR = "error"
EV_CALIB = "calib"

EVENTS = frozenset({EV_PONG, EV_TELE, EV_ERROR, EV_CALIB})

MAX_LINE_BYTES = 1 << 20  # 1 MiB: una escena serializada entra de sobra


def op(name: str, /, **fields: Any) -> dict[str, Any]:
    """Construye una operacion validando el nombre contra el protocolo."""
    if name not in OPS:
        raise ValueError(f"operacion desconocida: {name!r}")
    return {"op": name, **fields}


def ev(name: str, /, **fields: Any) -> dict[str, Any]:
    """Construye un evento validando el nombre contra el protocolo."""
    if name not in EVENTS:
        raise ValueError(f"evento desconocido: {name!r}")
    return {"ev": name, **fields}


def encode(message: dict[str, Any]) -> bytes:
    """Serializa un mensaje a una linea de bytes lista para enviar."""
    return (json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


class LineDecoder:
    """Acumula bytes de un socket y entrega los mensajes completos.

    Tolera que los mensajes lleguen partidos o varios en un mismo recv, que es el
    caso normal en un stream. Descarta lineas invalidas en vez de romper la
    conexion: un mensaje corrupto no debe tirar el render.
    """

    def __init__(self, max_line_bytes: int = MAX_LINE_BYTES) -> None:
        self._buffer = bytearray()
        self._max = max_line_bytes
        self.dropped = 0

    def feed(self, chunk: bytes) -> Iterator[dict[str, Any]]:
        self._buffer.extend(chunk)
        while True:
            index = self._buffer.find(b"\n")
            if index < 0:
                if len(self._buffer) > self._max:
                    # Linea sin fin a la vista: se descarta lo acumulado.
                    self._buffer.clear()
                    self.dropped += 1
                return
            raw = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            if not raw.strip():
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                self.dropped += 1
                continue
            if isinstance(message, dict):
                yield message
            else:
                self.dropped += 1
