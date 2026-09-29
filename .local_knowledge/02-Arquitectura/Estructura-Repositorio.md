---
tags: [arquitectura, repo]
---

# Estructura del repositorio

```
eco-map/
├── pyproject.toml              # uv, un solo proyecto, extras por componente
├── uv.lock
├── Dockerfile                  # multi-stage, multi-arch arm64 + amd64
├── docker-compose.yml          # base: servicios y volúmenes
├── docker-compose.dev.yml      # escritorio: bind mounts, render software, cámara fake
├── docker-compose.pi.yml       # Pi: /dev/dri, webcam, host network, D-Bus
├── .env.example
├── src/
│   ├── ecomap_core/            # compartido: schemas, protocolo IPC, config
│   │   ├── models.py  schemas.py  protocol.py  settings.py
│   ├── ecomap_web/             # FastAPI. Ver [[Modulo-Web-API]]
│   │   ├── main.py  migrate.py
│   │   ├── routers/            # pages, surfaces, effects, scenes, camera, network, ws
│   │   ├── services/           # scenes.py, calibration.py, catalog.py, network.py
│   │   ├── repo/               # acceso SQLite
│   │   ├── templates/  static/ # htmx.min.js, alpine.min.js, pico.min.css (versionados)
│   ├── ecomap_render/          # ModernGL. Ver [[Modulo-Render]]
│   │   ├── main.py  context.py  pipeline.py  warp.py  effects.py  bus.py  telemetry.py
│   └── ecomap_vision/          # cámara. Ver [[Modulo-Camara-Feedback]]
│       ├── source.py           # CameraSource, OpenCVSource, FakeSource
│       ├── calibrate.py  motion.py
├── effects/                    # catálogo semilla; en runtime es el volumen ecomap-effects
│   └── plasma/{effect.json,frag.glsl,preview.jpg}
├── media/                      # assets semilla; en runtime, volumen ecomap-media
├── migrations/                 # 001_init.sql, ...
├── scripts/                    # bootstrap-pi.sh, ecomap.service
├── tests/
└── .local_knowledge/           # esta base de conocimiento
```

`data/` no existe en el repo: la DB vive en el volumen `ecomap-data`. Ver [[ADR-011-Archivos-vs-DB]].

## Por qué un solo paquete Python con tres módulos

Menos fricción que tres repos o un monorepo con workspaces: comparten `ecomap_core` sin publicar nada. `pyproject.toml` define extras:

```toml
[project.optional-dependencies]
web    = ["fastapi", "uvicorn[standard]", "jinja2", "python-multipart"]
render = ["moderngl", "moderngl-window", "numpy"]
vision = ["opencv-python-headless", "numpy"]
```

Una sola imagen Docker instala los tres extras y sirve para ambos servicios; lo que cambia es el comando. Ya **no** hay extra `pi`: `picamera2` salió del alcance con [[ADR-010-Camara-USB]], y con eso el entorno es idéntico en escritorio y en Pi.

Entry points:

```toml
[project.scripts]
ecomap-web    = "ecomap_web.main:run"
ecomap-render = "ecomap_render.main:run"
```

Relacionado: [[ADR-003-uv]] · [[ADR-009-Todo-en-Contenedores]] · [[Docker-Local]] · [[Despliegue-Raspberry]]
