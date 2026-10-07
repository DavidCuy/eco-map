"""API de auto-calibración.

El render es quien la corre: tiene el proyector y la cámara. El web la dispara,
sigue el progreso por el bus y guarda el resultado.

Es **asíncrona a propósito**: la secuencia son decenas de patrones y tarda
varios segundos. Un POST que se quedara esperando daría timeout en el
navegador justo cuando la cosa va bien.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, status

from ecomap_core.protocol import OP_CALIBRATE, op
from ecomap_core.schemas import CalibrationOut, CalibrationStart
from ecomap_web.deps import BusDep, DbDep, StateDep

router = APIRouter(prefix="/api/calibration", tags=["calibration"])

HTTP_422 = 422


@router.post("/auto", response_model=CalibrationOut, status_code=status.HTTP_202_ACCEPTED)
async def auto(payload: CalibrationStart, bus: BusDep, state: StateDep) -> dict:
    """Arranca la secuencia. Devuelve 202: el resultado llega por WebSocket."""
    if state.camera.state != "open":
        raise HTTPException(
            HTTP_422,
            "hace falta una camara abierta: sin ella no hay nada que decodificar",
        )
    if state.calibration.get("running"):
        raise HTTPException(HTTP_422, "ya hay una calibracion en curso")

    entregado = await bus.send(
        op(OP_CALIBRATE, settle=payload.settle, max_bits=payload.max_bits)
    )
    if not entregado:
        raise HTTPException(HTTP_422, "el render no esta conectado")

    state.calibration = {"running": True, "progress": 0.0, "stage": "arrancando"}
    return state.calibration


@router.delete("/auto", response_model=CalibrationOut)
async def cancelar(bus: BusDep, state: StateDep) -> dict:
    """Corta la secuencia a mitad.

    La proyeccion vuelve a la escena configurada en el frame siguiente: durante
    la calibracion el render no toco nada, solo dibujo otra cosa encima.
    """
    if not state.calibration.get("running"):
        raise HTTPException(HTTP_422, "no hay ninguna calibracion en curso")
    if not await bus.send(op(OP_CALIBRATE, cancel=True)):
        raise HTTPException(HTTP_422, "el render no esta conectado")
    return state.calibration


@router.get("/auto", response_model=CalibrationOut)
def estado(state: StateDep) -> dict:
    """Progreso y ultimo resultado."""
    return state.calibration


@router.get("/last", response_model=CalibrationOut | None)
def ultima(db: DbDep) -> dict | None:
    """La ultima calibracion guardada, de esta corrida o de otra.

    Vive en la base porque sobrevive a reiniciar: recalibrar cuesta tiempo y
    paciencia, y nadie quiere repetirlo porque se reinicio el servicio.
    """
    fila = db.execute(
        "SELECT method, homography, rms_error, camera_w, camera_h, proj_w, proj_h, created_at "
        "FROM calibration ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return None
    return {
        "running": False,
        "ok": True,
        "method": fila["method"],
        "homography": json.loads(fila["homography"]) if fila["homography"] else None,
        "rms": fila["rms_error"],
        "camera_size": [fila["camera_w"], fila["camera_h"]],
        "proj_size": [fila["proj_w"], fila["proj_h"]],
        "created_at": fila["created_at"],
    }
