---
tags: [adr, devops, podman]
estado: aceptada
fecha: 2026-09-29
complementa: ADR-009-Todo-en-Contenedores
---

# ADR-012 — Podman como runtime de contenedores en desarrollo local

**Estado:** aceptada · **Fecha:** 2026-09-29 · **Complementa a** [[ADR-009-Todo-en-Contenedores]]

## Contexto

[[ADR-009-Todo-en-Contenedores]] fija que todo corre en contenedores, en todos los entornos, pero no dice con qué runtime. En la máquina de desarrollo se decidió usar **Podman** en vez de Docker.

## Decisión

**Podman para desarrollo local.** Los archivos `Dockerfile` y `docker-compose*.yml` **no cambian**: son OCI y compose estándar, y Podman los consume tal cual.

```bash
podman build -t ecomap:latest .
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
podman logs -f eco-map_render_1
podman-compose -f docker-compose.yml -f docker-compose.dev.yml down
```

El proveedor de compose es **`podman-compose`** (instalable con `uv tool install podman-compose`), no `docker-compose`. Ver la tabla de trampas.

Verificado con Podman 6.0.2 rootless sobre WSL2: build de amd64, los dos servicios arriba, bus por socket Unix en volumen compartido, bind mounts con hot reload (marcador creado en el host visible dentro del contenedor y watchfiles disparando), preview MJPEG y API respondiendo. Medido en `headless` a 640x360: 29.97 fps con tope de 30, `frame_ms` 0.65.

## Razones

- **Rootless por defecto.** El contenedor corre como usuario sin privilegios. Para un proyecto que en la Pi va a tocar `/dev/dri`, `/dev/video0` y el D-Bus del sistema, arrancar desde rootless obliga a ser explícito con cada permiso en vez de esconderlo tras un daemon root.
- **Sin daemon.** No hay servicio que quede colgado ni que haya que arrancar antes de trabajar.
- **Sin Docker Desktop.** Evita la dependencia de una licencia comercial para uso corporativo.
- **Quadlet en la Pi.** Podman integra unidades systemd nativamente (`podman generate systemd` / archivos `.container`), que es más limpio que una unit `oneshot` que llama a `compose up`. Candidato a reemplazar el arranque de [[Despliegue-Raspberry]] en US-28.

## Costos y trampas, todas comprobadas

| Tema | Detalle |
|---|---|
| **`podman compose` necesita proveedor externo** | Podman delega en un binario externo. Si hay Docker Desktop instalado, elige su `docker-compose.exe`, que habla con Podman **solo** si el proxy de API Docker de la máquina levantó; cuando no levanta, falla con `exit status 143` y sin explicación. Por eso el proveedor elegido es `podman-compose` (Python, `uv tool install podman-compose`), que habla con Podman directo y no depende de nada de Docker. |
| **Nombres de contenedor según proveedor** | `podman-compose` genera `eco-map_web_1` (guion bajo) y `docker-compose` genera `eco-map-web-1` (guion). Los comandos `podman logs`/`exec` de cualquier documentación hay que ajustarlos al proveedor que se use. |
| **Sin cross-build arm64 en Windows** | WSL2 secuestra `binfmt_misc` (`/proc/sys/fs/binfmt_misc` devuelve *Too many levels of symbolic links*), así que `--platform linux/arm64` falla con *Exec format error*. Peor: intentar registrar qemu con `multiarch/qemu-user-static --reset` **dejó la máquina de Podman sin responder** (SSH caído, `wsl.exe` fallando con `0xffffffff`); se recupera con `wsl --shutdown` y `podman machine start`. **No hacerlo.** La imagen arm64 se construye en la Pi o en CI con runners Linux. |
| **SELinux** | En hosts Fedora/RHEL los bind mounts necesitan sufijo `:z` (compartido) o `:Z` (exclusivo), o el contenedor no puede leerlos. En WSL y Debian no hace falta. |
| **Puertos bajo 1024** | Rootless no puede publicarlos sin ajustar `net.ipv4.ip_unprivileged_port_start`. Eco-Map usa 8000 y 8001, así que no aplica. |
| **Devices en rootless** | Pasar `/dev/dri` requiere que el usuario tenga permiso real sobre el device (grupos `video` y `render`); rootless no puede conceder lo que el usuario no tiene. Es justamente lo que ya pide [[Raspberry-Pi-Setup]]. |

## Alcance

Esta decisión cubre **desarrollo local**. En la Pi el runtime queda por definir al cerrar US-28: Podman con Quadlet es el favorito por la integración con systemd, pero hay que validarlo con acceso a KMS/DRM en rootless, que es el punto que puede obligar a volver a Docker o a correr Podman como root.

## Alternativas

- **Docker Desktop** — funciona y es lo más probado, pero agrega daemon, licencia y una VM propia.
- **Docker Engine en WSL directo** — sin licencia, pero daemon root y una VM más que mantener.
- **nerdctl / containerd** — menos fricción que Docker, pero ecosistema compose más pobre.

Relacionado: [[Docker-Local]] · [[Despliegue-Raspberry]] · [[ADR-009-Todo-en-Contenedores]]
