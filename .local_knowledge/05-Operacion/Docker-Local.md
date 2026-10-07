---
tags: [operacion, docker, dev]
---

# Contenedores y Compose

Único modo de ejecución, en desarrollo y en la Pi. Ver [[ADR-009-Todo-en-Contenedores]].

**Runtime en desarrollo local: Podman rootless con `podman-compose`.** Los archivos son OCI y
compose estándar, así que sirven igual con Docker; lo que cambia son los comandos. Detalle y
trampas verificadas en [[ADR-012-Podman-Desarrollo-Local]].

```bash
uv tool install podman-compose          # una vez
podman build --target dev -t ecomap:dev .
podman-compose -f compose.dev.yml up -d
podman logs -f eco-map_render_1         # ojo: guion bajo con podman-compose
podman exec eco-map_web_1 pytest -q     # la imagen dev trae pytest y ruff
podman-compose -f compose.dev.yml down
```

## Un Dockerfile, tres compose

Cada entorno tiene su **compose autocontenido**, sin overrides encadenados
([[ADR-013-Plataforma-Agnostica]]):

| Archivo | Destino | Particularidad |
|---|---|---|
| `compose.dev.yml` | laptop | target `dev`, llvmpipe, 640×360@30, bind mounts, cámara simulada |
| `compose.minipc.yml` | mini PC x86 | `kms` con driver i915, host network, D-Bus, 1080p60 |
| `compose.pi.yml` | Raspberry Pi | `kms` con driver v3d, `platform: linux/arm64` |

Un solo `Dockerfile` con dos targets, `runtime` y `dev`. No hay uno por plataforma porque el
contenido sería idéntico: `libgl1-mesa-dri` ya trae llvmpipe, crocus/iris y v3d. Se partirá cuando
llegue la aceleración de video por hardware, donde la mini PC quiere VAAPI y la Pi `v4l2m2m`.

## Volúmenes

Cuatro volúmenes nombrados, **separados a propósito**:

| Volumen | Contiene | Se respalda | Se comparte entre instalaciones |
|---|---|---|---|
| `ecomap-data` | `ecomap.db` | sí, crítico | no |
| `ecomap-effects` | `effect.json`, `frag.glsl`, `preview.jpg` | sí | **sí** — un paquete de efectos es portable |
| `ecomap-media` | videos, imágenes de los efectos | sí, pesado | sí |
| `ecomap-bus` | `bus.sock` | no, efímero | no |

Separar efectos de la DB permite reemplazar el catálogo entero sin tocar la configuración, y montar los efectos como **solo lectura** en el render. Ver [[ADR-011-Archivos-vs-DB]].

## Dockerfile

```dockerfile
# ---- builder ----
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
      --extra web --extra render --extra vision
COPY src/ ./src/
RUN uv sync --frozen --no-dev --extra web --extra render --extra vision

# ---- runtime ----
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libegl1 libgbm1 libdrm2 mesa-utils libglib2.0-0 \
      network-manager \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src  /app/src
COPY migrations/ ./migrations/
COPY effects/ ./effects-seed/
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000 8001
CMD ["ecomap-web"]
```

- `pyproject.toml` + `uv.lock` antes que el código: la capa de dependencias se cachea. Ver [[ADR-003-uv]].
- `libgl1-mesa-dri` trae llvmpipe, que es lo que hace posible el modo headless sin GPU.
- `opencv-python-headless`, nunca la variante con GUI: evita arrastrar GTK.
- `network-manager` solo aporta el cliente `nmcli`; el daemon corre en el host. Ver [[Modulo-Red]].
- `effects/`, `media/` y `data/` **no** se copian a la imagen: son volúmenes.

## compose: estructura común

```yaml
services:
  web:
    image: ecomap:latest
    build: .
    command: ecomap-web
    environment:
      ECOMAP_DB: /data/ecomap.db
      ECOMAP_EFFECTS: /effects
      ECOMAP_MEDIA: /media
      ECOMAP_BUS: /run/ecomap/bus.sock
    volumes:
      - ecomap-data:/data
      - ecomap-effects:/effects
      - ecomap-media:/media
      - ecomap-bus:/run/ecomap
    restart: unless-stopped
    depends_on: [render]

  render:
    image: ecomap:latest
    build: .
    command: ecomap-render
    environment:
      ECOMAP_EFFECTS: /effects
      ECOMAP_MEDIA: /media
      ECOMAP_BUS: /run/ecomap/bus.sock
    volumes:
      - ecomap-effects:/effects:ro
      - ecomap-media:/media:ro
      - ecomap-bus:/run/ecomap
    restart: unless-stopped

volumes:
  ecomap-data:
  ecomap-effects:
  ecomap-media:
  ecomap-bus:
```

El render monta efectos y media **`:ro`**: no tiene por qué escribirlos, y así un shader no puede corromper el catálogo.

## compose.dev.yml (laptop, sin hardware)

```yaml
services:
  web:
    ports: ["8000:8000"]
    environment:
      ECOMAP_RELOAD: "1"
    volumes:
      - ./src:/app/src
      - ./effects:/effects          # bind mount: editar shaders con el editor local
  render:
    command: ecomap-render
    environment:
      ECOMAP_RENDER_MODE: headless
      ECOMAP_GL_BACKEND: egl
      LIBGL_ALWAYS_SOFTWARE: "1"
      ECOMAP_WIDTH: "640"        # llvmpipe no llega a mas
      ECOMAP_HEIGHT: "360"
      ECOMAP_FPS: "30"
      ECOMAP_PREVIEW_PORT: "8001"
      ECOMAP_CAMERA: "fake://"
    ports: ["8001:8001"]
    volumes:
      - ./src:/app/src
      - ./effects:/effects:ro
```

```bash
podman-compose -f compose.dev.yml up -d
```

Sin proyector, sin cámara, sin Pi: el render dibuja a un FBO y expone el resultado como MJPEG en `:8001`, que la UI muestra como preview. Es lo que permite desarrollar todo el flujo de calibración y efectos en el escritorio. Ver [[Modulo-Render]].

## compose.minipc.yml y compose.pi.yml (producción)

```yaml
services:
  web:
    network_mode: host
    volumes:
      - /run/dbus/system_bus_socket:/run/dbus/system_bus_socket
  render:
    devices:
      - /dev/dri:/dev/dri
      - /dev/v4l/by-id/usb-XXXX-video-index0:/dev/video0
    group_add: ["video", "render"]
    environment:
      ECOMAP_CAMERA: "v4l2:///dev/video0"
```

Detalle de despliegue en [[Despliegue-Raspberry]].

## Limitaciones conocidas

- Con `LIBGL_ALWAYS_SOFTWARE=1` el render va por CPU (llvmpipe): valida lógica y shaders simples, **no** mide rendimiento. Las mediciones reales se hacen en la Pi. Ver [[Presupuesto-de-Rendimiento]].
- El socket IPC va por **volumen nombrado**, no por bind mount: los bind mounts de sockets Unix fallan sobre Windows y macOS, tanto con Docker Desktop como con la máquina de Podman.
- Sobre Windows no hay passthrough de USB (ni con Docker Desktop ni con Podman en WSL): la cámara real se prueba en Linux o en la Pi; en Windows se usa `FakeSource`.
- La versión de Mesa en la imagen debe ser compatible con el kernel del host. Riesgo asumido y anotado en [[ADR-009-Todo-en-Contenedores]].

Relacionado: [[ADR-012-Podman-Desarrollo-Local]] · [[Despliegue-Raspberry]] · [[Estructura-Repositorio]] · [[Modulo-Efectos]]
