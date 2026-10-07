"""Paginas HTML renderizadas en el servidor con Jinja2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ecomap_web.deps import BusDep, DbDep, SettingsDep, StateDep, build_status

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["pages"])


def _json_para_script(datos: dict[str, Any]) -> str:
    """Serializa para incrustar dentro de un <script type="application/json">.

    Se escapa el `<` como secuencia unicode para que un nombre de superficie
    no pueda cerrar la etiqueta e inyectar codigo. El JSON sigue siendo valido:
    la secuencia la resuelve JSON.parse, no el navegador al parsear el HTML.
    """
    escape = chr(92) + "u003c"
    return json.dumps(datos, default=str).replace("<", escape)


def render_fragment(request: Request, template: str, context: dict[str, Any]) -> Response:
    """Fragmento HTML para intercambio via HTMX."""
    return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    bus: BusDep,
    state: StateDep,
    settings: SettingsDep,
    db: DbDep,
) -> Response:
    from ecomap_web.routers.camera import devices_out
    from ecomap_web.routers.effects import catalogo
    from ecomap_web.services import surfaces as surface_service

    status = build_status(bus, state, request.app.state.version)
    # El preview del render vive en otro puerto: el canvas lo muestra de fondo
    # como <img>, no lo dibuja, para no ensuciar el canvas por CORS.
    host = request.url.hostname or "localhost"
    preview_url = f"{request.url.scheme}://{host}:{settings.preview_port}/"
    workspace_config = {
        "surfaces": surface_service.listar(db),
        "status": status.model_dump(),
        "previewUrl": preview_url,
        "output": {"width": settings.width, "height": settings.height},
    }
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
            # Se inyecta como JSON y no como atributos sueltos: la malla puede
            # tener cientos de puntos. Va dentro de un <script type="application/json">,
            # y se escapan los "<" para que un nombre de superficie no pueda
            # cerrar la etiqueta e inyectar codigo.
            "workspace_config": _json_para_script(workspace_config),
        },
    )


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness del contenedor web. No dice nada del render."""
    return {"status": "ok"}
