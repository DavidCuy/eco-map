---
tags: [adr, plataforma, devops]
estado: aceptada
fecha: 2026-10-06
---

# ADR-013 — Plataforma agnóstica: mini PC x86 de referencia, Raspberry Pi soportada

**Estado:** aceptada · **Fecha:** 2026-10-06

## Contexto

El proyecto nació asumiendo Raspberry Pi ([[Vision-Producto]], [[ADR-005-Motor-Render-OpenGL]]). Apareció una **mini PC x86** disponible (KAMRUI GK3PLUS, Intel Celeron N3350, 8 GB, SSD 256 GB, 2×HDMI), y el hardware de Pi va a tardar.

Además había un criterio bloqueado: la imagen arm64 no se puede construir desde Windows porque WSL2 no permite usar `binfmt_misc` ([[ADR-012-Podman-Desarrollo-Local]]).

## Decisión

**El sistema es agnóstico de plataforma.** Corre en x86-64 y en arm64, con el mismo código y la misma imagen por arquitectura. La **mini PC es la plataforma de referencia** (la que se valida primero y de la que salen los números de rendimiento); la **Raspberry Pi sigue siendo objetivo soportado**.

Qué lo hace agnóstico, y qué cuesta:

| Pieza | Cómo queda |
|---|---|
| Contexto GL | `kms` por SDL2/KMSDRM en las dos: en la mini PC con driver `i915`, en la Pi con `v3d`. Mismo código. |
| Shaders | **Siguen escritos en GLSL ES 3.0.** Es el precio del agnosticismo: en x86 habría GL 4.x de escritorio disponible. El header se elige en runtime, ya implementado. |
| Imagen | Un solo `Dockerfile`; la arquitectura la define `--platform` o el campo `platform` del compose. |
| Cámara | Webcam USB por V4L2 en ambas ([[ADR-010-Camara-USB]]). Sin cambios. |
| Almacenamiento | SSD en la mini PC, SD o SSD USB en la Pi. El debounce de 500 ms de [[ADR-004-SQLite]] queda como buena práctica; en la Pi sigue siendo supervivencia del hardware. |

## Un Dockerfile, tres compose

Los tres entornos tienen **su propio archivo compose autocontenido**, sin overrides encadenados:

| Archivo | Destino | Particularidad |
|---|---|---|
| `compose.dev.yml` | laptop (desarrollo) | target `dev`, llvmpipe, 640×360@30, bind mounts, cámara simulada |
| `compose.minipc.yml` | mini PC x86 | `kms`, `/dev/dri` (i915), host network, D-Bus, 1080p60 |
| `compose.pi.yml` | Raspberry Pi | `kms`, `/dev/dri` (v3d), `platform: linux/arm64` |

Se eligió **un solo Dockerfile con dos targets** (`runtime` y `dev`) en vez de tres Dockerfiles: el contenido sería idéntico en un 90 % y tres copias divergen sin que nadie lo note. `libgl1-mesa-dri` ya trae los tres drivers que se necesitan (llvmpipe, crocus/iris, v3d), así que ni la capa de paquetes cambia entre plataformas.

Partirlo **sí se justificará** cuando aparezca aceleración de video por hardware para el efecto `video_loop`: ahí la mini PC quiere VAAPI (`intel-media-va-driver`) y la Pi quiere `v4l2m2m`. Ese es el momento de agregar stages por plataforma, no antes.

El target `dev` existe para poder correr la suite dentro del contenedor:

```bash
podman exec eco-map_web_1 pytest -q      # 23 passed
```

## Matriz de validación

El agnosticismo tiene un costo real: cada hito se valida en más de un lugar.

| Dónde | Qué valida | Qué no puede validar |
|---|---|---|
| **Laptop** (Windows, Iris Xe) | tests, lógica, web, render con GPU real en `window`/standalone, contenedores en `headless` | cámara real (sin passthrough USB), modo `kms`, arm64 |
| **Mini PC** (referencia) | `kms` con proyector, webcam USB, cifras de rendimiento, arranque autónomo | arm64, driver V3D |
| **Raspberry Pi** | build arm64, shaders contra V3D, presupuesto en VideoCore | — |

## Consecuencias

- [[Presupuesto-de-Rendimiento]] pasa a tener dos columnas. El N3350 **no es más rápido que una Pi en CPU**: son 2 núcleos Goldmont de 2016 contra 4 de la Pi 4. La GPU (HD 500, 12 EUs) sí tiene más margen que el VideoCore VI. El cuello se mueve de GPU a CPU, y el hilo de cámara ([[Modulo-Camara-Feedback]]) es el primer candidato a sufrir.
- HDMI 1.4b en la mini PC: 1080p60 sí, 4K solo a 30 Hz. Irrelevante para v1.
- 2×HDMI en la mini PC abre el camino de multi-proyector con edge blending, que estaba listado como post-v1 en [[Roadmap]].
- La imagen arm64 sigue sin construirse. Se construye **en la Pi** (nativo) o en CI con runners Linux; es lo único que mantiene abierto el criterio correspondiente de US-02.
- El riesgo "funciona en mi máquina" de [[ADR-005-Motor-Render-OpenGL]] no desaparece: ahora hay **tres** drivers de Mesa en juego (llvmpipe, i915, v3d) y un shader puede compilar en dos y fallar en el tercero.

## Alternativas

- **Solo mini PC x86** — permitiría GL 4.x de escritorio y una sola plataforma de validación, pero tira a la basura la premisa de bajo costo de [[Vision-Producto]] y la Pi ya comprada.
- **Solo Raspberry Pi** — mantiene el proyecto bloqueado esperando hardware, y deja sin usar la máquina que ya está disponible.

Relacionado: [[Mini-PC-Setup]] · [[Raspberry-Pi-Setup]] · [[Docker-Local]] · [[ADR-009-Todo-en-Contenedores]] · [[ADR-012-Podman-Desarrollo-Local]]
