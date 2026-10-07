---
tags: [arquitectura, frontend, ui]
---

# Dirección de UI

Referencia visual: la app de videomapping del video analizado ([[ADR-015-Superficie-por-Cara-y-Malla]]). Se toma **la disposición**, no el contenido: lo que se muestra es lo que este sistema mide.

## Qué se copia de la referencia

- **El canvas manda.** Ocupa la mayor parte de la pantalla; lo demás son controles alrededor. Hoy el dashboard es una pila de tarjetas de texto: eso sirve para el esqueleto, no para calibrar.
- **Tema oscuro, acentos saturados.** Se opera a oscuras, al lado del proyector. Ya está resuelto con Pico en modo oscuro.
- **Barra de herramientas compacta** bajo el canvas: crear superficie, subdividir malla, resetear, blackout, patrón de prueba.
- **Miniaturas por superficie** en una tira lateral o inferior, para saltar entre caras sin volver a una lista. Con una superficie por cara ([[ADR-015-Superficie-por-Cara-y-Malla]]) van a ser muchas.
- **Pensado para el pulgar.** Se usa de pie, con una mano, mirando la pared y no la pantalla. Controles grandes, nada de menús anidados.

## Qué NO se copia

- **La telemetría se queda.** fps, `frame_ms` con su pico, temperatura, estado del render y estado de la cámara siguen visibles. Son lo que permite saber si la Pi está sufriendo, y ninguna app comercial los muestra porque no corren en hardware al límite.
- **La doble representación se queda.** Los endpoints siguen devolviendo fragmento HTML con `HX-Request` y JSON sin él ([[Modulo-Web-API]]).
- **Sin framework.** Jinja2 + HTMX + Alpine + Pico, sin build ([[ADR-002-HTMX-Alpine]]). La dirección visual no justifica meter Node.

## Estructura propuesta

```
┌─────────────────────────────────────┐
│ Eco-Map    ● render 60fps 1.6ms 54° │  barra de estado, siempre visible
├─────────────────────────────────────┤
│                                     │
│        CANVAS                       │  preview + handles de la malla
│        (superficie activa)          │
│                                     │
├─────────────────────────────────────┤
│ [+ cara] [malla 3×3] [reset] [⬛]   │  herramientas
├─────────────────────────────────────┤
│ [cara A][cara B][cara C][cara D] +  │  tira de superficies
├─────────────────────────────────────┤
│ efecto: plasma   ▸ velocidad ▁▂▃▅   │  parámetros del efecto activo
└─────────────────────────────────────┘
```

La tarjeta de cámara y el log de eventos pasan a una pantalla aparte o a un panel plegable: no compiten con el canvas.

## Cuándo

Entra con el **Hito 1**, junto con el canvas de calibración: rediseñar el dashboard antes de que exista el canvas sería pintar una pantalla que va a cambiar entera. Ver [[Roadmap]].

Relacionado: [[Modulo-Web-API]] · [[Modulo-Calibracion]] · [[ADR-002-HTMX-Alpine]] · [[ADR-015-Superficie-por-Cara-y-Malla]]
