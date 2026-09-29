"""Ida y vuelta real entre el BusServer del render y el BusClient del web.

Se usa TCP en localhost para que el test corra igual en Linux y en Windows
(donde CPython no expone AF_UNIX).
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from ecomap_core.protocol import EV_TELE, OP_PING, ev, op
from ecomap_render.bus import BusServer
from ecomap_web.bus import BusClient


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _esperar(condicion, timeout: float = 3.0) -> bool:
    limite = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < limite:
        if condicion():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.fixture
async def par():
    puerto = _puerto_libre()
    direccion = ("tcp", "127.0.0.1", puerto)
    servidor = BusServer(direccion)
    servidor.start()
    cliente = BusClient(direccion)
    await cliente.start()
    assert await _esperar(lambda: cliente.connected)
    try:
        yield servidor, cliente
    finally:
        await cliente.stop()
        servidor.stop()


async def test_operacion_del_web_llega_al_render(par):
    servidor, cliente = par
    recibidos: list[dict] = []

    def llego() -> bool:
        recibidos.extend(servidor.poll())
        return bool(recibidos)

    assert await cliente.send(op(OP_PING))
    assert await _esperar(llego)
    assert recibidos == [{"op": "ping"}]


async def test_evento_del_render_llega_al_web(par):
    servidor, cliente = par
    eventos: list[dict] = []
    cliente.subscribe(eventos.append)

    servidor.publish(ev(EV_TELE, fps=59.4, frame_ms=16.8))
    assert await _esperar(lambda: bool(eventos))

    assert eventos[0]["ev"] == EV_TELE
    assert eventos[0]["fps"] == 59.4


async def test_send_devuelve_false_sin_render():
    cliente = BusClient(("tcp", "127.0.0.1", _puerto_libre()))
    await cliente.start()
    try:
        assert await cliente.send(op(OP_PING)) is False
        assert cliente.connected is False
    finally:
        await cliente.stop()


async def test_el_cliente_reconecta_si_el_render_vuelve():
    puerto = _puerto_libre()
    direccion = ("tcp", "127.0.0.1", puerto)
    cliente = BusClient(direccion)
    conexiones: list[int] = []

    async def on_connect() -> None:
        conexiones.append(1)

    cliente.on_connect = on_connect
    await cliente.start()

    primero = BusServer(direccion)
    primero.start()
    assert await _esperar(lambda: cliente.connected)
    primero.stop()
    assert await _esperar(lambda: not cliente.connected)

    segundo = BusServer(direccion)
    segundo.start()
    try:
        assert await _esperar(lambda: cliente.connected, timeout=5.0)
        assert len(conexiones) >= 2
    finally:
        await cliente.stop()
        segundo.stop()


async def test_publicar_sin_cliente_no_rompe():
    servidor = BusServer(("tcp", "127.0.0.1", _puerto_libre()))
    servidor.start()
    try:
        servidor.publish(ev(EV_TELE, fps=0.0))  # nadie conectado: se descarta
        assert servidor.poll() == []
    finally:
        servidor.stop()
