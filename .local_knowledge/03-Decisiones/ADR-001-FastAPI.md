---
tags: [adr, backend]
estado: aceptada
fecha: 2026-09-26
---

# ADR-001 — FastAPI como backend

**Estado:** aceptada · **Fecha:** 2026-09-26

## Contexto
Hace falta un backend Python que sirva HTML, exponga API JSON, maneje WebSocket para telemetría y stream MJPEG de cámara, corriendo en una Pi junto a un proceso de render que ya consume GPU y CPU.

## Decisión
**FastAPI** con Uvicorn, un solo worker.

## Razones
- WebSocket y `StreamingResponse` (MJPEG) nativos, sin extensiones.
- Pydantic v2 valida los parámetros de efectos y la geometría de calibración — que son la fuente principal de errores tontos en este dominio.
- `/docs` gratis: sirve para depurar desde el celular sin frontend.
- Se integra con Jinja2 sin ceremonia, así que la misma app sirve UI y API. Ver [[Modulo-Web-API]].

## Alternativas
- **Flask** — más simple, pero WebSocket exige extensión y no hay validación de entrada.
- **Litestar** — comparable y con buen DI, comunidad menor.
- **Django** — sobrepeso enorme para 20 endpoints en una Pi.

## Consecuencias
- Un solo worker Uvicorn: el estado en memoria (conexión al bus IPC) es seguro. **No escalar a múltiples workers** sin repensarlo.
- Los handlers que tocan SQLite se declaran `def` (no `async def`) para que corran en threadpool.

Relacionado: [[ADR-002-HTMX-Alpine]] · [[Contratos-API]]
