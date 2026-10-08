"""Enumeracion de camaras disponibles.

Solo stdlib y **sin abrir los devices**: lo usa el proceso web para armar el
selector, mientras el que realmente abre la camara es el render, que es quien
la tiene. Abrir una camara desde el web se la quitaria al render, y en Windows
ademas tarda segundos. Ver Modulo-Camara-Feedback.

Dos caminos, segun la plataforma:

- **Linux**: lee `/sys/class/video4linux`. Da nombre, nodo y la ruta estable de
  `/dev/v4l/by-id`, que es la que conviene guardar porque el indice `/dev/videoN`
  cambia entre arranques (ADR-010).
- **Windows**: pregunta a CIM por los dispositivos de clase `Camera`. Windows no
  tiene nada equivalente a `by-id`: la camara se direcciona por indice de
  DirectShow y punto.
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SYSFS_V4L = Path("/sys/class/video4linux")
DEV_BY_ID = Path("/dev/v4l/by-id")

FAKE_URI = "fake://"

# Nombres de las camaras presentes, en el orden en que CIM las devuelve. Se
# filtra por Status para no listar una camara desenchufada que Windows recuerda.
PS_CAMARAS = (
    "Get-CimInstance Win32_PnPEntity "
    "| Where-Object { $_.PNPClass -eq 'Camera' -and $_.Status -eq 'OK' } "
    "| Select-Object -ExpandProperty Name "
    "| ConvertTo-Json -Compress"
)
PS_TIMEOUT = 10.0


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
        if self.node is None:
            # Windows: no hay nodo, solo el indice que ya viaja en la URI.
            return f"{self.name} (indice {self.uri.rsplit('/', 1)[-1]})"
        return f"{self.name} ({Path(self.node).name})"


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


def _nombres_windows() -> list[str]:
    """Nombres de las camaras presentes, preguntandole a CIM.

    Via PowerShell y no por un modulo COM a proposito: no agrega dependencias y
    el proceso web no necesita hablar DirectShow para armar un selector.
    """
    try:
        salida = subprocess.run(  # noqa: S603 - comando fijo, sin entrada del usuario
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_CAMARAS],
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("no se pudieron enumerar las camaras de Windows: %s", exc)
        return []
    crudo = salida.stdout.strip()
    if not crudo:
        return []
    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError:
        log.warning("respuesta inesperada al enumerar camaras: %r", crudo[:200])
        return []
    # ConvertTo-Json devuelve un escalar cuando hay una sola camara.
    if isinstance(datos, str):
        return [datos]
    return [str(d) for d in datos if d]


def _enumerar_windows() -> list[CameraDevice]:
    """Camaras en Windows, como `dshow://N`.

    **El indice es una suposicion.** CIM da los nombres pero no el indice de
    DirectShow, y no hay forma de obtener el mapeo sin abrir cada camara, que
    es justo lo que este modulo no hace. Se emparejan por orden, que es lo que
    suele coincidir.

    Con una sola camara no hay ambiguedad posible. Con varias, si la elegida no
    es la que se esperaba, la de al lado lo es: el selector las muestra todas y
    el render dice cual abrio de verdad.
    """
    return [
        CameraDevice(uri=f"dshow://{indice}", name=nombre, kind="dshow")
        for indice, nombre in enumerate(_nombres_windows())
    ]


def _enumerar_v4l2(sysfs_root: Path, by_id_dir: Path) -> list[CameraDevice]:
    """Camaras en Linux, leyendo sysfs.

    Se queda con los nodos cuyo `index` es 0: una webcam suele exponer varios
    (`video0` captura, `video1` metadatos) y solo el primero sirve para
    capturar. Es una heuristica, no una consulta de capacidades V4L2: alcanza
    para poblar el selector, y el render reporta un error claro si el device
    elegido no sirve.
    """
    try:
        candidatos = sorted(sysfs_root.iterdir(), key=lambda p: p.name)
    except OSError:
        return []  # no hay devices V4L2

    dispositivos: list[CameraDevice] = []
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
    return dispositivos


def enumerate_cameras(
    sysfs_root: Path | None = None,
    by_id_dir: Path | None = None,
    include_fake: bool = True,
    system: str | None = None,
) -> list[CameraDevice]:
    """Lista las camaras de captura detectadas, segun la plataforma."""
    system = system or platform.system()

    if system == "Windows":
        dispositivos = _enumerar_windows()
    else:
        dispositivos = _enumerar_v4l2(sysfs_root or SYSFS_V4L, by_id_dir or DEV_BY_ID)

    if include_fake:
        dispositivos.append(FAKE_DEVICE)
    return dispositivos
