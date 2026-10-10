"""Efectos hechos a partir de un archivo: imagen, gif y video corto.

Lo que se prueba acá es que terminen siendo **un efecto como cualquier otro**:
directorio con manifiesto, shader y preview. Esa es la decision que mantiene
simple todo lo demas —catalogo, capas, escenas guardadas— y si se rompe, se
rompe en silencio: el efecto aparece en la lista y proyecta negro.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import cv2
import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from ecomap_core.effects import _COMMON_UNIFORMS, media_fragment, media_params
from ecomap_core.settings import Settings
from ecomap_web.main import create_app
from ecomap_web.services import media_effects as service

RAIZ = Path(__file__).resolve().parent.parent
MIGRATIONS = RAIZ / "migrations"


def _imagen(ruta: Path, ancho: int = 64, alto: int = 48) -> Path:
    cv2.imwrite(str(ruta), np.random.randint(0, 255, (alto, ancho, 3), dtype=np.uint8))
    return ruta


def _video(ruta: Path, segundos: float = 1.0, fps: int = 10) -> Path:
    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    for _ in range(int(segundos * fps)):
        escritor.write(np.random.randint(0, 255, (48, 64, 3), dtype=np.uint8))
    escritor.release()
    return ruta


# --- nombres e identificacion -------------------------------------------


def test_el_id_sale_del_nombre_y_queda_usable_como_directorio():
    """El id termina siendo un nombre de directorio y una clave en la base."""
    assert service.id_desde_nombre("Logo del Minilab") == "logo_del_minilab"
    assert service.id_desde_nombre("Ñandú 2024") == "nandu_2024"
    assert service.id_desde_nombre("  a  b  ") == "a_b"


def test_un_nombre_que_no_deja_nada_se_rechaza():
    """Un id vacio escribiria en el directorio de efectos, no dentro de uno."""
    for malo in ("", "   ", "///", "..."):
        with pytest.raises(service.MediaEffectError):
            service.id_desde_nombre(malo)


def test_un_nombre_que_empieza_con_numero_sigue_siendo_valido():
    """El manifiesto exige que el id empiece con letra."""
    assert service.id_desde_nombre("3 rayas").startswith("efecto")


def test_la_extension_decide_que_clase_de_medio_es():
    assert service.kind_de("foto.PNG") == "image"
    assert service.kind_de("animado.gif") == "gif"
    assert service.kind_de("clip.mp4") == "video"
    with pytest.raises(service.MediaEffectError, match="no soportada"):
        service.kind_de("documento.pdf")


# --- lo que se escribe en disco -----------------------------------------


def test_una_imagen_queda_como_un_efecto_normal(tmp_path: Path):
    efectos = tmp_path / "effects"
    efectos.mkdir()

    manifiesto = service.crear(efectos, "Mi Logo", _imagen(tmp_path / "f.png"), "f.png")

    directorio = efectos / "mi_logo"
    assert {p.name for p in directorio.iterdir()} == {
        "effect.json",
        "frag.glsl",
        "preview.jpg",
        "media.png",
    }
    guardado = json.loads((directorio / "effect.json").read_text(encoding="utf-8"))
    assert guardado["source"] == {"kind": "image", "file": "media.png"}
    assert manifiesto["id"] == "mi_logo"


def test_el_shader_de_una_imagen_usa_la_textura_y_sus_parametros(tmp_path: Path):
    """Si el shader no referencia `u_media`, el efecto compila y proyecta
    negro: el peor fallo posible, porque no se ve como fallo."""
    glsl = media_fragment("image")

    assert "u_media" in glsl
    assert "p_speed" in glsl and "p_angle" in glsl
    # Y el uniform tiene que estar declarado donde el loader lo pone
    assert "uniform sampler2D u_media;" in _COMMON_UNIFORMS


def test_el_angulo_y_la_velocidad_elegidos_quedan_como_valores_por_defecto(tmp_path: Path):
    """Son parte de como se definio el efecto, no un ajuste de una capa: quien
    lo use despues arranca con el movimiento que se eligio al crearlo."""
    efectos = tmp_path / "effects"
    efectos.mkdir()

    manifiesto = service.crear(
        efectos,
        "girando",
        _imagen(tmp_path / "f.png"),
        "f.png",
        defaults={"speed": 0.42, "angle": 135.0},
    )

    por_clave = {p["key"]: p["default"] for p in manifiesto["params"]}
    assert por_clave == {"speed": 0.42, "angle": 135.0}


def test_un_video_no_lleva_parametros(tmp_path: Path):
    """Ya trae su propio movimiento: agregarle otro encima solo lo ensucia."""
    efectos = tmp_path / "effects"
    efectos.mkdir()

    manifiesto = service.crear(efectos, "clip", _video(tmp_path / "v.mp4"), "v.mp4")

    assert manifiesto["params"] == []
    assert media_params("video") == []
    # Decodificar frame a frame cuesta, y el presupuesto tiene que reflejarlo
    assert manifiesto["cost"] == "medium"


def test_un_archivo_ilegible_no_deja_un_efecto_a_medias(tmp_path: Path):
    """Un efecto a medias en el catalogo es peor que uno que no se creo:
    aparece en la lista y falla recien al proyectarlo."""
    efectos = tmp_path / "effects"
    efectos.mkdir()
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"esto no es una imagen")

    with pytest.raises(service.MediaEffectError):
        service.crear(efectos, "roto", roto, "roto.png")

    assert list(efectos.iterdir()) == []


def test_no_se_pisan_dos_efectos_con_el_mismo_nombre(tmp_path: Path):
    efectos = tmp_path / "effects"
    efectos.mkdir()
    service.crear(efectos, "repetido", _imagen(tmp_path / "a.png"), "a.png")

    with pytest.raises(service.MediaEffectError, match="ya hay un efecto"):
        service.crear(efectos, "repetido", _imagen(tmp_path / "b.png"), "b.png")


def test_un_video_largo_se_rechaza(tmp_path: Path, monkeypatch):
    """Esto proyecta bucles cortos, no reproduce peliculas: un video largo
    entra entero en memoria del render y llena la SD."""
    monkeypatch.setattr(service, "MAX_SEGUNDOS", 0.5)
    efectos = tmp_path / "effects"
    efectos.mkdir()

    with pytest.raises(service.MediaEffectError, match="maximo"):
        service.crear(efectos, "largo", _video(tmp_path / "v.mp4", segundos=2.0), "v.mp4")


def test_los_efectos_del_sistema_no_se_borran_desde_la_web(tmp_path: Path):
    """Volver a tenerlos significaria reinstalar."""
    efectos = tmp_path / "effects"
    (efectos / "nativo").mkdir(parents=True)
    (efectos / "nativo" / "effect.json").write_text('{"id": "nativo", "name": "Nativo"}')

    with pytest.raises(service.MediaEffectError, match="viene con el sistema"):
        service.borrar(efectos, "nativo")
    assert (efectos / "nativo").exists()


# --- la API --------------------------------------------------------------


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def cliente(tmp_path: Path):
    efectos = tmp_path / "effects"
    efectos.mkdir()
    settings = Settings(
        db=tmp_path / "ecomap.db",
        migrations_dir=MIGRATIONS,
        bus=f"tcp://127.0.0.1:{_puerto_libre()}",  # render offline
        effects_dir=efectos,
        media_dir=tmp_path / "media",
        scenes_dir=tmp_path / "scenes",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client, efectos, tmp_path


async def test_subir_una_imagen_la_deja_elegible_en_el_catalogo(cliente):
    """Es el criterio de la US: guardado el efecto, tiene que aparecer como
    opcion."""
    client, _efectos, tmp = cliente
    ruta = _imagen(tmp / "subida.png")

    respuesta = await client.post(
        "/api/effects/upload",
        files={"archivo": ("subida.png", ruta.read_bytes(), "image/png")},
        data={"nombre": "Subida de prueba", "speed": "0.3", "angle": "90"},
    )

    assert respuesta.status_code == 201
    catalogo = (await client.get("/api/effects")).json()
    creado = next(e for e in catalogo if e["id"] == "subida_de_prueba")
    assert creado["available"] is True
    assert {p["key"]: p["default"] for p in creado["params"]} == {"speed": 0.3, "angle": 90.0}


async def test_subir_algo_que_no_es_un_medio_se_rechaza(cliente):
    client, efectos, _ = cliente

    respuesta = await client.post(
        "/api/effects/upload",
        files={"archivo": ("notas.txt", b"hola", "text/plain")},
        data={"nombre": "texto"},
    )

    assert respuesta.status_code == 422
    assert "no soportada" in respuesta.text
    assert list(efectos.iterdir()) == []


async def test_un_archivo_demasiado_grande_se_rechaza(cliente, monkeypatch):
    """Antes de escribirlo a disco: el limite existe para no llenar la SD."""
    import ecomap_web.routers.effects as router_efectos

    monkeypatch.setattr(router_efectos.media_service, "MAX_BYTES", 10)
    client, _, tmp = cliente

    respuesta = await client.post(
        "/api/effects/upload",
        files={"archivo": ("grande.png", _imagen(tmp / "g.png").read_bytes(), "image/png")},
        data={"nombre": "grande"},
    )

    assert respuesta.status_code == 422
    assert "MB" in respuesta.text


async def test_el_archivo_original_se_puede_recuperar(cliente):
    """Para previsualizar un gif o un video en el navegador hace falta el
    archivo de verdad: el preview del catalogo es una imagen fija."""
    client, _, tmp = cliente
    ruta = _imagen(tmp / "x.png")
    await client.post(
        "/api/effects/upload",
        files={"archivo": ("x.png", ruta.read_bytes(), "image/png")},
        data={"nombre": "con archivo"},
    )

    respuesta = await client.get("/api/effects/con_archivo/media")

    assert respuesta.status_code == 200
    assert len(respuesta.content) > 0


async def test_un_efecto_sin_archivo_no_tiene_media(cliente):
    client, efectos, _ = cliente
    (efectos / "nativo").mkdir()
    (efectos / "nativo" / "effect.json").write_text('{"id": "nativo", "name": "N"}')

    assert (await client.get("/api/effects/nativo/media")).status_code == 404


async def test_borrar_un_efecto_subido_no_borra_las_capas_que_lo_usan(cliente):
    """Quedan marcadas como no disponibles, igual que si el archivo hubiera
    desaparecido del volumen. Borrar capas de escenas guardadas por quitar un
    efecto seria una sorpresa desagradable."""
    client, _, tmp = cliente
    await client.post(
        "/api/effects/upload",
        files={"archivo": ("y.png", _imagen(tmp / "y.png").read_bytes(), "image/png")},
        data={"nombre": "temporal"},
    )
    cara = (await client.post("/api/surfaces", json={"name": "cara"})).json()
    escena = next(e for e in (await client.get("/api/scenes")).json() if e["is_active"])
    await client.post(
        f"/api/scenes/{escena['id']}/layers",
        json={"surface_id": cara["id"], "effect_id": "temporal"},
    )

    assert (await client.delete("/api/effects/temporal/upload")).status_code == 204

    capas = (await client.get(f"/api/scenes/{escena['id']}")).json()["layers"]
    assert len(capas) == 1
    assert capas[0]["effect_available"] is False


async def test_la_pagina_de_efectos_responde(cliente):
    client, _, _ = cliente

    respuesta = await client.get("/efectos")

    assert respuesta.status_code == 200
    assert "Agregar un efecto" in respuesta.text
    # Y el dashboard ya no lo lleva adentro
    assert "Catálogo de efectos" not in (await client.get("/")).text
