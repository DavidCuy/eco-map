"""Enumeracion de camaras disponibles.

Solo stdlib: lee sysfs, no abre los devices ni necesita OpenCV. Lo usa el
proceso web para armar el selector, mientras el que realmente abre la camara es
el render (es quien tiene el device montado). Ver Modulo-Camara-Feedback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SYSFS_V4L = Path("/sys/class/video4linux")
DEV_BY_ID = Path("/dev/v4l/by-id")

FAKE_URI = "fake://"


@dataclass(frozen=True)
class CameraDevice:
    uri: str
    name: str
    node: str | None = None
    stable_path: str | None = None
    kind: str = "v4l2"

    @property
    def label(self) -> str:
        if self.kind == "fake":
            return self.name
        nodo = Path(self.node).name if self.node else "?"
        return f"{self.name} ({nodo})"


FAKE_DEVICE = CameraDevice(
    uri=FAKE_URI,
    name="Camara simulada",
    kind="fake",
)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _stable_path_for(node: str, by_id_dir: Path) -> str | None:
    """Busca el symlink estable de /dev/v4l/by-id que apunta a este nodo.

    El indice /dev/videoN cambia entre arranques, asi que para configurar
    conviene guardar la ruta estable (ADR-010).
    """
    try:
        entradas = sorted(by_id_dir.iterdir())
    except OSError:
        return None
    for entrada in entradas:
        try:
            if entrada.resolve() == Path(node).resolve():
                return str(entrada)
        except OSError:
            continue
    return None


def enumerate_cameras(
    sysfs_root: Path | None = None,
    by_id_dir: Path | None = None,
    include_fake: bool = True,
) -> list[CameraDevice]:
    """Lista las camaras de captura detectadas.

    Se queda con los nodos cuyo `index` es 0: una webcam suele exponer varios
    (`video0` captura, `video1` metadatos) y solo el primero sirve para
    capturar. Es una heuristica, no una consulta de capacidades V4L2: alcanza
    para poblar el selector, y el render reporta un error claro si el device
    elegido no sirve.
    """
    sysfs_root = sysfs_root or SYSFS_V4L
    by_id_dir = by_id_dir or DEV_BY_ID

    dispositivos: list[CameraDevice] = []
    try:
        candidatos = sorted(sysfs_root.iterdir(), key=lambda p: p.name)
    except OSError:
        candidatos = []  # no es Linux, o no hay devices V4L2

    for entrada in candidatos:
        if not entrada.name.startswith("video"):
            continue
        indice = _read(entrada / "index")
        if indice is not None and indice != "0":
            continue
        nombre = _read(entrada / "name") or entrada.name
        nodo = f"/dev/{entrada.name}"
        estable = _stable_path_for(nodo, by_id_dir)
        dispositivos.append(
            CameraDevice(
                uri=f"v4l2://{estable or nodo}",
                name=nombre,
                node=nodo,
                stable_path=estable,
            )
        )

    if include_fake:
        dispositivos.append(FAKE_DEVICE)
    return dispositivos
