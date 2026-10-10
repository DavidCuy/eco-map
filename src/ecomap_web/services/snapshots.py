"""Escenas como archivos: guardar y abrir una instalacion entera.

Una escena deja de ser una fila con nombre y pasa a ser un **documento**. Lo
que se esta tocando en el dashboard es siempre "la escena actual": se
autoguarda sola en la base, y aparte se puede guardar con nombre y volver a
abrir. No hay que crear una escena antes de trabajar, que era lo que el boton
"+ escena" obligaba a hacer sin explicar por que.

El archivo lleva **toda la instalacion**: caras con su malla, capas,
calibracion y el efecto global. Abrirlo reemplaza todo eso. Es una decision
tomada a sabiendas: sirve para replicar una instalacion completa en otro
equipo, y el costo es que pisa la calibracion fisica, que cuesta veinte
minutos de ajustar esquinas.

Por eso **antes de abrir siempre se guarda un respaldo automatico** del estado
actual. La decision de reemplazar todo se mantiene; lo que se evita es que sea
irreversible.

Las capas referencian las caras **por nombre**, no por id. Los ids no
significan nada fuera de esta base: al abrir un archivo guardado en otro
equipo apuntarian a cualquier lado. El nombre es ademas lo que el operador
tiene en la cabeza: "frontal", "lateral".
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ecomap_core.geometry import GeometryError, validate_mesh
from ecomap_web.db import get_setting, set_setting
from ecomap_web.services import scenes as scene_service
from ecomap_web.services import surfaces as surface_service

log = logging.getLogger(__name__)

# Version del formato. Si alguna vez cambia la forma del archivo, esto permite
# leer los viejos en vez de fallar con un KeyError.
FORMATO = 1
EXTENSION = ".json"

# Prefijo de los respaldos que se toman solos antes de abrir. Se listan aparte
# para que no se mezclen con las escenas que el operador guardo a proposito.
PREFIJO_RESPALDO = "respaldo-"
MAX_RESPALDOS = 10


class SnapshotError(RuntimeError):
    """El archivo no se puede leer, o no se puede escribir donde se pidio."""


def nombre_de_archivo(nombre: str) -> str:
    """Pasa un nombre escrito por una persona a un nombre de archivo seguro.

    Se restringe a propósito: el nombre llega por HTTP y termina siendo una
    ruta. Sin esto, un nombre con `../` escribiria fuera del directorio.
    """
    limpio = re.sub(r"[^\w\s-]", "", nombre, flags=re.UNICODE).strip()
    limpio = re.sub(r"[\s_]+", "-", limpio).lower()
    if not limpio:
        raise SnapshotError("el nombre no puede quedar vacio")
    return limpio[:60] + EXTENSION


def _ruta(directorio: Path, nombre: str) -> Path:
    ruta = (directorio / nombre_de_archivo(nombre)).resolve()
    # Cinturon y tirantes: aunque el nombre ya se limpio, se comprueba que la
    # ruta resuelta siga cayendo dentro del directorio.
    if directorio.resolve() not in ruta.parents:
        raise SnapshotError("ruta de escena fuera del directorio permitido")
    return ruta


# --- serializar ----------------------------------------------------------


def exportar(conn: sqlite3.Connection, nombre: str = "") -> dict[str, Any]:
    """La instalacion entera como un diccionario listo para guardar."""
    caras = surface_service.listar(conn)
    por_id = {c["id"]: c["name"] for c in caras}

    escena_id = scene_service.escena_activa(conn)
    capas = scene_service.obtener(conn, escena_id)["layers"] if escena_id else []

    return {
        "ecomap": FORMATO,
        "nombre": nombre,
        "guardado": datetime.now(UTC).isoformat(timespec="seconds"),
        "caras": [
            {
                "nombre": c["name"],
                "mesh_cols": c["mesh_cols"],
                "mesh_rows": c["mesh_rows"],
                "points": c["points"],
                "opacity": c["opacity"],
                "enabled": c["enabled"],
            }
            for c in caras
        ],
        "capas": [
            {
                # Por nombre: los ids no significan nada en otro equipo.
                "cara": por_id.get(capa["surface_id"], ""),
                "efecto": capa["effect_id"],
                "blend": capa["blend_mode"],
                "params": capa["params"],
                "enabled": capa["enabled"],
            }
            for capa in capas
        ],
        "calibracion": _calibracion(conn),
        "efecto_global": {
            "id": get_setting(conn, "active_effect", ""),
            "params": json.loads(get_setting(conn, "active_effect_params", "{}") or "{}"),
        },
    }


def _calibracion(conn: sqlite3.Connection) -> dict[str, Any] | None:
    fila = conn.execute(
        "SELECT method, homography, rms_error, camera_w, camera_h, proj_w, proj_h "
        "FROM calibration ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return None
    return {
        "method": fila["method"],
        "homography": json.loads(fila["homography"]) if fila["homography"] else None,
        "rms_error": fila["rms_error"],
        "camera_w": fila["camera_w"],
        "camera_h": fila["camera_h"],
        "proj_w": fila["proj_w"],
        "proj_h": fila["proj_h"],
    }


# --- validar -------------------------------------------------------------


def validar(datos: Any) -> dict[str, Any]:
    """Comprueba la forma del archivo antes de dejarlo tocar la base.

    Se valida aca y no con Pydantic en el router porque el archivo tambien
    puede venir de disco, no solo de una subida.
    """
    if not isinstance(datos, dict):
        raise SnapshotError("el archivo no contiene un objeto JSON")
    version = datos.get("ecomap")
    if version != FORMATO:
        raise SnapshotError(
            f"formato de escena desconocido: {version!r} (esta version lee {FORMATO})"
        )
    for clave in ("caras", "capas"):
        if not isinstance(datos.get(clave), list):
            raise SnapshotError(f"falta la lista {clave!r} o no es una lista")

    for cara in datos["caras"]:
        try:
            cols, rows = int(cara["mesh_cols"]), int(cara["mesh_rows"])
            puntos = [(float(x), float(y)) for x, y in cara["points"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError(f"cara invalida en el archivo: {exc}") from exc
        if not str(cara.get("nombre", "")).strip():
            raise SnapshotError("hay una cara sin nombre")
        # Que la malla cierre: un archivo con puntos de menos deja una
        # superficie que el render no puede triangular. El error de geometria
        # se traduce: desde afuera esto es "el archivo esta mal", y quien lo
        # llama solo sabe atrapar SnapshotError.
        try:
            validate_mesh(puntos, cols, rows)
        except GeometryError as exc:
            raise SnapshotError(f"cara {cara.get('nombre', '?')!r}: {exc}") from exc
    return datos


# --- aplicar -------------------------------------------------------------


def importar(conn: sqlite3.Connection, datos: dict[str, Any]) -> dict[str, Any]:
    """Reemplaza caras, capas y calibracion con las del archivo.

    Todo en una transaccion: si algo falla a mitad, no queda una instalacion
    con las caras nuevas y las capas viejas, que seria peor que no haber
    importado nada.
    """
    validar(datos)
    informe: dict[str, Any] = {"caras": 0, "capas": 0, "omitidas": []}

    with conn:  # transaccion
        # Borrar las caras arrastra sus capas por ON DELETE CASCADE.
        for cara in surface_service.listar(conn):
            conn.execute("DELETE FROM surface WHERE id = ?", (cara["id"],))

        por_nombre: dict[str, int] = {}
        for cara in datos["caras"]:
            creada = surface_service.crear(
                conn, str(cara["nombre"]), int(cara["mesh_cols"]), int(cara["mesh_rows"])
            )
            surface_service.guardar_puntos(
                conn, creada["id"], [(float(x), float(y)) for x, y in cara["points"]]
            )
            campos = {}
            if "opacity" in cara:
                campos["opacity"] = float(cara["opacity"])
            if "enabled" in cara:
                campos["enabled"] = bool(cara["enabled"])
            if campos:
                surface_service.actualizar(conn, creada["id"], campos)
            por_nombre[str(cara["nombre"])] = creada["id"]
            informe["caras"] += 1

        escena_id = scene_service.escena_activa(conn)
        if escena_id is None:
            escena_id = scene_service.crear(conn, datos.get("nombre") or "escena")["id"]
        conn.execute("DELETE FROM layer WHERE scene_id = ?", (escena_id,))

        for capa in datos["capas"]:
            surface_id = por_nombre.get(str(capa.get("cara", "")))
            if surface_id is None:
                informe["omitidas"].append(
                    f"{capa.get('efecto', '?')}: no hay una cara llamada "
                    f"{capa.get('cara', '')!r}"
                )
                continue
            try:
                creada = scene_service.crear_capa(
                    conn,
                    escena_id,
                    surface_id,
                    str(capa["efecto"]),
                    str(capa.get("blend", "normal")),
                    dict(capa.get("params") or {}),
                )
            except Exception as exc:  # noqa: BLE001 - una capa mala no aborta el resto
                # Tipico al mover una instalacion: el efecto no esta instalado
                # en este equipo. Se reporta y se sigue, que es mas util que
                # rechazar el archivo entero.
                informe["omitidas"].append(f"{capa.get('efecto', '?')}: {exc}")
                continue
            if not capa.get("enabled", True):
                scene_service.actualizar_capa(conn, creada["id"], {"enabled": False})
            informe["capas"] += 1

        if datos.get("calibracion"):
            _guardar_calibracion(conn, datos["calibracion"])

        global_ = datos.get("efecto_global") or {}
        if global_.get("id"):
            set_setting(conn, "active_effect", str(global_["id"]))
            set_setting(conn, "active_effect_params", json.dumps(global_.get("params") or {}))

        if datos.get("nombre"):
            conn.execute(
                "UPDATE scene SET name = ? WHERE id = ?", (str(datos["nombre"]), escena_id)
            )

    return informe


def _guardar_calibracion(conn: sqlite3.Connection, cal: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO calibration (method, homography, rms_error, camera_w, camera_h, "
        "proj_w, proj_h) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            cal.get("method", "manual"),
            json.dumps(cal["homography"]) if cal.get("homography") else None,
            cal.get("rms_error"),
            cal.get("camera_w"),
            cal.get("camera_h"),
            cal.get("proj_w"),
            cal.get("proj_h"),
        ),
    )


# --- archivos ------------------------------------------------------------


def listar_archivos(directorio: Path) -> list[dict[str, Any]]:
    """Las escenas guardadas, de la mas reciente a la mas vieja."""
    try:
        archivos = sorted(directorio.glob(f"*{EXTENSION}"))
    except OSError:
        return []

    salida = []
    for ruta in archivos:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Un archivo roto no deberia romper la lista: se muestra para que
            # se pueda borrar, con lo poco que se sabe de el.
            salida.append({"archivo": ruta.name, "nombre": ruta.stem, "roto": True})
            continue
        salida.append(
            {
                "archivo": ruta.name,
                "nombre": datos.get("nombre") or ruta.stem,
                "guardado": datos.get("guardado"),
                "caras": len(datos.get("caras") or []),
                "capas": len(datos.get("capas") or []),
                "respaldo": ruta.name.startswith(PREFIJO_RESPALDO),
                "roto": False,
            }
        )
    salida.sort(key=lambda d: d.get("guardado") or "", reverse=True)
    return salida


def guardar(conn: sqlite3.Connection, directorio: Path, nombre: str) -> dict[str, Any]:
    directorio.mkdir(parents=True, exist_ok=True)
    datos = exportar(conn, nombre)
    ruta = _ruta(directorio, nombre)
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("escena guardada en %s", ruta.name)
    return {"archivo": ruta.name, "nombre": nombre, "guardado": datos["guardado"]}


def leer(directorio: Path, archivo: str) -> dict[str, Any]:
    ruta = directorio / Path(archivo).name  # sin rutas relativas
    try:
        return validar(json.loads(ruta.read_text(encoding="utf-8")))
    except OSError as exc:
        raise SnapshotError(f"no se pudo leer {archivo}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{archivo} no es un JSON valido: {exc}") from exc


def respaldar(conn: sqlite3.Connection, directorio: Path) -> str:
    """Guarda el estado actual antes de pisarlo.

    Abrir una escena reemplaza las caras y la calibracion. Que eso sea
    reversible no es opcional: recalibrar cuesta veinte minutos y nadie se
    acuerda de respaldar antes.
    """
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    guardado = guardar(conn, directorio, f"{PREFIJO_RESPALDO}{marca}")
    _podar_respaldos(directorio)
    return guardado["archivo"]


def _podar_respaldos(directorio: Path) -> None:
    """Deja solo los ultimos: en una SD, los respaldos infinitos la llenan."""
    respaldos = sorted(directorio.glob(f"{PREFIJO_RESPALDO}*{EXTENSION}"))
    for ruta in respaldos[:-MAX_RESPALDOS]:
        try:
            ruta.unlink()
        except OSError:  # pragma: no cover - permisos raros
            log.warning("no se pudo borrar el respaldo %s", ruta.name)


def abrir(conn: sqlite3.Connection, directorio: Path, archivo: str) -> dict[str, Any]:
    """Respalda lo que hay y carga el archivo encima."""
    datos = leer(directorio, archivo)
    respaldo = respaldar(conn, directorio)
    informe = importar(conn, datos)
    informe["respaldo"] = respaldo
    informe["nombre"] = datos.get("nombre") or Path(archivo).stem
    return informe


def borrar(directorio: Path, archivo: str) -> None:
    ruta = directorio / Path(archivo).name
    try:
        ruta.unlink()
    except FileNotFoundError as exc:
        raise SnapshotError(f"no existe {archivo}") from exc
    except OSError as exc:
        raise SnapshotError(f"no se pudo borrar {archivo}: {exc}") from exc
