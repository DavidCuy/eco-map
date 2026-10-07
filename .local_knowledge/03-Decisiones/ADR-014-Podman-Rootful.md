---
tags: [adr, devops, podman]
estado: aceptada
fecha: 2026-10-06
reemplaza-parcialmente: ADR-012-Podman-Desarrollo-Local
---

# ADR-014 — Podman en modo rootful, en todos los entornos

**Estado:** aceptada · **Fecha:** 2026-10-06 · **Reemplaza el modo rootless de** [[ADR-012-Podman-Desarrollo-Local]]

## Contexto

[[ADR-012-Podman-Desarrollo-Local]] eligió Podman y listó "rootless por defecto" como una de las razones. En la práctica el modo rootless costó más de lo que aportaba:

- En la máquina de Podman sobre WSL2, rootless quedó con la **delegación de cgroups rota** (`cgroup.subtree_control` vacío, `Delegate=no` en `user@1000.service`), y los contenedores no arrancaban: *controller `pids` is not available*. Hubo que forzar `cgroup_manager="cgroupfs"` para recuperarla.
- Pasar `/dev/dri` en rootless obliga a `group_add: [keep-groups]` (exclusivo de crun, exclusivo de otros grupos, y depende de que el proceso que lanza ya tenga los grupos). Fácil de escribir mal y difícil de diagnosticar: el device aparece como `nobody:nobody` sin error.
- La configuración de wifi del Hito 3 ([[Modulo-Red]]) necesitaría además una **regla de polkit** para que un usuario sin privilegios controle NetworkManager.

## Decisión

**Podman rootful en los tres entornos**: laptop de desarrollo, mini PC y Raspberry Pi.

En Windows, la máquina se cambia de modo con la VM detenida:

```bash
podman machine stop
podman machine set --rootful
podman machine start
podman info --format '{{.Host.Security.Rootless}}'   # false
```

En Linux es simplemente `sudo podman` / `sudo podman-compose`.

Los compose de hardware usan `group_add: [video, render]`, la forma normal cuando el contenedor ya corre como root.

## Razones

- **Una sola forma de hacer las cosas.** Deja de haber dos variantes de `group_add`, dos caminos para los devices y una regla de polkit pendiente.
- Es un equipo de **propósito único** en red local, sin usuarios múltiples: el aislamiento que da rootless protege poco aquí. Ver [[Seguridad-y-Red]].
- El render ya necesita acceso al DRM master y a `/dev/dri`; la cámara, a `/dev/video0`. La lista de privilegios reales no es corta ni siquiera en rootless.

## Costos, medidos

| Costo | Detalle |
|---|---|
| **Stores separados** | root y el usuario no comparten imágenes ni volúmenes. Al cambiar de modo hay que reconstruir la imagen y los volúmenes arrancan vacíos (en desarrollo es irrelevante: las migraciones recrean la DB). |
| **Sin `localhost` en Windows** | En rootful se pierde el forward de gvproxy. La UI se abre en la IP de la VM, no en `localhost`: `podman machine ssh "ip -4 addr show eth0 \| awk '/inet /{print \$2}'"`. Esa IP cambia cuando reinicia WSL. |
| **Menos aislamiento** | Un escape del contenedor es root en el host. Se acepta por el contexto de propósito único, y es una razón más para no exponer nunca el equipo a internet. |
| Cambio de runtime | Ninguno: sigue siendo Podman con crun, y los archivos compose y el Dockerfile no cambian salvo el `group_add`. |

## Lo que esta decisión no cambia

Podman sigue elegido frente a Docker por lo que no dependía del modo: sin daemon, sin Docker Desktop ni su licencia, y con integración nativa a systemd (Quadlet) para el arranque en el hardware.

## Si algún día se vuelve a rootless

Hay que tocar dos cosas, ambas documentadas: `group_add: [keep-groups]` en los compose de hardware, y una regla de polkit para NetworkManager. El resto del proyecto es indiferente al modo.

Relacionado: [[ADR-012-Podman-Desarrollo-Local]] · [[Mini-PC-Setup]] · [[Docker-Local]] · [[Seguridad-y-Red]]
