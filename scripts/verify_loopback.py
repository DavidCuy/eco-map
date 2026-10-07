"""Verifica la auto-calibracion contra el banco virtual proyector-camara.

Corre el render de verdad (loop, bus, hilo de vision) con `loopback://` como
camara: la camara virtual devuelve lo que el proyector acaba de dibujar,
deformado por una homografia conocida. Al terminar la secuencia se compara la
`H` estimada contra esa verdad.

Con hardware solo se puede decir "se ve bien". Aca se sabe la respuesta.

    python scripts/verify_loopback.py
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from ecomap_core.protocol import OP_CALIBRATE, OP_CAMERA, op  # noqa: E402
from ecomap_core.settings import Settings  # noqa: E402
from ecomap_render.main import RenderApp  # noqa: E402

CAMARA = "loopback://?width=640&height=480&noise=2&blur=3"
# En el contenedor los efectos viven en /effects; fuera, en el arbol del repo.
EFFECTS = Path("/effects") if Path("/effects").is_dir() else RAIZ / "effects"


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> int:
    puerto = puerto_libre()
    settings = Settings(
        render_mode="headless",
        width=640,
        height=360,
        fps=60,
        bus=f"tcp://127.0.0.1:{puerto}",
        effects_dir=EFFECTS,
        preview_port=0,
    )
    app = RenderApp(settings)
    # setup() y run() en el **mismo** hilo: el contexto GL queda ligado al hilo
    # que lo crea, y crear texturas desde otro falla con "cannot create
    # texture". En produccion los dos corren en el hilo principal.
    listo = threading.Event()

    def arrancar() -> None:
        app.setup()
        listo.set()
        app.run()

    hilo = threading.Thread(target=arrancar, name="render", daemon=True)
    hilo.start()
    if not listo.wait(timeout=30):
        print("FALLO: el render no arranco")
        return 1

    eventos: list[dict] = []
    conexion = socket.create_connection(("127.0.0.1", puerto), timeout=10)
    lector = conexion.makefile("r", encoding="utf-8")

    def recibir() -> None:
        for linea in lector:
            if linea.strip():
                eventos.append(json.loads(linea))

    threading.Thread(target=recibir, daemon=True).start()

    def enviar(mensaje: dict) -> None:
        conexion.sendall((json.dumps(mensaje) + "\n").encode("utf-8"))

    enviar(op(OP_CAMERA, source=CAMARA))
    time.sleep(2.0)  # que el hilo de vision entregue algunos frames
    enviar(op(OP_CALIBRATE, settle=2, max_bits=8))

    limite = time.time() + 90
    final = None
    while time.time() < limite:
        final = next((e for e in eventos if e.get("ev") == "calib" and e.get("done")), None)
        if final:
            break
        time.sleep(0.2)

    app.running = False
    hilo.join(timeout=5)

    if final is None:
        print("FALLO: la calibracion no termino en 90 s")
        return 1

    print(f"ok={final.get('ok')} msg={final.get('msg')}")
    if not final.get("ok"):
        return 1

    print(f"  rms={final['rms']:.2f} px  inliers={final['inliers']}  cobertura={final['coverage']}")

    # --- comparacion contra la verdad ---
    #
    # La camara virtual deforma proyector -> camara con `truth`. La calibracion
    # estima camara -> proyector. Encadenarlas tiene que dar la identidad.
    import cv2

    from ecomap_vision.loopback import LoopbackSource

    fuente = app.camera._source  # noqa: SLF001 - verificacion, no produccion
    if not isinstance(fuente, LoopbackSource) or fuente.truth is None:
        print("FALLO: la fuente no era el banco virtual")
        return 1

    H_est = np.array(final["homography"], dtype=np.float64)
    cam_w, cam_h = final["camera_size"]
    # La H se estimo en la resolucion de proceso (reducida), no en la del
    # stream: hay que llevar la verdad a esa escala antes de comparar.
    escala = np.diag([cam_w / fuente.size[0], cam_h / fuente.size[1], 1.0])
    H_verdad = np.linalg.inv(escala @ fuente.truth)

    esquinas = np.float32([[0, 0], [cam_w, 0], [cam_w, cam_h], [0, cam_h]]).reshape(-1, 1, 2)
    esperado = cv2.perspectiveTransform(esquinas, H_verdad)
    obtenido = cv2.perspectiveTransform(esquinas, H_est)
    error = float(np.abs(esperado - obtenido).max())
    comp = (escala @ fuente.truth) @ H_est
    comp = comp / comp[2, 2]
    print("  cam_size", (cam_w, cam_h), "loopback", fuente.size, "proj", final["proj_size"])
    print("  composicion (deberia ser identidad)")
    print(comp.round(3))
    print(f"  esquinas: diferencia maxima contra la verdad {error:.1f} px")

    if error > 12.0:
        print("FALLO: la homografia estimada no coincide con la del banco")
        return 1
    print("OK: la homografia recuperada coincide con la verdad del banco")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
