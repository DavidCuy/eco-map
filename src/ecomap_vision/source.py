"""Fuentes de camara.

Webcam USB (ADR-010) y fuentes simuladas para desarrollar sin hardware. Lo que
hay aca es lo necesario para **abrir, verificar y cerrar** una camara, que es lo
que el selector del dashboard necesita para dar una respuesta honesta.

El backend va en el esquema de la URI y no se adivina. OpenCV elige uno solo si
no se le dice cual, y cual elige cambia entre instalaciones: con eso, la misma
camara da 30 fps en un equipo y 5 en otro sin que nada lo explique.

URIs aceptadas:
    fake://                     patron sintetico
    loopback://                 banco virtual: lo que el proyector dibuja,
                                deformado (solo dentro del render)
    fake:///ruta/video.mp4      archivo reproducido en loop (requiere OpenCV)
    v4l2:///dev/video0          webcam en Linux
    v4l2:///dev/v4l/by-id/...   webcam en Linux por ruta estable (preferida)
    dshow://0                   webcam en Windows por DirectShow (preferida)
    msmf://0                    webcam en Windows por Media Foundation

En Windows la camara se direcciona por **indice**, no por ruta: no hay nada
equivalente a `/dev/v4l/by-id`, asi que el indice puede cambiar al enchufar otra
camara. Es una limitacion de la plataforma, y parte de por que el appliance va
sobre la Pi y no sobre Windows.

DirectShow antes que Media Foundation porque MSMF tarda segundos en abrir,
suele ignorar el pedido de MJPG y expone menos controles. Queda igual
disponible: hay camaras que andan con uno y no con el otro, y cuando pasa,
poder cambiar de backend desde la URI evita quedarse sin camara.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 15


class CameraError(RuntimeError):
    """La camara no se pudo abrir o leer."""


@dataclass
class CameraInfo:
    uri: str
    width: int
    height: int
    fps: float
    backend: str
    # Formato que el driver entrega de verdad. Vacio cuando la fuente no es una
    # camara real. Si no es MJPG, los fps los limita el bus USB (ADR-010).
    fourcc: str = ""


class CameraSource(Protocol):
    info: CameraInfo

    def read(self) -> Any | None: ...

    def close(self) -> None: ...


class FakeSource:
    """Patron sintetico o archivo de video. Permite desarrollar sin camara."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._capture = None
        self._frame = 0
        if path:
            cv2 = _import_cv2()
            capture = cv2.VideoCapture(path)
            if not capture.isOpened():
                raise CameraError(f"no se pudo abrir el video simulado: {path}")
            self._capture = capture
            self._cv2 = cv2
            ancho = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or DEFAULT_WIDTH
            alto = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or DEFAULT_HEIGHT
            fps = float(capture.get(cv2.CAP_PROP_FPS)) or DEFAULT_FPS
        else:
            ancho, alto, fps = DEFAULT_WIDTH, DEFAULT_HEIGHT, float(DEFAULT_FPS)
        self.info = CameraInfo(
            uri=f"fake://{path or ''}",
            width=ancho,
            height=alto,
            fps=fps,
            backend="fake",
        )

    def read(self) -> Any | None:
        if self._capture is not None:
            ok, frame = self._capture.read()
            if not ok:  # fin del archivo: vuelve al principio
                self._capture.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._capture.read()
            return frame if ok else None

        import numpy as np

        self._frame += 1
        # Degradado que se desplaza: sirve para ver que los frames avanzan.
        # El desfase se reduce antes de sumarlo: NumPy 2 ya no hace el casting
        # por valor, asi que sumar un entero mayor que 255 a un array uint8
        # lanza OverflowError. Pasaba en el frame 256, o sea a los 17 segundos
        # a 15 fps, que es mas de lo que dura cualquier test.
        desfase = np.uint8(self._frame % 256)
        fila = (np.arange(self.info.width, dtype=np.uint8) + desfase) % 255
        frame = np.tile(fila, (self.info.height, 1))
        return np.dstack([frame, np.roll(frame, 40), np.roll(frame, 80)])

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


# Esquema de URI -> nombre de la constante de backend en cv2. Se resuelve por
# nombre y no importando la constante: una build de OpenCV sin DirectShow no
# tiene `CAP_DSHOW`, y eso tiene que dar un error que se entienda, no un
# AttributeError al abrir.
BACKENDS = {
    "v4l2": "CAP_V4L2",
    "dshow": "CAP_DSHOW",
    "msmf": "CAP_MSMF",
}

# Por que no abrio, segun el backend. Las causas no se parecen entre
# plataformas, y mandar al operador a buscar al lugar equivocado cuesta mas que
# no decir nada.
MOTIVOS = {
    "v4l2": (
        "no existe, esta en uso, o no esta montado dentro del contenedor "
        "(falta el --device o el grupo video)"
    ),
    "dshow": (
        "no hay camara con ese indice, otra aplicacion la tiene tomada, o "
        "Windows bloquea el acceso en Privacidad > Camara"
    ),
    "msmf": (
        "no hay camara con ese indice, otra aplicacion la tiene tomada, o "
        "Windows bloquea el acceso en Privacidad > Camara. MSMF ademas tarda "
        "varios segundos en abrir: conviene probar con dshow://"
    ),
}

# Valor de CAP_PROP_AUTO_EXPOSURE para pedir modo manual. No hay forma de
# escribir esto sin tabla: V4L2 usa el enum de la API (1 = manual, 3 = auto) y
# DirectShow usa la convencion de DirectShow (0.25 = manual, 0.75 = auto).
AUTO_EXPOSURE_MANUAL = {"v4l2": 1.0, "dshow": 0.25, "msmf": 0.25}
AUTO_EXPOSURE_AUTO = {"v4l2": 3.0, "dshow": 0.75, "msmf": 0.75}


class OpenCVSource:
    """Webcam USB, por V4L2 en Linux o DirectShow / Media Foundation en Windows.

    MJPG es obligatorio: con YUYV sin comprimir el ancho de banda USB limita a
    pocos fps (ADR-010). `BUFFERSIZE=1` lo respetan los drivers de forma
    desigual, asi que el consumidor debe descartar frames si la latencia crece.
    """

    def __init__(
        self,
        device: str,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fps: int = DEFAULT_FPS,
        backend: str = "v4l2",
    ) -> None:
        cv2 = _import_cv2()
        self._cv2 = cv2
        self.backend = backend
        api = _backend_const(cv2, backend)
        # En Windows el device es un indice; en Linux, una ruta.
        destino: str | int = int(device) if str(device).isdigit() else device
        capture = cv2.VideoCapture(destino, api)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"no se pudo abrir {backend}://{device}: {MOTIVOS[backend]}")
        # Resolucion **antes** que formato, y no al reves. Medido con
        # DirectShow sobre una webcam real: pidiendo MJPG primero y el tamano
        # despues, el driver termina entregando YUY2 — el cambio de tamano
        # renegocia el formato y se pierde lo pedido. Con este orden entrega
        # MJPG, que es la diferencia entre 10 fps y 30 (ADR-010).
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, fps)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("M", "J", "P", "G"))
        # Y al reves tambien pasa en algunos drivers: cambiar el formato les
        # mueve el tamano. Se reafirma solo si hizo falta.
        if int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) != width:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        ok, _ = capture.read()
        if not ok:
            capture.release()
            raise CameraError(
                f"{backend}://{device} se abrio pero no entrega frames. "
                "Suele ser otra aplicacion que ya la tiene tomada."
            )

        self._capture = capture
        self.info = CameraInfo(
            uri=f"{backend}://{device}",
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or width,
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height,
            fps=float(capture.get(cv2.CAP_PROP_FPS)) or float(fps),
            backend=backend,
            fourcc=self.fourcc,
        )

    @property
    def fourcc(self) -> str:
        """El formato que el driver termino dando, no el que se pidio.

        Pedir MJPG no garantiza obtenerlo. Si sale `YUY2`, los fps van a estar
        limitados por el ancho de banda USB por mas que `CAP_PROP_FPS` diga otra
        cosa, y es lo primero que hay que mirar cuando la captura va lenta. En
        Windows no existe `v4l2-ctl`, asi que esto es lo unico que lo dice.
        """
        valor = int(self._capture.get(self._cv2.CAP_PROP_FOURCC))
        if valor <= 0:
            return ""
        return "".join(chr((valor >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00 ")

    def set_auto_exposure(self, automatica: bool) -> str:
        """Pide exposicion automatica o manual. Devuelve que se pudo comprobar.

        Tres resultados, y la diferencia importa:

        - `"aplicado"`: se releyo la propiedad y quedo en lo pedido.
        - `"ignorado"`: se releyo y quedo en otra cosa. La camara acepta el
          control y no lo obedece, que es lo comun en webcams baratas.
        - `"sin_confirmar"`: el driver no deja leer la propiedad (devuelve -1).
          Puede haber funcionado o no; no hay forma de saberlo desde OpenCV, y
          decir "ignorado" seria inventar.

        Importa para el Gray code: la secuencia compara cada patron contra su
        inverso, y si la camara reajusta el brillo entre una captura y la
        siguiente, los dos dejan de ser comparables y la calibracion falla sin
        decir por que.
        """
        tabla = AUTO_EXPOSURE_AUTO if automatica else AUTO_EXPOSURE_MANUAL
        objetivo = tabla[self.backend]
        self._capture.set(self._cv2.CAP_PROP_AUTO_EXPOSURE, objetivo)
        leido = self._capture.get(self._cv2.CAP_PROP_AUTO_EXPOSURE)
        modo = "automatica" if automatica else "manual"

        if leido < 0:
            log.warning(
                "camara %s: pedi exposicion %s y el driver no deja leer el "
                "control para confirmarlo. Si la auto-calibracion falla con "
                "los patrones aplanados, es por aca.",
                self.info.uri,
                modo,
            )
            return "sin_confirmar"

        # Margen amplio: algunos drivers devuelven el valor redondeado o
        # reescalado, y lo que interesa es si cambio de modo, no el numero.
        if abs(leido - objetivo) < 0.5:
            return "aplicado"

        log.warning(
            "camara %s: pedi exposicion %s y quedo en %.2f (esperaba %.2f). "
            "La camara ignora el control; la auto-calibracion puede fallar.",
            self.info.uri,
            modo,
            leido,
            objetivo,
        )
        return "ignorado"

    def controls(self) -> dict[str, float]:
        """Lo que el driver reporta de los controles que afectan al Gray code.

        Es el reemplazo de `v4l2-ctl --list-ctrls` donde no hay v4l2-ctl. Un
        valor en 0 o -1 suele significar "no soportado", no "apagado": OpenCV no
        distingue una cosa de la otra, asi que esto se lee como indicio.
        """
        cv2 = self._cv2
        propiedades = {
            "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
            "exposure": cv2.CAP_PROP_EXPOSURE,
            "auto_wb": cv2.CAP_PROP_AUTO_WB,
            "wb_temperature": cv2.CAP_PROP_WB_TEMPERATURE,
            "gain": cv2.CAP_PROP_GAIN,
            "brightness": cv2.CAP_PROP_BRIGHTNESS,
        }
        valores: dict[str, float] = {}
        for nombre, prop in propiedades.items():
            try:
                valores[nombre] = float(self._capture.get(prop))
            except Exception:  # noqa: BLE001 - un control no soportado no es un error
                continue
        return valores

    def read(self) -> Any | None:
        ok, frame = self._capture.read()
        return frame if ok else None

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def _backend_const(cv2, backend: str) -> int:
    nombre = BACKENDS.get(backend)
    if nombre is None:
        raise CameraError(f"backend de camara desconocido: {backend!r}")
    api = getattr(cv2, nombre, None)
    if api is None:  # pragma: no cover - depende de como se compilo OpenCV
        raise CameraError(f"esta instalacion de OpenCV no trae el backend {backend} ({nombre})")
    return int(api)


def _import_cv2():
    """Import perezoso: el render sin camara no deberia necesitar OpenCV."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise CameraError("OpenCV no esta instalado: instalar el extra `vision`") from exc
    return cv2


def open_source(uri: str, **kwargs: Any) -> CameraSource:
    """Abre la fuente que describe `uri`. Lanza CameraError si no se puede."""
    parsed = urlparse(uri)
    esquema = parsed.scheme or "fake"
    ruta = parsed.path or ""

    if esquema == "fake":
        return FakeSource(ruta or None)
    if esquema == "loopback":
        from ecomap_vision.loopback import from_uri

        return from_uri(uri)
    if esquema in BACKENDS:
        # `dshow://0` deja el indice en netloc y no en path: urlparse trata lo
        # que sigue a `//` como host, y "0" es un host valido.
        destino = ruta or parsed.netloc
        if not destino:
            raise CameraError(f"uri de camara sin device: {uri!r}")
        return OpenCVSource(destino, backend=esquema, **kwargs)
    raise CameraError(f"esquema de camara desconocido: {esquema!r}")
