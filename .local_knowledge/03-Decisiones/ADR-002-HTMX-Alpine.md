---
tags: [adr, frontend]
estado: aceptada
fecha: 2026-09-26
---

# ADR-002 — UI: Jinja2 + HTMX + Alpine.js + Pico.css

**Estado:** aceptada · **Fecha:** 2026-09-26

## Contexto
Se pidió una interfaz web **muy ligera** que combine bien con FastAPI. La UI corre en un navegador de celular o laptop contra un servidor en una Raspberry Pi. Hay una parte interactiva no trivial: arrastrar esquinas de calibración sobre un canvas y mover sliders con feedback en vivo.

## Decisión
Renderizado en servidor con **Jinja2**, interactividad con **HTMX 2** + **Alpine.js 3**, estilos con **Pico.css**. Sin Node, sin bundler, sin paso de build. Assets servidos desde `static/` (no CDN: la Pi puede estar sin internet).

Peso total: HTMX ~14 KB + Alpine ~15 KB + Pico ~12 KB gzip ≈ **41 KB**.

## Razones
- **Cero build.** Editar un `.html` y recargar. En un proyecto de hardware, cada herramienta extra es una fuente de fricción.
- **HTMX encaja con FastAPI**: los endpoints devuelven fragmentos Jinja2 y se intercambian en el DOM. El CRUD (superficies, escenas, capas) se resuelve sin escribir JS.
- **Alpine cubre el resto**: el canvas de calibración es estado local de una vista (posición de handles, handle activo, zoom). `x-data`/`x-on` alcanza; no hace falta un framework con router y virtual DOM.
- **La UI de parámetros se genera desde el manifiesto del efecto** con un macro Jinja2 por tipo. Con SPA habría que duplicar ese mapeo en JS. Ver [[Modulo-Efectos]].
- Pico.css da un tema oscuro decente sin escribir CSS ni llenar el HTML de clases.

## Alternativas
- **React/Vue + Vite** — mejor para apps grandes; aquí agrega Node, build, y un contrato JSON duplicado. Rechazado.
- **NiceGUI / Reflex / Streamlit** — muy rápido para arrancar, pero mantienen estado de UI en el servidor por sesión y cuestan CPU/RAM en la Pi; personalizar un canvas con drag & drop pelea contra el framework. Rechazado.
- **HTMX solo, sin Alpine** — insuficiente para el canvas de calibración.
- **Datastar** — un solo script cubre ambos roles, pero comunidad chica; reconsiderar en v2.

## Consecuencias
- Un poco de JS a mano para el canvas (~200 líneas). Aceptado.
- Los endpoints tienen doble representación (HTML si `HX-Request`, JSON si no). Convención documentada en [[Modulo-Web-API]].
- Los assets se versionan en el repo, no se instalan con npm.

Relacionado: [[ADR-001-FastAPI]] · [[Modulo-Calibracion]]
