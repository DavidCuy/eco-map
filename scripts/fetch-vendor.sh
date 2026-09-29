#!/usr/bin/env bash
# Descarga los assets del frontend al directorio static/vendor.
# Se corre a mano cuando se sube de version; los archivos van versionados en el
# repo porque la Pi puede estar sin internet (ADR-002).
set -euo pipefail

HTMX_VERSION="2.0.4"
HTMX_JSON_ENC_VERSION="2.0.2"
ALPINE_VERSION="3.14.8"
PICO_VERSION="2.0.6"

DEST="$(dirname "$0")/../src/ecomap_web/static/vendor"
mkdir -p "$DEST"

get() { echo "  $2"; curl -sSfL "$1" -o "$DEST/$2"; }

echo "descargando en $DEST"
get "https://cdnjs.cloudflare.com/ajax/libs/htmx/${HTMX_VERSION}/htmx.min.js" "htmx.min.js"
get "https://cdn.jsdelivr.net/npm/htmx-ext-json-enc@${HTMX_JSON_ENC_VERSION}/json-enc.js" "htmx-ext-json-enc.js"
get "https://cdnjs.cloudflare.com/ajax/libs/alpinejs/${ALPINE_VERSION}/cdn.min.js" "alpine.min.js"
get "https://cdn.jsdelivr.net/npm/@picocss/pico@${PICO_VERSION}/css/pico.min.css" "pico.min.css"
echo "listo. Actualizar las versiones en $DEST/VERSIONS.md"
