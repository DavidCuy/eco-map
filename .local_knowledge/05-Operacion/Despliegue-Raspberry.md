---
tags: [operacion, deploy, raspberry, minipc]
---

# Despliegue en hardware

Todo por contenedores. Ver [[ADR-009-Todo-en-Contenedores]]. Cada plataforma tiene su archivo
compose autocontenido ([[ADR-013-Plataforma-Agnostica]]):

| Plataforma | Compose | Preparación del SO |
|---|---|---|
| Mini PC x86 (referencia) | `compose.minipc.yml` | [[Mini-PC-Setup]] |
| Raspberry Pi (arm64) | `compose.pi.yml` | [[Raspberry-Pi-Setup]] |

Lo que sigue está escrito para la Pi; en la mini PC es idéntico cambiando el archivo compose y
salteando lo específico de `vc4-kms-v3d`.

## Instalación

```bash
# Raspberry Pi OS Bookworm 64-bit Lite, sin escritorio
sudo apt install -y podman avahi-daemon network-manager
sudo usermod -aG video,render "$USER"
sudo hostnamectl set-hostname eco-map
pipx install podman-compose    # o uv tool install podman-compose

git clone <repo> /opt/ecomap && cd /opt/ecomap
# La imagen arm64 se construye aqui, en nativo: desde Windows no se puede
# (WSL2 no permite binfmt_misc). Ver ADR-012.
podman build --target runtime -t ecomap:latest .
podman-compose -f compose.pi.yml up -d
```

Primer arranque: el contenedor web aplica las migraciones y siembra el catálogo de efectos desde el volumen. Si el volumen de efectos está vacío, se copia el catálogo base incluido en la imagen (solo la primera vez).

## Identificar la cámara

El índice de `/dev/video0` cambia entre arranques. Ver [[ADR-010-Camara-USB]].

```bash
ls -l /dev/v4l/by-id/          # ruta estable, va en el compose de la plataforma
v4l2-ctl --list-formats-ext -d /dev/video0    # confirmar que soporta MJPG
```

Una webcam suele exponer **dos** nodos (`video0` = captura, `video1` = metadatos). Usar el que lista formatos.

## Arranque automático

`restart: unless-stopped` en el compose cubre casi todo. Para que el stack suba tras un corte de luz aunque alguien lo haya bajado a mano, una unit mínima:

```ini
# /etc/systemd/system/ecomap.service
[Unit]
Description=Eco-Map stack
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/ecomap
ExecStart=/usr/bin/podman-compose -f compose.pi.yml up -d
ExecStop=/usr/bin/podman-compose -f compose.pi.yml down

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now ecomap
```

**La proyección no espera a la red.** El render no depende del web ni del wifi: con la escena marcada `is_default` en la DB, arranca proyectando aunque no haya router. Ver [[Modulo-Red]].

## Operación

```bash
podman logs -f eco-map_render_1        # loop de render, shaders, cámara
podman logs -f eco-map_web_1           # HTTP, red, calibración
podman restart eco-map_render_1        # ~2 s de negro
podman stats                           # CPU y RAM por contenedor
vcgencmd measure_temp                # en el host de la Pi; en la mini PC, `sensors`
```

## Respaldo y restauración

Tres volúmenes, uno crítico y dos pesados. Ver [[ADR-011-Archivos-vs-DB]].

```bash
# DB: respaldo consistente en caliente
podman exec eco-map_web_1 sqlite3 /data/ecomap.db ".backup /data/backup.db"

# volúmenes completos a un tar
podman run --rm -v ecomap-data:/v -v "$PWD":/out alpine \
  tar czf /out/ecomap-data.tgz -C /v .
podman run --rm -v ecomap-effects:/v -v "$PWD":/out alpine \
  tar czf /out/ecomap-effects.tgz -C /v .
```

Alternativa de respaldo lógico: `POST /api/config/export` baja un JSON con superficies, escenas y capas — más chico y legible, suficiente para reconstruir una instalación.

## Actualizar

```bash
cd /opt/ecomap && git pull
podman build --target runtime -t ecomap:latest .
podman-compose -f compose.pi.yml up -d
```

Las migraciones corren al arrancar el web. Rollback = `git checkout <tag>` y volver a levantar; los volúmenes sobreviven. **Atención:** una migración que cambie el esquema hacia adelante no se revierte sola — respaldar la DB antes de actualizar.

## Cuidados con el almacenamiento

- Escrituras de la app: solo por debounce de 500 ms. Ver [[ADR-004-SQLite]]. En la Pi con SD esto
  es supervivencia del hardware; en la mini PC con SSD es solo buena práctica.
- Logs de los contenedores acotados: `logging.options.max-size: "10m"`, `max-file: "3"` en el compose. Sin esto, `json-file` crece sin límite y llena la tarjeta.
- Idealmente, SSD USB en vez de SD.

Relacionado: [[Docker-Local]] · [[Mini-PC-Setup]] · [[Raspberry-Pi-Setup]] · [[ADR-013-Plataforma-Agnostica]] · [[Seguridad-y-Red]]
