"""Servidor MJPEG del modo headless.

Publica el ultimo frame renderizado para que la UI lo muestre como preview. Se
alimenta a `preview_fps` (5 por defecto), no a 60: leer el framebuffer a CPU es
caro y rompe el pipeline si se hace por frame.
"""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

log = logging.getLogger(__name__)

BOUNDARY = "ecomapframe"


class FrameStore:
    """Ultimo JPEG disponible, con aviso a los lectores que esperan."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._jpeg: bytes | None = None
        self._seq = 0

    def put(self, jpeg: bytes) -> None:
        with self._condition:
            self._jpeg = jpeg
            self._seq += 1
            self._condition.notify_all()

    def get_after(self, seq: int, timeout: float = 5.0) -> tuple[bytes, int] | None:
        with self._condition:
            if self._seq == seq:
                self._condition.wait(timeout)
            if self._jpeg is None or self._seq == seq:
                return None
            return self._jpeg, self._seq


def encode_jpeg(rgb: bytes, width: int, height: int, quality: int = 70) -> bytes | None:
    """Comprime un buffer RGB. Devuelve None si no hay codificador disponible."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    frame = np.frombuffer(rgb, dtype=np.uint8).reshape(height, width, 3)
    # El framebuffer de GL viene con el origen abajo; la imagen va al reves.
    frame = np.flipud(frame)
    ok, buffer = cv2.imencode(".jpg", frame[:, :, ::-1], [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buffer.tobytes() if ok else None


class _Handler(BaseHTTPRequestHandler):
    store: FrameStore  # inyectado por PreviewServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug("preview: " + format, *args)

    def do_GET(self) -> None:  # noqa: N802 - firma de BaseHTTPRequestHandler
        if self.path.startswith("/snapshot"):
            self._snapshot()
        else:
            self._stream()

    def _snapshot(self) -> None:
        item = self.store.get_after(-1, timeout=2.0)
        if item is None:
            self.send_error(503, "sin frame todavia")
            return
        jpeg, _ = item
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        seq = -1
        try:
            while True:
                item = self.store.get_after(seq)
                if item is None:
                    continue
                jpeg, seq = item
                self.wfile.write(f"--{BOUNDARY}\r\n".encode("ascii"))
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # el navegador cerro la pestana


class PreviewServer:
    def __init__(self, port: int, store: FrameStore) -> None:
        handler = type("Handler", (_Handler,), {"store": store})
        self._httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)  # noqa: S104
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="preview", daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        log.info("preview: MJPEG en http://0.0.0.0:%s/", self._httpd.server_port)

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
