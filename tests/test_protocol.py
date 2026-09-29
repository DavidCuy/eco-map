import pytest

from ecomap_core.protocol import LineDecoder, encode, ev, op


def test_encode_termina_en_salto_de_linea():
    assert encode({"op": "ping"}).endswith(b"\n")


def test_op_y_ev_validan_el_nombre():
    assert op("ping") == {"op": "ping"}
    assert ev("tele", fps=60.0) == {"ev": "tele", "fps": 60.0}
    with pytest.raises(ValueError):
        op("inventado")
    with pytest.raises(ValueError):
        ev("inventado")


def test_decoder_reensambla_mensajes_partidos():
    decoder = LineDecoder()
    payload = encode(op("param", layer=12, key="speed", value=0.7))
    mitad = len(payload) // 2

    assert list(decoder.feed(payload[:mitad])) == []
    mensajes = list(decoder.feed(payload[mitad:]))

    assert mensajes == [{"op": "param", "layer": 12, "key": "speed", "value": 0.7}]


def test_decoder_entrega_varios_de_un_solo_chunk():
    decoder = LineDecoder()
    chunk = encode(op("ping")) + encode(op("blackout", on=True))

    assert list(decoder.feed(chunk)) == [{"op": "ping"}, {"op": "blackout", "on": True}]


def test_decoder_descarta_basura_sin_romperse():
    decoder = LineDecoder()
    chunk = b"{no es json}\n" + encode(op("ping"))

    assert list(decoder.feed(chunk)) == [{"op": "ping"}]
    assert decoder.dropped == 1


def test_decoder_corta_lineas_desmedidas():
    decoder = LineDecoder(max_line_bytes=16)

    assert list(decoder.feed(b"x" * 64)) == []
    assert decoder.dropped == 1
    # Tras descartar, sigue funcionando con el mensaje siguiente.
    assert list(decoder.feed(encode(op("ping")))) == [{"op": "ping"}]
