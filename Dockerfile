# Imagen unica para los dos servicios: cambia el comando, no la imagen (ADR-009).
# Base Bookworm a proposito: Mesa del contenedor debe ser compatible con el
# kernel de Raspberry Pi OS Bookworm del host.

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Primero solo el manifiesto: la capa de dependencias se cachea entre builds.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project \
      --extra web --extra render --extra vision

COPY src/ ./src/
RUN uv sync --frozen --no-dev --extra web --extra render --extra vision


FROM python:3.12-slim-bookworm

# libgl1-mesa-dri trae llvmpipe (render por CPU en desarrollo) y el driver v3d
# en arm64. libglib2.0-0 lo pide OpenCV. network-manager solo aporta nmcli, que
# usa el modulo de red (Hito 3); el daemon corre en el host.
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
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
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
