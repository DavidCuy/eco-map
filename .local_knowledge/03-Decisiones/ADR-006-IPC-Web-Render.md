---
tags: [adr, arquitectura]
estado: aceptada
fecha: 2026-09-26
---

# ADR-006 — IPC entre web y render: Unix socket + JSON por línea

**Estado:** aceptada · **Fecha:** 2026-09-26

## Contexto
El proceso web debe empujar cambios al render con latencia < 100 ms (RNF-2) y recibir telemetría. Son dos procesos en la **misma** máquina.

## Decisión
**Unix domain socket** en `/run/ecomap/bus.sock`, protocolo de **JSON delimitado por `\n`** (JSON Lines). Render = servidor, web = cliente que reconecta. Mensajes en [[Contratos-API]].

## Razones
- Latencia de decenas de microsegundos, sin pila de red.
- Permisos por filesystem (`0600`), no hay puerto expuesto. Ver [[Seguridad-y-Red]].
- JSON Lines se depura con `socat` o `nc` a mano; sin esquema binario que mantener.
- El render hace `poll()` no bloqueante una vez por frame: cero impacto en el loop.

## Alternativas
- **Redis pub/sub** — un servicio más, RAM y un punto de fallo extra en una Pi. Rechazado.
- **ZeroMQ** — buen ajuste técnico, pero dependencia nativa y patrones que aquí no se necesitan.
- **Polling de SQLite desde el render** — obligaría a leer la DB en el loop; contradice [[ADR-004-SQLite]].
- **Un solo proceso con hilos** — el GIL y un loop GL bloqueante hacen que el HTTP sufra jitter; además un crash del web mataría la proyección.

## Consecuencias
- Ambos procesos se despliegan y versionan juntos; no hay negociación de versión de protocolo en v1.
- El render debe tolerar al web caído (sigue proyectando con el último estado) y el web al render caído (la UI muestra "render offline" y encola nada; al reconectar envía `scene` completa).
- En Windows no hay UDS usable de la misma forma: en desarrollo sobre Windows se cae a TCP `127.0.0.1:8765` mediante una bandera de configuración.

Relacionado: [[Arquitectura-General]] · [[Modulo-Render]]
