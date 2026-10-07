"""Aplicacion FastAPI de Eco-Map.

Un solo worker de Uvicorn: el estado en memoria (conexion al bus, telemetria,
clientes WebSocket) vive en el proceso. Ver ADR-001.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ecomap_core.protocol import OP_CAMERA, OP_EFFECT, OP_PING, op
from ecomap_core.settings import Settings, load_settings
from ecomap_web import migrate
from ecomap_web.bus import BusClient
from ecomap_web.db import connect, get_setting
from ecomap_web.routers import camera, effects, pages, scenes, surfaces, system, ws
from ecomap_web.services import effects as effect_service
from ecomap_web.services import scenes as scene_service
from ecomap_web.services.persist import DebouncedWriter
from ecomap_web.state import AppState

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


def _version() -> str:
    try:
        return pkg_version("ecomap")
    except PackageNotFoundError:
        return "0.0.0+dev"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        applied = migrate.run(settings)
        if applied:
            log.info("migraciones aplicadas: %s", applied)

        conn = connect(settings.db)
        state = AppState()
        state.blackout = get_setting(conn, "blackout", "0") == "1"
        state.effect = get_setting(conn, "active_effect", "grid_test")
        state.camera_source = get_setting(conn, "camera", settings.camera)
        state.effect_params = json.loads(get_setting(conn, "active_effect_params", "{}") or "{}")

        # El catalogo se espeja al arrancar: si alguien copio un efecto nuevo
        # al volumen con el sistema apagado, aparece sin tener que recargar.
        resumen = effect_service.sincronizar(conn, settings.effects_dir)
        log.info(
            "catalogo: %d efectos, %d con error", len(resumen["cargados"]), len(resumen["errores"])
        )

        bus = BusClient(settings.bus_address())
        bus.subscribe(state.handle_event)

        async def on_connect() -> None:
            # Al (re)conectar se reenvia el estado que el render no conoce.
            # En el Hito 0 alcanza con ping + blackout + patron; la escena
            # completa entra con US-13.
            await bus.send(op(OP_PING))
            await bus.send(op("blackout", on=state.blackout))
            if state.effect:
                await bus.send(op(OP_EFFECT, id=state.effect, params=state.effect_params))
            if state.camera_source:
                await bus.send(op(OP_CAMERA, source=state.camera_source))
            # La escena completa: el render no abre la base, asi que todo lo que
            # necesita para dibujar se lo manda el web al (re)conectar.
            await scene_service.push(bus, conn)

        bus.on_connect = on_connect
        await bus.start()

        app.state.settings = settings
        app.state.db = conn
        app.state.bus = bus
        app.state.app_state = state
        app.state.version = _version()
        # Las escrituras de parametros se agrupan: ver services/persist.py.
        app.state.writer = DebouncedWriter()
        log.info("web listo en http://%s:%s", settings.host, settings.port)
        try:
            yield
        finally:
            # Primero se vuelca lo pendiente y despues se cierra la base: si no,
            # el ultimo valor de un arrastre se perderia al salir.
            await app.state.writer.flush()
            await bus.stop()
            conn.close()

    app = FastAPI(
        title="Eco-Map",
        version=_version(),
        summary="Videomapping con proyector, Raspberry Pi y camara",
        lifespan=lifespan,
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.include_router(pages.router)
    app.include_router(system.router)
    app.include_router(camera.router)
    app.include_router(surfaces.router)
    app.include_router(effects.router)
    app.include_router(scenes.router)
    app.include_router(ws.router)
    return app


app = create_app


def run() -> None:
    """Entry point `ecomap-web`."""
    import uvicorn

    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "ecomap_web.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        reload_dirs=["src"] if settings.reload else None,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    run()
