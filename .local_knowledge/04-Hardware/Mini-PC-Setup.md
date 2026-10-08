---
tags: [hardware, minipc, setup]
---

# Mini PC x86 — configuración

Plataforma de **referencia** del proyecto. Ver [[ADR-013-Plataforma-Agnostica]].

## El equipo disponible

KAMRUI GK3PLUS, recibido con **Intel Processor N95** (no el N3350 que se asumía al
dimensionar), 8 GB RAM, SSD 256 GB, 2×HDMI + VGA, WiFi y BT.

| Dato | Valor | Qué implica |
|---|---|---|
| CPU | 4 núcleos / 4 hilos, 1.7–3.4 GHz, Gracemont (Alder Lake-N) | Mismos núcleos que una Pi 4 y bastante más rápidos. El hilo de cámara deja de ser el riesgo principal |
| GPU | Intel UHD Graphics Gen12, hasta 1.2 GHz | Bastante más margen que el VideoCore VI de la Pi 4 |
| Video | HDMI 1.4b | 1080p60 sí; 4K solo a 30 Hz, irrelevante para v1 |
| RAM | 8 GB | De sobra: el sistema entero usa cientos de MB |
| Disco | SSD | Sin el problema de desgaste de la SD |
| Salidas | 2×HDMI | Habilita multi-proyector en v2. VGA es analógico, ignorarlo |

> [!warning] Falta confirmar la GPU contra el hardware
> El N95 y el N97/N100 comparten arquitectura pero no el número de EUs, y de eso
> depende el fillrate disponible. El dato sale del propio equipo, no de la ficha:
> ```bash
> bash scripts/hw-report.sh > hw-report.md    # cubre esto y el resto del issue #33
> ```
> Con el conteo real hay que cerrar la columna mini PC de [[Presupuesto-de-Rendimiento]].

## Sistema

> [!danger] El equipo viene con Windows 11 Pro y hay que reinstalarlo
> No es preferencia de plataforma: Windows no expone KMS/DRM, así que no existe
> `/dev/dri` que pasar al contenedor y el modo `kms` no se puede ni ejecutar. Con
> WSL2 tampoco, porque no hay passthrough del nodo DRM ni de USB. Bajo Windows la
> mini PC solo repite lo que ya hace la laptop con `compose.dev.yml`: llvmpipe y
> `headless`. Para validar cualquier item del issue #33 hay que instalar Linux.

**Debian 13 o Ubuntu Server, sin entorno gráfico.** El requisito no es estético: si hay un escritorio corriendo, él toma el *DRM master* y el contenedor de render no puede sacar video por KMS.

```bash
sudo apt install -y avahi-daemon network-manager podman
sudo usermod -aG video,render "$USER"   # acceso a /dev/dri
sudo hostnamectl set-hostname eco-map
```

El driver `i915` viene en el kernel; no hace falta instalar nada equivalente al `vc4-kms-v3d` de la Pi. Para confirmar que la GPU está disponible:

```bash
ls -l /dev/dri/            # debe existir card0 y renderD128
sudo apt install -y mesa-utils && glxinfo -B | grep -E 'OpenGL (renderer|version)'
```

## Alternativa sin instalar Linux: Windows + modo `window`

El equipo llegó con Windows 11 Pro y reinstalarlo no siempre es viable. Con Windows la mini PC
**no es el appliance** — no hay `kms`, no hay `/dev/dri`, y Podman corre dentro de WSL2, que no
tiene passthrough del nodo DRM ni de USB, así que un contenedor allá solo repite lo que hace la
laptop. Pero sí sirve como **banco de pruebas de proyector**, nativa y sin contenedores, usando el
modo `window` en pantalla completa.

```powershell
uv sync --extra render --extra window --extra vision
$env:ECOMAP_BUS = "tcp://0.0.0.0:8765"
$env:ECOMAP_RENDER_MODE = "window"
$env:ECOMAP_WINDOW_FULLSCREEN = "1"
$env:ECOMAP_WINDOW_MONITOR = "1"      # si el proyector es la segunda salida HDMI
uv run ecomap-render
```

El web puede quedarse en la laptop, porque el render es quien escucha el bus:

```powershell
$env:ECOMAP_BUS = "tcp://<ip-de-la-minipc>:8765"
uv run ecomap-web
```

> [!tip] El escalado de pantalla de Windows cambia el tamaño del framebuffer
> Con escalado al 125%, pedir 640x360 da una ventana de 640x360 y un framebuffer de 800x450. El
> render usa el framebuffer y todo aguas abajo sale de ahi, asi que es correcto, pero explica por
> que la resolucion efectiva no es la que se pidio. En pantalla completa manda el modo de video del
> monitor.

### Qué valida así, y qué no

| Sí se valida con Windows | Queda pendiente, se muda a la Pi |
|---|---|
| Warp sobre un objeto real y el criterio de aceptación del Hito 1 | Modo `kms` sobre KMS/DRM |
| Tres caras como tres superficies | `/dev/dri` y Podman rootful con devices |
| `frame_ms` por efecto a 1080p con **GPU real** y fillrate de verdad | Arranque < 20 s y autostart con systemd |
| Presupuesto con malla 9x9 | `eco-map.local` por avahi |
| Temperatura sostenida 30 min | Shaders contra **Mesa** (i915 / V3D) |
| Modo `window`, que estaba implementado y nunca ejecutado | Cámara USB: el código es solo V4L2 |

Las dos últimas filas son las que importan al leer resultados. En Windows el compilador de shaders
es el de Intel, no el de Mesa: valida el **hardware** Gen12, no el **driver** con el que va a correr
el appliance, así que el riesgo de "funciona en mi máquina" sigue vivo hasta probar en la Pi. Y la
cámara no abre: `source.py` fija `cv2.CAP_V4L2` y la enumeración lee `/sys/class/video4linux`;
usarla en Windows pide un backend MSMF/DSHOW que todavía no existe.

## Privilegios: rootful

Se corre con **Podman rootful** ([[ADR-014-Podman-Rootful]]), así que el acceso a `/dev/dri`,
`/dev/video0` y al D-Bus del sistema sale sin trámite:

```bash
sudo podman build --target runtime -t ecomap:latest .
sudo podman-compose -f compose.minipc.yml up -d
```

El único requisito que queda es que **nada más tenga el DRM master**: sin servidor X ni Wayland
corriendo, el contenedor de render lo toma. Por eso el host va sin entorno gráfico.

Comprobaciones útiles:

```bash
ls -l /dev/dri/            # card0 y renderD128
sudo podman info --format '{{.Host.Security.Rootless}} {{.Host.OCIRuntime.Name}}'   # false crun
```

El `usermod -aG video,render` de más arriba deja de ser imprescindible con rootful, pero conviene
igual: permite depurar a mano (`glxinfo`, `v4l2-ctl`) sin `sudo`.

## Diferencias frente a la Raspberry Pi

| | Mini PC | Raspberry Pi |
|---|---|---|
| Driver Mesa | `i915` (crocus/iris) | `v3d` |
| Config de arranque | nada especial | `dtoverlay=vc4-kms-v3d` en `config.txt` |
| Arquitectura | amd64 (igual que la laptop) | arm64 |
| Compose | `compose.minipc.yml` | `compose.pi.yml` |
| Consumo | ~10–15 W | ~5–7 W |
| Núcleos | 2 | 4 |

La consecuencia práctica más útil: **la imagen de la mini PC es la misma arquitectura que la de desarrollo**, así que lo que se valida en la laptop aplica sin recompilar.

## Puesta en marcha

```bash
git clone <repo> /opt/ecomap && cd /opt/ecomap
podman build --target runtime -t ecomap:latest .
podman-compose -f compose.minipc.yml up -d
```

Arranque automático y respaldos: [[Despliegue-Raspberry]] sirve igual, cambiando el archivo compose. La unit de systemd está en `scripts/ecomap.service`.

## Qué hay que medir cuando esté montada

Esto es lo que falta para cerrar el presupuesto de rendimiento con números reales en vez de estimaciones:

- [ ] `frame_ms` de cada efecto a 1080p en modo `kms`, no en `headless`.
- [ ] Carga de CPU con el hilo de cámara activo: es la prueba de fuego de los 2 núcleos.
- [ ] Temperatura sostenida tras 30 min proyectando (el GK3PLUS tiene ventilador).
- [ ] Tiempo de encendido hasta proyección (RNF-3: menos de 20 s).

Relacionado: [[ADR-013-Plataforma-Agnostica]] · [[Raspberry-Pi-Setup]] · [[Proyector]] · [[Camara]] · [[Presupuesto-de-Rendimiento]]
