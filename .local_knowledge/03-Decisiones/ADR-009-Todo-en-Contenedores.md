---
tags: [adr, devops, docker]
estado: aceptada
fecha: 2026-09-26
reemplaza: ADR-007-Docker
---

# ADR-009 — Todo corre en contenedores, también en la Pi

**Estado:** aceptada · **Fecha:** 2026-09-26 · **Reemplaza a** [[ADR-007-Docker]]

## Contexto

[[ADR-007-Docker]] proponía Docker solo para desarrollo y systemd nativo en la Pi, por el riesgo de contenerizar `libcamera`/picamera2. Decisión del proyecto: **cámara web USB** ([[ADR-010-Camara-USB]]), lo que elimina ese riesgo — V4L2 por `/dev/video0` es un device node ordinario. Se adopta contenedores en todos los entornos.

## Decisión

`docker compose` es la **única** forma de ejecutar Eco-Map: escritorio de desarrollo y Raspberry Pi en producción. La Pi no tiene Python de la aplicación instalado; solo Docker.

Un compose base + overrides:

- `docker-compose.yml` — servicios web y render, volúmenes, red.
- `docker-compose.dev.yml` — bind mount de `src/`, reload, render por software.
- `docker-compose.pi.yml` — `/dev/dri`, cámara, `network_mode: host`, D-Bus para wifi.

## Razones

- **Un solo artefacto.** La misma imagen multi-arch corre en ambos lados; se acaba la divergencia entre "instrucciones de dev" e "instrucciones de Pi".
- Rollback = levantar el tag anterior. Sin `uv sync` a medias en una Pi sin red.
- La SD queda más protegida: la app es read-only dentro de la imagen; solo escriben los volúmenes.
- Con webcam USB no hay dependencias del sistema difíciles de contenerizar.

## Lo que hay que resolver, y cómo

| Recurso | Solución en compose |
|---|---|
| GPU / KMS | `devices` con `/dev/dri` + `group_add` video y render |
| Salida HDMI sin X | el contenedor toma el master DRM; **nada de escritorio en el host** |
| Cámara USB | `devices` con la ruta persistente `/dev/v4l/by-id/...` |
| Socket IPC | volumen nombrado `ecomap-bus` montado en ambos |
| Wifi | `network_mode: host` + socket D-Bus del sistema. Ver [[Modulo-Red]] |
| Arranque | unit systemd mínima que levanta el compose, más `restart: unless-stopped` |

## Riesgos aceptados

- **Mesa dentro del contenedor debe ser compatible con el kernel del host.** Mitigación: imagen base Debian Bookworm, misma release que Raspberry Pi OS Bookworm. Si el host sube de release mayor, hay que reconstruir la imagen. Deuda conocida.
- `network_mode: host` reduce el aislamiento de red. Aceptado: Pi de propósito único en red local. Ver [[Seguridad-y-Red]].
- Acceso al D-Bus del sistema para configurar wifi es una elevación real de privilegios. Se limita al contenedor web y se documenta en [[Modulo-Red]].
- Overhead de Docker en la Pi: despreciable en CPU, unos 100 MB de disco por imagen.

Relacionado: [[Docker-Local]] · [[Despliegue-Raspberry]] · [[ADR-003-uv]]
