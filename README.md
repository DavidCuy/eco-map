# Eco-Map

Videomapping de bajo costo: **un proyector + una Raspberry Pi + una cámara web**, configurado
entero desde el navegador. Sin nube, sin software propietario, sin teclado en la Pi.

> Estado: **Hito 0 (esqueleto) completo**. Hay dos procesos que hablan entre sí, base de datos,
> dashboard y render con telemetría real. Todavía no hay superficies, efectos ni calibración:
> eso es el [Hito 1](https://github.com/DavidCuy/eco-map/milestone/2) en adelante.

## Cómo funciona

Dos procesos en la misma máquina:

- **`ecomap-web`** — FastAPI + Jinja2 + HTMX + Alpine. Sirve la UI y la API, es el único que
  escribe en SQLite.
- **`ecomap-render`** — ModernGL. Dueño del contexto OpenGL y de la salida HDMI. Nunca abre la
  base de datos.

Se comunican por un socket Unix con JSON por línea. **SQLite es persistencia; el socket es tiempo
real.** Si el web se reinicia, la proyección sigue.

El diagrama completo está en
[`.local_knowledge/02-Arquitectura/Arquitectura-General.md`](.local_knowledge/02-Arquitectura/Arquitectura-General.md).

## Arranque rápido

### Con contenedores (recomendado, sin hardware)

El runtime de desarrollo es **Podman rootless** con `podman-compose`. Los archivos son OCI y compose
estándar, así que Docker también sirve; solo cambian los comandos.

```bash
uv tool install podman-compose        # una vez
podman build -t ecomap:latest .
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

- UI: <http://localhost:8000>
- Preview del render (MJPEG): <http://localhost:8001>
- API: <http://localhost:8000/docs>

El render dibuja por CPU con llvmpipe, a 640×360 y 30 fps: sirve para validar lógica y shaders
simples, **no** para medir rendimiento.

```bash
podman logs -f eco-map_render_1      # con podman-compose los nombres usan guion bajo
podman-compose -f docker-compose.yml -f docker-compose.dev.yml down
```

Con Docker el equivalente es `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
y los contenedores se llaman `eco-map-render-1`.

### Sin contenedores

```bash
uv sync --extra web --extra render --extra vision
cp .env.example .env          # en Windows hay que dejar ECOMAP_BUS=tcp://...

uv run ecomap-render          # en una terminal
uv run ecomap-web             # en otra
```

En Linux y macOS el bus usa un socket Unix. En Windows CPython no expone `AF_UNIX`, así que hay
que usar `ECOMAP_BUS=tcp://127.0.0.1:8765` en ambos procesos.

### En la Raspberry Pi

```bash
podman-compose -f docker-compose.yml -f docker-compose.pi.yml up -d
```

Requiere `dtoverlay=vc4-kms-v3d`, el usuario en los grupos `video` y `render`, y `avahi-daemon`.
Pasos completos en
[`.local_knowledge/05-Operacion/Despliegue-Raspberry.md`](.local_knowledge/05-Operacion/Despliegue-Raspberry.md).

## Comandos

```bash
uv run pytest                 # tests
uv run ruff check src tests   # lint
uv run ruff format src tests  # formato
uv run python -m ecomap_web.migrate   # aplicar migraciones a mano
bash scripts/fetch-vendor.sh  # actualizar htmx, alpine y pico
```

## Configuración

Todo por variables de entorno con prefijo `ECOMAP_` (ver [`.env.example`](.env.example)). Las más
usadas:

| Variable | Default | Para qué |
|---|---|---|
| `ECOMAP_BUS` | `/run/ecomap/bus.sock` | socket del bus, o `tcp://host:puerto` |
| `ECOMAP_RENDER_MODE` | `headless` | `kms` en la Pi, `window` en escritorio con GPU |
| `ECOMAP_WIDTH` / `ECOMAP_HEIGHT` / `ECOMAP_FPS` | 1920 / 1080 / 60 | salida del render |
| `ECOMAP_DB` | `/data/ecomap.db` | base SQLite |
| `ECOMAP_GL_BACKEND` | — | `egl` dentro de contenedores Linux |

## Estructura

```
src/ecomap_core/     protocolo del bus, configuración, esquemas compartidos
src/ecomap_web/      FastAPI, routers, templates, assets vendorizados
src/ecomap_render/   contexto GL, pipeline, preview MJPEG, telemetría
src/ecomap_vision/   cámara (Hito 4)
effects/             catálogo en disco (Hito 2)
migrations/          esquema SQLite
.local_knowledge/    base de conocimiento: arquitectura, ADRs, hardware, operación
```

## Decisiones

Las decisiones técnicas están razonadas como ADRs en
[`.local_knowledge/03-Decisiones/`](.local_knowledge/03-Decisiones/). Las que más se notan al leer
el código:

- **HTMX + Alpine en vez de un framework SPA** — sin Node, sin build, ~41 KB de front.
- **Dos procesos** — un loop GL bloqueante dentro de asyncio produce jitter y bloquea el HTTP.
- **Todo en contenedores**, también en producción; Podman rootless en desarrollo local.
- **Contenido voluminoso en archivos, metadatos en SQLite** — nada de BLOBs.
- **Sin login en v1** — red local de propósito único. La red se configura desde la misma web.

## Limitaciones conocidas

- El modo `kms` está implementado pero **no validado contra hardware**: falta probarlo en una Pi
  con proyector.
- **La imagen arm64 todavía no se construyó.** Desde Windows no se puede: WSL2 no permite usar
  `binfmt_misc`, así que no hay emulación qemu. Hay que construirla en la Pi o en CI.
- Bajo llvmpipe los números de rendimiento no significan nada; hay que medir en la Pi.
- No hay autenticación. No exponer a internet.

## Licencia

MIT. Ver [LICENSE](LICENSE).
