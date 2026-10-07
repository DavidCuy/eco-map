"""Escritura diferida a SQLite.

Mover un slider genera decenas de valores por segundo. El valor **siempre**
viaja al render por el socket, porque eso es lo que se ve; lo que se difiere es
la escritura en disco, que no aporta nada en el medio de un arrastre y desgasta
la tarjeta (ADR-004: en la Pi, la SD es la causa número uno de muerte).

Lo que importa de este diseño:

- Nunca se pierde el último valor: se vuelca al cerrar la app.
- Nunca se bloquea al que escribe: se programa y se sigue.
- Una clave con muchas escrituras seguidas termina en **una sola** escritura.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.5


class DebouncedWriter:
    """Agrupa escrituras por clave y las vuelca cuando se calman."""

    def __init__(self, delay: float = DEBOUNCE_SECONDS) -> None:
        self.delay = delay
        self._pendientes: dict[str, tuple[Callable[[], None], Any]] = {}
        self._tareas: dict[str, asyncio.Task[None]] = {}
        self.writes = 0  # para poder afirmar en tests que de verdad se agrupan

    def schedule(self, key: str, write: Callable[[], None]) -> None:
        """Programa `write` para dentro de `delay`. Si llega otra para la misma
        clave antes, la reemplaza: solo sobrevive la ultima."""
        self._pendientes[key] = (write, None)
        tarea = self._tareas.get(key)
        if tarea and not tarea.done():
            tarea.cancel()
        self._tareas[key] = asyncio.create_task(self._esperar(key))

    async def _esperar(self, key: str) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        self._volcar(key)

    def _volcar(self, key: str) -> None:
        entrada = self._pendientes.pop(key, None)
        self._tareas.pop(key, None)
        if entrada is None:
            return
        write, _ = entrada
        try:
            write()
            self.writes += 1
        except Exception:  # noqa: BLE001 - una escritura fallida no debe tumbar el web
            log.exception("escritura diferida fallida: %s", key)

    async def flush(self) -> None:
        """Vuelca todo lo pendiente. Se llama al cerrar: el ultimo valor de un
        arrastre no se puede perder porque el usuario cerro la pestana."""
        for tarea in list(self._tareas.values()):
            tarea.cancel()
        for key in list(self._pendientes):
            self._volcar(key)
