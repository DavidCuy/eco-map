"""Crear efectos a partir de un archivo subido: imagen, gif o video corto.

Un efecto clasico pinta con codigo. Estos pintan lo que trae un archivo, y aun
asi terminan siendo **el mismo tipo de cosa**: un directorio con `effect.json`,
`frag.glsl` y `preview.jpg`. El shader se genera y se escribe al crearlos.

Esa decision es la que mantiene todo lo demas simple. El render no tiene que
saber que existen dos clases de efecto: carga y compila igual, y lo unico
nuevo es que hay una textura que alimentar cuando el manifiesto declara
`source`. El catalogo, las capas, los parametros y el guardado de escenas
siguen funcionando sin tocarse.

La imagen se puede mover —velocidad y angulo— porque una imagen quieta
proyectada es un cuadro y no un efecto. El gif y el video ya traen su propio
movimiento: agregarles otro encima solo los ensucia, asi que van sin
parametros.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from ecomap_core.effects import (
    EXTENSIONES,
    FRAGMENT_NAME,
    MANIFEST_NAME,
    PREVIEW_NAME,
    MediaKind,
    media_fragment,
    media_params,
)

log = logging.getLogger(__name__)

# Un video corto: lo que entra en memoria del render sin pensarlo mucho y lo
# que una SD aguanta sin llenarse. No es un reproductor de peliculas.
MAX_BYTES = 32 * 1024 * 1024
MAX_SEGUNDOS = 30.0

# Lado mayor del preview del catalogo. El original se conserva intacto.
PREVIEW_LADO = 480


class MediaEffectError(ValueError):
    """El archivo no sirve, o el efecto no se puede crear con ese nombre."""


def id_desde_nombre(nombre: str) -> str:
    """Un id valido para el manifiesto a partir de lo que escribio una persona.

    El id termina siendo un nombre de directorio y una clave en la base, asi
    que se restringe fuerte: sin acentos, sin espacios, sin nada que pueda
    salirse del directorio de efectos.
    """
    base = nombre.strip().lower()
    base = base.replace("á", "a").replace("é", "e").replace("í", "i")
    base = base.replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    if not base or not base[0].isalpha():
        base = f"efecto_{base}" if base else ""
    if not base:
        raise MediaEffectError("el nombre no deja ningun caracter utilizable")
    return base[:40]


def kind_de(nombre_archivo: str) -> MediaKind:
    """Que clase de medio es, por extension."""
    ext = Path(nombre_archivo).suffix.lower()
    for kind, extensiones in EXTENSIONES.items():
        if ext in extensiones:
            return kind  # type: ignore[return-value]
    permitidas = ", ".join(sorted(e for grupo in EXTENSIONES.values() for e in grupo))
    raise MediaEffectError(
        f"extension no soportada: {ext or '(ninguna)'}. Se aceptan: {permitidas}"
    )


def _cv2():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise MediaEffectError("falta OpenCV: instalar el extra `vision`") from exc
    return cv2


def validar_archivo(ruta: Path, kind: MediaKind) -> dict[str, Any]:
    """Comprueba que el archivo se pueda abrir **antes** de crear el efecto.

    Si no, el efecto queda en el catalogo y falla recien al proyectarlo, que
    es el peor momento para enterarse.
    """
    cv2 = _cv2()

    if kind == "image":
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            raise MediaEffectError("no se pudo leer la imagen: puede estar corrupta")
        alto, ancho = imagen.shape[:2]
        return {"width": int(ancho), "height": int(alto), "frames": 1, "duration": 0.0}

    captura = cv2.VideoCapture(str(ruta))
    try:
        if not captura.isOpened():
            raise MediaEffectError(
                "no se pudo abrir el archivo. Si es un gif o un video poco comun, "
                "convertirlo a mp4 suele alcanzar."
            )
        ok, frame = captura.read()
        if not ok or frame is None:
            raise MediaEffectError("el archivo se abrio pero no tiene frames legibles")
        alto, ancho = frame.shape[:2]
        frames = int(captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(captura.get(cv2.CAP_PROP_FPS) or 0)
        duracion = frames / fps if fps > 0 and frames > 0 else 0.0
        if duracion > MAX_SEGUNDOS:
            raise MediaEffectError(
                f"el video dura {duracion:.0f} s y el maximo son {MAX_SEGUNDOS:.0f}: "
                "esto proyecta bucles cortos, no reproduce peliculas"
            )
        return {
            "width": int(ancho),
            "height": int(alto),
            "frames": frames,
            "duration": round(duracion, 2),
            "fps": round(fps, 2),
        }
    finally:
        captura.release()


def _escribir_preview(origen: Path, destino: Path, kind: MediaKind) -> None:
    """El preview del catalogo: la imagen, o el primer frame del video.

    Se genera uno propio en vez de servir el original: un video de 20 MB como
    miniatura de una grilla es absurdo, y el gif animado en el catalogo
    distrae de lo que se esta eligiendo.
    """
    cv2 = _cv2()
    if kind == "image":
        imagen = cv2.imread(str(origen))
    else:
        captura = cv2.VideoCapture(str(origen))
        try:
            _ok, imagen = captura.read()
        finally:
            captura.release()
    if imagen is None:  # pragma: no cover - ya se valido antes
        return

    alto, ancho = imagen.shape[:2]
    escala = PREVIEW_LADO / max(alto, ancho)
    if escala < 1:
        imagen = cv2.resize(
            imagen, (int(ancho * escala), int(alto * escala)), interpolation=cv2.INTER_AREA
        )
    cv2.imwrite(str(destino), imagen, [int(cv2.IMWRITE_JPEG_QUALITY), 80])


def crear(
    effects_dir: Path,
    nombre: str,
    archivo_temporal: Path,
    nombre_original: str,
    tags: list[str] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Arma el directorio del efecto a partir del archivo subido.

    Devuelve el manifiesto escrito. Lanza MediaEffectError si algo no cuadra,
    y en ese caso **no deja nada a medias**: el directorio se borra entero.
    """
    kind = kind_de(nombre_original)
    effect_id = id_desde_nombre(nombre)
    destino = effects_dir / effect_id
    if destino.exists():
        raise MediaEffectError(
            f"ya hay un efecto llamado «{effect_id}». Elegi otro nombre o borra el anterior."
        )

    info = validar_archivo(archivo_temporal, kind)

    extension = Path(nombre_original).suffix.lower()
    media_name = f"media{extension}"
    destino.mkdir(parents=True)
    try:
        shutil.copy2(archivo_temporal, destino / media_name)
        (destino / FRAGMENT_NAME).write_text(media_fragment(kind), encoding="utf-8")
        _escribir_preview(destino / media_name, destino / PREVIEW_NAME, kind)

        params = media_params(kind)
        # La velocidad y el angulo que la persona eligio mirando la
        # previsualizacion quedan como los **valores por defecto** del
        # manifiesto, no como overrides de una capa: son parte de como se
        # definio el efecto, y cualquier capa que lo use arranca asi.
        for param in params:
            if defaults and param["key"] in defaults:
                param["default"] = float(defaults[param["key"]])

        manifiesto = {
            "id": effect_id,
            "name": nombre.strip()[:80],
            "version": "1.0.0",
            "tags": tags or [kind],
            "needs_camera": False,
            # Un video se decodifica frame a frame en el hilo de render: no es
            # gratis, y el presupuesto de frame tiene que reflejarlo.
            "cost": "low" if kind == "image" else "medium",
            "params": params,
            "source": {"kind": kind, "file": media_name},
        }
        (destino / MANIFEST_NAME).write_text(
            json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        # Un efecto a medias en el catalogo es peor que uno que no se creo.
        shutil.rmtree(destino, ignore_errors=True)
        raise

    log.info("efecto %s creado desde %s (%s)", effect_id, nombre_original, kind)
    return {**manifiesto, "media": info}


def borrar(effects_dir: Path, effect_id: str) -> None:
    """Borra el directorio de un efecto subido.

    Solo los que tienen `source`: los que vienen con el sistema no se borran
    desde la web, porque volver a tenerlos significaria reinstalar.
    """
    destino = effects_dir / effect_id
    manifiesto = destino / MANIFEST_NAME
    if not manifiesto.exists():
        raise MediaEffectError(f"no existe el efecto «{effect_id}»")
    try:
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaEffectError(f"no se pudo leer el manifiesto de «{effect_id}»") from exc
    if not datos.get("source"):
        raise MediaEffectError(
            f"«{effect_id}» viene con el sistema y no se borra desde la web"
        )
    shutil.rmtree(destino, ignore_errors=True)
    log.info("efecto %s borrado", effect_id)
