---
tags: [operacion, docker, dev]
---

# Docker y Compose

Único modo de ejecución, en desarrollo y en la Pi. Ver [[ADR-009-Todo-en-Contenedores]].

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
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["ecomap-web"]
```

- `pyproject.toml` + `uv.lock` antes que el código: la capa de dependencias se cachea. Ver [[ADR-003-uv]].
- `opencv-python-headless`, nunca la variante con GUI: evita arrastrar GTK.
- `network-manager` solo aporta el cliente `nmcli`; el daemon corre en el host. Ver [[Modulo-Red]].
- `effects/`, `media/` y `data/` **no** se copian a la imagen: son volúmenes.

## docker-compose.yml (base)

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

## docker-compose.dev.yml (escritorio, sin hardware)

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
    command: ecomap-render --headless --preview-port 8001
    environment:
      LIBGL_ALWAYS_SOFTWARE: "1"
      ECOMAP_CAMERA: "fake:///media/sample.mp4"
    ports: ["8001:8001"]
    volumes:
      - ./src:/app/src
      - ./effects:/effects:ro
```

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Sin proyector, sin cámara, sin Pi: el render dibuja a un FBO y expone el resultado como MJPEG en `:8001`, que la UI muestra como preview. Es lo que permite desarrollar todo el flujo de calibración y efectos en el escritorio. Ver [[Modulo-Render]].

## docker-compose.pi.yml (producción)

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
- El socket IPC va por **volumen nombrado**, no por bind mount: los bind mounts de sockets Unix fallan en Docker Desktop sobre Windows y macOS.
- En Docker Desktop sobre Windows no hay passthrough de USB: la cámara real se prueba en Linux o en la Pi; en Windows se usa `FakeSource`.
- La versión de Mesa en la imagen debe ser compatible con el kernel del host. Riesgo asumido y anotado en [[ADR-009-Todo-en-Contenedores]].

Relacionado: [[Despliegue-Raspberry]] · [[Estructura-Repositorio]] · [[Modulo-Efectos]]
