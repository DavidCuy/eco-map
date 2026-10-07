---
tags: [adr, calibracion, render, ui]
estado: aceptada
fecha: 2026-10-06
---

# ADR-015 — Una superficie por cara, malla como modelo único

**Estado:** aceptada · **Fecha:** 2026-10-06

## Contexto

Se analizó un video de referencia de videomapping doméstico: dos cajas apiladas, un proyector portátil y un celular como control. El flujo que se ve ahí resolvió varias preguntas que estaban abiertas en [[Modulo-Calibracion]] y [[Roadmap]].

## Decisiones

### 1. Una superficie por cada cara física

No se mapea el objeto, se mapean **sus caras**. Dos cajas apiladas con tres caras visibles cada una son hasta seis superficies independientes, cada una con su calibración y sus capas.

Consecuencia: el número de superficies sube rápido, así que la UI tiene que hacer cómodo **crear, duplicar, nombrar y seleccionar** superficies. Lo que en el modelo de datos ya está (tabla `surface`, sin jerarquía) alcanza; lo que falta es que la pantalla no se vuelva una lista inmanejable.

Queda **abierto**: si conviene agrupar superficies por objeto (un "grupo" para las seis caras de las dos cajas) para activarlas y moverlas juntas. No se decide ahora; se decidirá cuando duela.

### 2. La malla es el modelo único; el quad es su caso 1×1

Hasta ahora había dos caminos: quad por homografía (Hito 1) y malla N×M como refinamiento posterior (Hito 6). **Se unifican**: toda superficie es una malla, y una malla de 1×1 celda son exactamente los cuatro puntos de un quad.

Razones:

- Las superficies reales no son todas planas ni regulares — es la razón que dio el proyecto: *"las superficies pueden ser distintas"*.
- Un solo camino de render: un VBO, un draw, una ruta de código. Mantener dos implementaciones del warp y que ambas calcen con la misma calibración es trabajo doble y fuente de bugs sutiles.
- En el video de referencia la deformación durante el arrastre es curva y diagonal, no trapezoidal: la malla no es un lujo, es lo que se usa.

Consecuencia en el plan: la malla **se adelanta al Hito 1** y deja de ser un ítem del Hito 6. La homografía sigue existiendo como el cálculo de la celda 1×1, no como un modo aparte.

### 3. El derrame de luz se conserva

Lo proyectado es más grande que el objeto y se ve un halo alrededor. **No es un defecto a tapar**: sirve para ver dónde caen los límites de la superficie mientras se calibra.

Consecuencia: las **máscaras bajan de prioridad**. Dejan de ser requisito de "instalación real" y pasan a ser una herramienta opcional de acabado, para cuando alguien quiera la instalación final sin halo.

### 4. Los efectos siguen siendo shaders

El video termina proyectando una imagen estática (papel de regalo) mapeada por cara. **No se adopta**: el catálogo sigue siendo GLSL con parámetros, como está en [[Modulo-Efectos]] y [[ADR-011-Archivos-vs-DB]]. Un tipo de efecto "textura/imagen" es una extensión posible, no parte del camino actual.

### 5. Proyectar la interfaz de edición: fuera de alcance por ahora

En el video, los contornos y los puntos de control se proyectan **sobre el objeto real**, así que el operador los ve a distancia sin mirar la pantalla. Es claramente útil y barato de sumar sobre el pipeline que ya existe, pero no entra ahora. Queda anotado como idea con fundamento, no como requisito.

### 6. El dashboard toma la dirección visual de esa app

Layout centrado en el canvas, tema oscuro, barra de herramientas compacta, miniaturas por superficie. **Sin perder lo técnico que ya existe**: fps, frame time y su pico, temperatura, estado del render y estado de la cámara siguen visibles. La referencia es la disposición, no el contenido: lo que se muestra es lo que este sistema mide. Detalle en [[Direccion-de-UI]].

## Consecuencias sobre el plan

| Antes | Ahora |
|---|---|
| Hito 1: quad por homografía | Hito 1: malla N×M, 1×1 por defecto |
| Hito 6: malla | — (absorbido por Hito 1) |
| Hito 6: máscaras, requisito | Post-v1: máscaras, opcional |
| Dashboard: funcional, sin dirección | Hito 1: layout centrado en canvas |

Relacionado: [[Modulo-Calibracion]] · [[Warping-y-Homografia]] · [[Direccion-de-UI]] · [[Roadmap]]
