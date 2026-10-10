"""Texturas de los efectos hechos a partir de un archivo.

Una imagen se sube a GPU una vez y se queda. Un gif o un video hay que
decodificarlos frame a frame **dentro del loop de render**, que es donde esto
puede doler: si un video de 1080p tarda 15 ms en decodificar, se come la mitad
del presupuesto de frame.

Tres decisiones por eso:

- **Se reduce al subir a GPU**, no al proyectar. Un video 4K de origen se
  guarda como viene pero la textura es de a lo sumo `MAX_LADO`: lo que importa
  es cuanto ocupa en la cara, no el archivo.
- **El avance va por reloj de pared**, no por frame de render. El video se ve a
  su velocidad aunque el render vaya a 30 o a 60, y si el render se atrasa el
  video no se pone en camara lenta.
- **Un frame que no llega no corta nada**: se repite el anterior. Un bucle que
  parpadea es peor que uno que se traba un cuadro.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import moderngl

from ecomap_core.effects import Effect

log = logging.getLogger(__name__)

# Lado mayor de la textura. Mas que esto no se nota proyectado sobre una cara
# y cuesta memoria y ancho de banda en cada subida.
MAX_LADO = 1024

# Si el archivo no declara fps, se asume esto. Un gif sin metadatos es comun.
FPS_POR_DEFECTO = 15.0


def _cv2():
    try:
        import cv2
    except ImportError:  # pragma: no cover - depende del entorno
        return None
    return cv2


def _reducir(cv2, frame: Any) -> Any:
    alto, ancho = frame.shape[:2]
    escala = MAX_LADO / max(alto, ancho)
    if escala >= 1:
        return frame
    return cv2.resize(
        frame, (int(ancho * escala), int(alto * escala)), interpolation=cv2.INTER_AREA
    )


class MediaTexture:
    """La textura de un efecto con `source`, y como se mantiene al dia."""

    def __init__(self, ctx: moderngl.Context, ruta: Path, kind: str) -> None:
        self.ctx = ctx
        self.ruta = ruta
        self.kind = kind
        self.texture: moderngl.Texture | None = None
        self.error: str | None = None
        self._captura: Any = None
        self._periodo = 1.0 / FPS_POR_DEFECTO
        self._proximo = 0.0

        cv2 = _cv2()
        if cv2 is None:
            self.error = "sin OpenCV no se pueden cargar efectos de archivo"
            return
        try:
            self._abrir(cv2)
        except Exception as exc:  # noqa: BLE001 - un archivo malo no tumba el render
            self.error = f"{ruta.name}: {exc}"
            log.warning("media: %s", self.error)

    def _abrir(self, cv2) -> None:
        if self.kind == "image":
            imagen = cv2.imread(str(self.ruta))
            if imagen is None:
                raise ValueError("no se pudo leer la imagen")
            self._subir(cv2, imagen)
            return

        captura = cv2.VideoCapture(str(self.ruta))
        if not captura.isOpened():
            raise ValueError("no se pudo abrir el video")
        self._captura = captura
        fps = float(captura.get(cv2.CAP_PROP_FPS) or 0)
        self._periodo = 1.0 / fps if fps > 0 else 1.0 / FPS_POR_DEFECTO
        ok, frame = captura.read()
        if not ok or frame is None:
            raise ValueError("el video no tiene frames")
        self._subir(cv2, frame)
        self._proximo = time.perf_counter() + self._periodo

    def _subir(self, cv2, frame: Any) -> None:
        frame = _reducir(cv2, frame)
        alto, ancho = frame.shape[:2]
        # BGR -> RGB y el origen abajo, que es lo que espera GL.
        datos = frame[::-1, :, ::-1].copy()
        if self.texture is None or self.texture.size != (ancho, alto):
            if self.texture is not None:
                self.texture.release()
            self.texture = self.ctx.texture((ancho, alto), components=3)
            self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            # Se repite: el desplazamiento de una imagen usa `fract`, y sin
            # repeticion el borde se estira en vez de volver a empezar.
            self.texture.repeat_x = True
            self.texture.repeat_y = True
        self.texture.write(datos.tobytes())

    def tick(self) -> None:
        """Avanza el video si toca. Para una imagen no hace nada."""
        if self._captura is None or self.texture is None:
            return
        ahora = time.perf_counter()
        if ahora < self._proximo:
            return

        cv2 = _cv2()
        ok, frame = self._captura.read()
        if not ok or frame is None:
            # Fin del archivo: vuelve al principio. Son bucles cortos.
            self._captura.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._captura.read()
        if ok and frame is not None:
            self._subir(cv2, frame)

        # Sobre el instante ideal y no sobre "ahora": sumar desde ahora
        # acumula el retraso de cada frame y el video se va atrasando solo.
        self._proximo += self._periodo
        if self._proximo < ahora:
            # Se perdieron varios periodos (el render se trabo): se resincroniza
            # en vez de intentar recuperarlos todos de golpe.
            self._proximo = ahora + self._periodo

    def release(self) -> None:
        if self.texture is not None:
            self.texture.release()
            self.texture = None
        if self._captura is not None:
            self._captura.release()
            self._captura = None


class MediaLibrary:
    """Las texturas de todos los efectos con `source`, por id de efecto."""

    def __init__(self, ctx: moderngl.Context) -> None:
        self.ctx = ctx
        self.medios: dict[str, MediaTexture] = {}
        # Textura negra para los efectos sin archivo: un sampler sin enlazar
        # da resultado indefinido, y en algunos drivers basura en pantalla.
        self.vacia = ctx.texture((1, 1), components=3, data=bytes(3))

    def sync(self, efectos: list[Effect]) -> None:
        """Carga lo que falte y suelta lo que ya no esta en el catalogo."""
        con_fuente = {e.id: e for e in efectos if e.manifest.source is not None}

        for effect_id in list(self.medios):
            if effect_id not in con_fuente:
                self.medios.pop(effect_id).release()

        for effect_id, efecto in con_fuente.items():
            if effect_id in self.medios:
                continue
            fuente = efecto.manifest.source
            assert fuente is not None
            self.medios[effect_id] = MediaTexture(
                self.ctx, efecto.directory / fuente.file, fuente.kind
            )

        if self.medios:
            log.info("media: %d efectos con archivo (%s)", len(self.medios), ", ".join(self.medios))

    def tick(self) -> None:
        """Una vez por frame: avanza los videos que toquen."""
        for medio in self.medios.values():
            medio.tick()

    def bind(self, effect_id: str, location: int) -> None:
        medio = self.medios.get(effect_id)
        textura = medio.texture if medio and medio.texture is not None else self.vacia
        textura.use(location=location)

    @property
    def errors(self) -> dict[str, str]:
        return {i: m.error for i, m in self.medios.items() if m.error}

    def release(self) -> None:
        for medio in self.medios.values():
            medio.release()
        self.medios.clear()
        self.vacia.release()
