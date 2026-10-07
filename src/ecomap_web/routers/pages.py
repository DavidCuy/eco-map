"""Paginas HTML renderizadas en el servidor con Jinja2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ecomap_web.deps import BusDep, SettingsDep, StateDep, build_status

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["pages"])


def render_fragment(request: Request, template: str, context: dict[str, Any]) -> Response:
    """Fragmento HTML para intercambio via HTMX."""
    return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    bus: BusDep,
    state: StateDep,
    settings: SettingsDep,
) -> Response:
    from ecomap_web.routers.camera import devices_out
    from ecomap_web.routers.effects import catalogo

    status = build_status(bus, state, request.app.state.version)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "status": status,
            "logs": list(reversed(state.logs[-10:])),
            "settings": settings,
            "devices": devices_out(),
            "selected": state.camera_source or settings.camera,
            "camera": state.camera,
            "effects": catalogo(settings.effects_dir),
        },
    )


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness del contenedor web. No dice nada del render."""
    return {"status": "ok"}
