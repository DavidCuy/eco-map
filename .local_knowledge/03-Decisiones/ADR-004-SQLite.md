---
tags: [adr, datos]
estado: aceptada
fecha: 2026-09-26
---

# ADR-004 — SQLite como única base de datos

**Estado:** aceptada · **Fecha:** 2026-09-26

## Contexto
Los datos son pocos y de baja frecuencia: superficies, escenas, capas, parámetros, calibraciones. Un solo operador. La Pi debe poder apagarse por corte de luz sin corromper nada.

## Decisión
SQLite en `data/ecomap.db`, con `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`. Esquema en [[Modelo-de-Datos]].

## Razones
- Cero servicio que administrar; respaldo = copiar un archivo.
- Volumen real: decenas de filas. Cualquier otra cosa es sobreingeniería.
- Exportar/importar configuración completa es trivial.

## Reglas duras
1. **Solo el proceso web escribe.** El render nunca abre la DB; recibe el estado por el socket. Evita contención y locks a 60 fps. Ver [[ADR-006-IPC-Web-Render]].
2. Los movimientos de sliders se **debouncean 500 ms** antes de persistir: no hay que escribir en la tarjeta SD 60 veces por segundo. La SD se desgasta y es la causa número uno de muerte de una Pi.
3. La DB va en un volumen/carpeta fuera de la imagen Docker.

## Alternativas
- **JSON en disco** — más simple aún, pero sin transacciones y con riesgo de archivo a medio escribir en un corte de luz.
- **Postgres** — imposible de justificar aquí.

## Consecuencias
- ORM opcional. Recomendado: `sqlite3` + funciones de repositorio, o SQLModel si se quiere tipado. No hace falta Alembic; migraciones por scripts SQL numerados.

Relacionado: [[Modelo-de-Datos]] · [[Raspberry-Pi-Setup]]
