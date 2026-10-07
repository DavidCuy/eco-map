# Imagen unica para los dos servicios y para las tres plataformas: cambia el
# comando, no la imagen (ADR-009). La arquitectura la define --platform o el
# campo `platform` del compose; el contenido es identico (ADR-013).
#
# Targets:
#   runtime (default) -> produccion: mini PC y Raspberry Pi
#   dev               -> desarrollo: agrega pytest y ruff para correr dentro
#
#   podman build -t ecomap:latest .
#   podman build -t ecomap:dev --target dev .
#
# Base Bookworm a proposito: Mesa del contenedor debe ser compatible con el
# kernel del host, y Raspberry Pi OS estable es Bookworm.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- builder ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Primero solo el manifiesto: la capa de dependencias se cachea entre builds.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project \
      --extra web --extra render --extra vision

COPY src/ ./src/
RUN uv sync --frozen --no-dev --extra web --extra render --extra vision

# ------------------------------------------------------------ builder-dev ---
# Mismo venv mas el grupo dev (pytest, ruff, httpx). Se separa para que la
# imagen de produccion no arrastre herramientas de prueba.
FROM builder AS builder-dev
RUN uv sync --frozen --extra web --extra render --extra vision

# ----------------------------------------------------------- runtime-base ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime-base

# libgl1-mesa-dri trae los tres drivers que necesitamos segun plataforma:
#   llvmpipe (dev, sin GPU) · crocus/iris (mini PC Intel) · v3d (Raspberry Pi)
# libglib2.0-0 lo pide OpenCV. network-manager solo aporta nmcli, que usa el
# modulo de red (Hito 3); el daemon corre en el host.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 \
      libegl1 \
      libgbm1 \
      libdrm2 \
      libgl1-mesa-dri \
      libglib2.0-0 \
      network-manager \
      sqlite3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY migrations/ ./migrations/
# Catalogo semilla: en runtime manda el volumen ecomap-effects.
COPY effects/ ./effects-seed/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ECOMAP_DB=/data/ecomap.db \
    ECOMAP_EFFECTS=/effects \
    ECOMAP_MEDIA=/media \
    ECOMAP_BUS=/run/ecomap/bus.sock \
    ECOMAP_MIGRATIONS_DIR=/app/migrations

EXPOSE 8000 8001
CMD ["ecomap-web"]

# ---------------------------------------------------------------- runtime ---
FROM runtime-base AS runtime
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# -------------------------------------------------------------------- dev ---
# El codigo llega por bind mount desde el host; lo que aporta esta imagen es el
# venv con las herramientas de prueba, para poder correr:
#   podman exec eco-map_web_1 pytest -q
FROM runtime-base AS dev
COPY --from=builder-dev /app/.venv /app/.venv
COPY --from=builder-dev /app/src /app/src
COPY tests/ ./tests/
COPY pyproject.toml ./
