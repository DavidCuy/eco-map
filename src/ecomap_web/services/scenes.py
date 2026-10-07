"""Escenas y capas.

Una **capa** es la asignacion de un efecto a una superficie, con su orden, su
blend y sus parametros. Una **escena** es un conjunto de capas activable de un
golpe.

Esto reemplaza al "efecto activo global" del Hito 1, que era un atajo mientras
no existian las capas: ahora cada superficie puede mostrar algo distinto. El
efecto global sobrevive solo como fallback cuando no hay escena activa, que es
lo que sirve para apuntar el proyector antes de configurar nada.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ecomap_core.protocol import OP_SCENE, op
from ecomap_web.bus import BusClient
from ecomap_web.db import get_setting, set_setting
from ecomap_web.repo import scenes as repo
from ecomap_web.repo import surfaces as surface_repo

# Tope de capas simultaneas. El presupuesto dice 4 en una Pi 4 y 8 en una Pi 5;
# se deja configurable porque la mini PC tiene otro perfil (mas GPU, menos CPU)
# y el numero real sale recien al medir en hardware.
DEFAULT_MAX_LAYERS = 4


class SceneNotFound(LookupError):
    pass


class LayerNotFound(LookupError):
    pass


class TooManyLayers(RuntimeError):
    pass


class InvalidLayer(ValueError):
    pass


# --- escenas -------------------------------------------------------------


def max_layers(conn: sqlite3.Connection) -> int:
    return int(get_setting(conn, "max_layers", str(DEFAULT_MAX_LAYERS)) or DEFAULT_MAX_LAYERS)


def escena_activa(conn: sqlite3.Connection) -> int | None:
    valor = get_setting(conn, "active_scene")
    return int(valor) if valor and valor.isdigit() else None


def listar(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    activa = escena_activa(conn)
    return [
        {
            **escena,
            "is_active": escena["id"] == activa,
            "layers": repo.listar_capas(conn, escena["id"]),
        }
        for escena in repo.listar(conn)
    ]


def obtener(conn: sqlite3.Connection, scene_id: int) -> dict[str, Any]:
    escena = repo.obtener(conn, scene_id)
    if escena is None:
        raise SceneNotFound(scene_id)
    return {
        **escena,
        "is_active": escena["id"] == escena_activa(conn),
        "layers": repo.listar_capas(conn, scene_id),
    }


def crear(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    scene_id = repo.crear(conn, name)
    # La primera escena que existe pasa a ser la activa: si no, el sistema
    # quedaria con escenas creadas y nada proyectando.
    if escena_activa(conn) is None:
        set_setting(conn, "active_scene", str(scene_id))
    return obtener(conn, scene_id)


def renombrar(conn: sqlite3.Connection, scene_id: int, name: str) -> dict[str, Any]:
    obtener(conn, scene_id)
    repo.renombrar(conn, scene_id, name)
    return obtener(conn, scene_id)


def duplicar(conn: sqlite3.Connection, scene_id: int) -> dict[str, Any]:
    origen = obtener(conn, scene_id)
    nuevo = repo.crear(conn, f"{origen['name']} (copia)")
    repo.duplicar_capas(conn, scene_id, nuevo)
    return obtener(conn, nuevo)


def borrar(conn: sqlite3.Connection, scene_id: int) -> None:
    obtener(conn, scene_id)
    repo.borrar(conn, scene_id)  # las capas caen por FK en cascada
    if escena_activa(conn) == scene_id:
        restantes = repo.listar(conn)
        set_setting(conn, "active_scene", str(restantes[0]["id"]) if restantes else "")


def activar(conn: sqlite3.Connection, scene_id: int) -> dict[str, Any]:
    obtener(conn, scene_id)
    set_setting(conn, "active_scene", str(scene_id))
    return obtener(conn, scene_id)


def marcar_default(conn: sqlite3.Connection, scene_id: int) -> dict[str, Any]:
    obtener(conn, scene_id)
    repo.marcar_default(conn, scene_id)
    return obtener(conn, scene_id)


# --- capas ---------------------------------------------------------------


def crear_capa(
    conn: sqlite3.Connection,
    scene_id: int,
    surface_id: int,
    effect_id: str,
    blend_mode: str = "normal",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obtener(conn, scene_id)

    tope = max_layers(conn)
    if repo.contar_capas(conn, scene_id) >= tope:
        raise TooManyLayers(
            f"la escena ya tiene {tope} capas, que es el tope configurado en "
            "`max_layers`. Mas capas significa mas FBO por frame; el numero real "
            "sale de medir en el hardware de destino."
        )

    if surface_repo.obtener(conn, surface_id) is None:
        raise InvalidLayer(f"la superficie {surface_id} no existe")
    fila = conn.execute("SELECT available FROM effect WHERE id = ?", (effect_id,)).fetchone()
    if fila is None:
        raise InvalidLayer(f"el efecto {effect_id!r} no esta en el catalogo")
    if not fila["available"]:
        raise InvalidLayer(f"el efecto {effect_id!r} no esta disponible")

    layer_id = repo.crear_capa(
        conn,
        scene_id,
        surface_id,
        effect_id,
        repo.proximo_z(conn, scene_id),
        blend_mode,
        params or {},
    )
    return _capa(conn, layer_id)


def actualizar_capa(
    conn: sqlite3.Connection, layer_id: int, campos: dict[str, Any]
) -> dict[str, Any]:
    capa = _capa(conn, layer_id)
    permitidos: dict[str, Any] = {}
    if campos.get("blend_mode") is not None:
        permitidos["blend_mode"] = campos["blend_mode"]
    if campos.get("enabled") is not None:
        permitidos["enabled"] = int(bool(campos["enabled"]))
    if campos.get("params") is not None:
        # Mezcla parcial, igual que con el efecto activo: mover un slider no
        # pisa el resto de los valores.
        permitidos["params"] = {**capa["params"], **campos["params"]}
    repo.actualizar_capa(conn, layer_id, permitidos)
    return _capa(conn, layer_id)


def borrar_capa(conn: sqlite3.Connection, layer_id: int) -> int:
    capa = _capa(conn, layer_id)
    repo.borrar_capa(conn, layer_id)
    return int(capa["scene_id"])


def reordenar(conn: sqlite3.Connection, scene_id: int, layer_ids: list[int]) -> dict[str, Any]:
    escena = obtener(conn, scene_id)
    actuales = {capa["id"] for capa in escena["layers"]}
    if set(layer_ids) != actuales:
        raise InvalidLayer("el reordenamiento tiene que incluir exactamente las capas de la escena")
    repo.reordenar(conn, scene_id, layer_ids)
    return obtener(conn, scene_id)


def mover_capa(conn: sqlite3.Connection, layer_id: int, direccion: str) -> dict[str, Any]:
    """Sube o baja una capa un lugar en el apilado.

    Existe ademas del reordenamiento completo porque es lo que la UI necesita:
    calcular la lista entera en la plantilla para mover un elemento es ilegible,
    y el intercambio de dos vecinos es exactamente lo que el usuario pide.
    """
    capa = _capa(conn, layer_id)
    escena = obtener(conn, capa["scene_id"])
    ids = [c["id"] for c in escena["layers"]]
    i = ids.index(layer_id)
    j = i - 1 if direccion == "down" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        repo.reordenar(conn, capa["scene_id"], ids)
    return obtener(conn, capa["scene_id"])


def _capa(conn: sqlite3.Connection, layer_id: int) -> dict[str, Any]:
    capa = repo.obtener_capa(conn, layer_id)
    if capa is None:
        raise LayerNotFound(layer_id)
    return capa


# --- escena hacia el render ---------------------------------------------


def serializar(conn: sqlite3.Connection) -> dict[str, Any]:
    """La escena activa tal como la necesita el render.

    Va la geometria de la superficie **dentro** de cada capa: el render no
    tiene indice de superficies ni le sirve tenerlo, y asi un solo mensaje
    alcanza para redibujar todo.

    Se filtran las capas deshabilitadas, las de superficies deshabilitadas y
    las que apuntan a un efecto no disponible. El render no tiene que razonar
    sobre eso: recibe lo que se dibuja.
    """
    scene_id = escena_activa(conn)
    superficies = {s["id"]: s for s in surface_repo.listar(conn)}
    capas = []

    if scene_id is not None:
        for capa in repo.listar_capas(conn, scene_id):
            superficie = superficies.get(capa["surface_id"])
            if not capa["enabled"] or superficie is None or not superficie["enabled"]:
                continue
            if not capa["effect_available"]:
                continue
            capas.append(
                {
                    "id": capa["id"],
                    "effect": capa["effect_id"],
                    "params": capa["params"],
                    "blend": capa["blend_mode"],
                    "surface": {
                        "id": superficie["id"],
                        "cols": superficie["mesh_cols"],
                        "rows": superficie["mesh_rows"],
                        "points": superficie["points"],
                        "opacity": superficie["opacity"],
                    },
                }
            )

    return {
        "scene_id": scene_id,
        "calibration_version": int(get_setting(conn, "calibration_version", "1") or 1),
        "layers": capas,
        # Fallback para cuando no hay capas: el efecto global a pantalla
        # completa, que es lo que sirve para apuntar el proyector.
        "fallback_effect": get_setting(conn, "active_effect") or None,
        "fallback_params": json.loads(get_setting(conn, "active_effect_params", "{}") or "{}"),
    }


async def push(bus: BusClient, conn: sqlite3.Connection) -> bool:
    return await bus.send(op(OP_SCENE, scene=serializar(conn)))
