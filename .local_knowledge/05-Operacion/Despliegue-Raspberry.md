---
tags: [operacion, raspberry, deploy]
---

# Despliegue en la Raspberry Pi

Todo por contenedores. Ver [[ADR-009-Todo-en-Contenedores]]. Preparación del SO en [[Raspberry-Pi-Setup]].

## Instalación

```bash
# Raspberry Pi OS Bookworm 64-bit Lite, sin escritorio
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker,video,render "$USER"
sudo apt install -y avahi-daemon network-manager
sudo hostnamectl set-hostname eco-map

git clone <repo> /opt/ecomap && cd /opt/ecomap
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build
```

Primer arranque: el contenedor web aplica las migraciones y siembra el catálogo de efectos desde el volumen. Si el volumen de efectos está vacío, se copia el catálogo base incluido en la imagen (solo la primera vez).

## Identificar la cámara

El índice de `/dev/video0` cambia entre arranques. Ver [[ADR-010-Camara-USB]].

```bash
ls -l /dev/v4l/by-id/          # ruta estable, va en docker-compose.pi.yml
v4l2-ctl --list-formats-ext -d /dev/video0    # confirmar que soporta MJPG
```

Una webcam suele exponer **dos** nodos (`video0` = captura, `video1` = metadatos). Usar el que lista formatos.

## Arranque automático

`restart: unless-stopped` en el compose cubre casi todo. Para que el stack suba tras un corte de luz aunque alguien lo haya bajado a mano, una unit mínima:

```ini
# /etc/systemd/system/ecomap.service
[Unit]
Description=Eco-Map stack
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/ecomap
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.pi.yml down

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now ecomap
```

**La proyección no espera a la red.** El render no depende del web ni del wifi: con la escena marcada `is_default` en la DB, arranca proyectando aunque no haya router. Ver [[Modulo-Red]].

## Operación

```bash
docker compose logs -f render        # loop de render, shaders, cámara
docker compose logs -f web           # HTTP, red, calibración
docker compose restart render        # ~2 s de negro
docker stats                         # CPU y RAM por contenedor
vcgencmd measure_temp                # en el host, no en el contenedor
```

## Respaldo y restauración

Tres volúmenes, uno crítico y dos pesados. Ver [[ADR-011-Archivos-vs-DB]].

```bash
# DB: respaldo consistente en caliente
docker compose exec web sqlite3 /data/ecomap.db ".backup /data/backup.db"

# volúmenes completos a un tar
docker run --rm -v ecomap-data:/v -v "$PWD":/out alpine \
  tar czf /out/ecomap-data.tgz -C /v .
docker run --rm -v ecomap-effects:/v -v "$PWD":/out alpine \
  tar czf /out/ecomap-effects.tgz -C /v .
```

Alternativa de respaldo lógico: `POST /api/config/export` baja un JSON con superficies, escenas y capas — más chico y legible, suficiente para reconstruir una instalación.

## Actualizar

```bash
cd /opt/ecomap && git pull
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build
```

Las migraciones corren al arrancar el web. Rollback = `git checkout <tag>` y volver a levantar; los volúmenes sobreviven. **Atención:** una migración que cambie el esquema hacia adelante no se revierte sola — respaldar la DB antes de actualizar.

## Cuidados con la SD

- Escrituras de la app: solo por debounce de 500 ms. Ver [[ADR-004-SQLite]].
- Logs de Docker acotados: `logging.options.max-size: "10m"`, `max-file: "3"` en el compose. Sin esto, `json-file` crece sin límite y llena la tarjeta.
- Idealmente, SSD USB en vez de SD.

Relacionado: [[Docker-Local]] · [[Raspberry-Pi-Setup]] · [[Seguridad-y-Red]]
