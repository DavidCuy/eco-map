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

## Reparto: HTMX en los paneles, Alpine en el workspace

El canvas necesita el estado de la malla **en el cliente** de todas formas: arrastre, nudge y zoom
trabajan sobre los puntos sin ida y vuelta al servidor. Intercambiar HTML desde el servidor para esa
parte dejaría dos copias del mismo estado desincronizándose, así que el workspace usa Alpine con
`fetch` contra la API JSON.

Los paneles que son solo formularios — efecto activo, blackout, cámara, escenas — siguen con HTMX,
que para eso es más simple. La convención de doble representación ([[Modulo-Web-API]]) sigue
valiendo para ellos.

**Los sliders de parámetros tampoco usan HTMX**, por la misma razón que el canvas: cada respuesta de
HTMX reemplaza el fragmento entero, y hacer eso mientras el dedo arrastra arranca el control. La
regla que sale de esto: *si el usuario está interactuando de forma continua, el servidor no puede
reemplazarle el DOM debajo*. Formularios con HTMX; arrastres, con JS.

## Estado: implementado

El rediseño entró con el Hito 1. Lo que quedó:

- Barra de estado con fps, frame time y su pico, temperatura y estado del render, alimentada por
  WebSocket.
- Canvas con el preview del render de fondo y los handles encima, en dos capas: así no hay que leer
  píxeles del stream, que ensuciaría el canvas por CORS.
- Handles de malla arrastrables con punteros (sirve mouse y dedo), nudge con flechas de 1 px y 10 px
  con Shift, definidos en **píxeles de la salida del proyector** y no de la pantalla.
- Recuadro ampliado 4× de la esquina activa. Se calcula sobre el tamaño **mostrado** del preview, no
  sobre la resolución de salida: la imagen va estirada al stage.
- Tira de caras para saltar entre superficies de un toque.
- Paneles plegables para efecto, cámara y eventos: no compiten con el canvas.

Ver [[Roadmap]].

Relacionado: [[Modulo-Web-API]] · [[Modulo-Calibracion]] · [[ADR-002-HTMX-Alpine]] · [[ADR-015-Superficie-por-Cara-y-Malla]]
