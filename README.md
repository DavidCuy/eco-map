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

El runtime es **Podman en modo rootful** con `podman-compose`. Los archivos son OCI y compose
estándar, así que Docker también sirve; solo cambian los comandos.

En Windows, una vez: `podman machine stop && podman machine set --rootful && podman machine start`.

```bash
uv tool install podman-compose          # una vez
podman build --target dev -t ecomap:dev .
podman-compose -f compose.dev.yml up -d
```

- UI: <http://localhost:8000>
- Preview del render (MJPEG): <http://localhost:8001>
- API: <http://localhost:8000/docs>

En Windows con la máquina en rootful no hay forward a `localhost`: hay que usar la IP de la VM,
que cambia al reiniciar WSL.

```bash
podman machine ssh "ip -4 addr show eth0 | awk '/inet /{print \$2}'"
```

El render dibuja por CPU con llvmpipe, a 640×360 y 30 fps: sirve para validar lógica y shaders
simples, **no** para medir rendimiento.

```bash
podman logs -f eco-map_render_1      # con podman-compose los nombres usan guion bajo
podman exec eco-map_web_1 pytest -q  # la imagen dev trae pytest
podman-compose -f compose.dev.yml down
```

Con Docker el equivalente es `docker compose -f compose.dev.yml up -d`, y los contenedores se
llaman `eco-map-render-1` con guion.

### Sin contenedores

```bash
uv sync --extra web --extra render --extra vision
cp .env.example .env          # en Windows hay que dejar ECOMAP_BUS=tcp://...

uv run ecomap-render          # en una terminal
uv run ecomap-web             # en otra
```

En Linux y macOS el bus usa un socket Unix. En Windows CPython no expone `AF_UNIX`, así que hay
que usar `ECOMAP_BUS=tcp://127.0.0.1:8765` en ambos procesos.

Para ver el render en una ventana con la GPU real hace falta el extra `window`: moderngl-window
trae pyglet, no glfw, y sin glfw el modo falla al crear la ventana.

```bash
uv sync --extra render --extra window
ECOMAP_RENDER_MODE=window uv run ecomap-render
```

**El bus es TCP, así que los dos procesos no tienen que estar en la misma máquina.** El render
escucha y el web es cliente: sirve para proyectar desde el equipo que tiene el proyector mientras
se edita y se sirve la UI desde otro. Ver [`Mini-PC-Setup.md`](.local_knowledge/04-Hardware/Mini-PC-Setup.md).

### En hardware

El sistema es agnóstico de plataforma: corre en x86-64 y en arm64 con el mismo código. Cada destino
tiene su compose autocontenido.

```bash
podman build --target runtime -t ecomap:latest .

podman-compose -f compose.minipc.yml up -d   # mini PC x86 (referencia)
podman-compose -f compose.pi.yml up -d       # Raspberry Pi (arm64, construir en la Pi)
```

Ambas necesitan un host **sin entorno gráfico** (si no, el escritorio toma el DRM master), el
usuario en los grupos `video` y `render`, y `avahi-daemon`. La Pi además `dtoverlay=vc4-kms-v3d`.
Pasos completos en
[`Mini-PC-Setup.md`](.local_knowledge/04-Hardware/Mini-PC-Setup.md) y
[`Despliegue-Raspberry.md`](.local_knowledge/05-Operacion/Despliegue-Raspberry.md).

## Equipo de pruebas Windows

Para un equipo que corre Eco-Map nativo (sin contenedores, en modo `window`), el
ciclo de actualizacion es un solo comando en ese equipo:

```powershell
.\scripts\update.ps1
```

Trae el codigo (con `git pull` si la carpeta es un clon, con el zip de la rama si
no), sincroniza dependencias y relanza los procesos que estaban corriendo. La
puesta en marcha inicial esta en
[`Mini-PC-Setup.md`](.local_knowledge/04-Hardware/Mini-PC-Setup.md).

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
| `ECOMAP_WINDOW_FULLSCREEN` | `0` | en modo `window`, pantalla completa. Obligatorio al proyectar |
| `ECOMAP_WINDOW_MONITOR` | `0` | monitor destino; `1` para el proyector en la segunda salida |

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
- El modo `window` ya crea contexto sobre una GPU real (verificado en Intel Iris Xe), pero
  **la pantalla completa no se probó contra un proyector**: la resolución la impone el monitor, y
  si el modo de video no coincide con `ECOMAP_WIDTH`/`HEIGHT` manda el monitor.
- **La imagen arm64 todavía no se construyó.** Desde Windows no se puede: WSL2 no permite usar
  `binfmt_misc`, así que no hay emulación qemu. Hay que construirla en la Pi o en CI. La imagen
  amd64 sí está validada.
- Los shaders se escriben en GLSL ES 3.0 para que sirvan en las dos plataformas, aunque en x86
  habría OpenGL 4.x disponible. Es el costo del agnosticismo.
- Bajo llvmpipe los números de rendimiento no significan nada; hay que medir en la Pi.
- No hay autenticación. No exponer a internet.

## Licencia

MIT. Ver [LICENSE](LICENSE).
