"""WebSocket de telemetria: /ws/telemetry.

El render empuja eventos por el bus y el web los reenvia tal cual. Ademas se
manda un latido periodico con el estado, para que la UI muestre "render offline"
aunque no llegue nada del render.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ecomap_web.deps import build_status

log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws/telemetry")
async def telemetry(websocket: WebSocket) -> None:
    await websocket.accept()
    app = websocket.app
    state = app.state.app_state
    bus = app.state.bus
    version = app.state.version
    period = 1.0 / app.state.settings.telemetry_hz

    state.add_client(websocket)
    try:
        await websocket.send_json(
            {"type": "status", **build_status(bus, state, version).model_dump()}
        )
        while True:
            await asyncio.sleep(period)
            await websocket.send_json(
                {"type": "status", **build_status(bus, state, version).model_dump()}
            )
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - cliente cerrado de golpe
        log.debug("ws: cliente cerrado inesperadamente", exc_info=True)
    finally:
        state.discard_client(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
