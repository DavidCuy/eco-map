---
tags: [arquitectura, render, matematica]
---

# Warping y homografía

> [!info] Un solo camino
> Toda superficie es una malla; el quad es la malla de 1×1 celda
> ([[ADR-015-Superficie-por-Cara-y-Malla]]). Lo que sigue describe primero el caso 1×1 porque es
> donde vive la matemática de la homografía, no porque sea un modo aparte.

## Quad: la celda 1×1

Cuatro puntos destino → homografía 3×3 desde el cuadrado unitario. Se calcula con `cv2.getPerspectiveTransform` (o a mano, sistema 8×8) y se sube al shader como `mat3`.

En el vertex shader se transforma la posición; el fragment shader muestrea el FBO del efecto. **Ojo:** interpolar UV linealmente sobre dos triángulos produce el clásico "quiebre" diagonal. Solución: coordenadas homogéneas — pasar `vec3(u,v,1)` y dividir por `w` en el fragment (perspective-correct), o subdividir el quad.

## Malla N×M (el caso general)

Grilla de vértices con UV fijo y posición editable. Se dibuja como triangle strip. Cada celda se
deforma de forma independiente → aproxima curvatura sin 3D real. Es el camino que ejecuta siempre el
render, con N=M=1 cuando la superficie es un quad plano.

Costo: N×M vértices, despreciable. La malla vive en un VBO que se re-sube solo cuando cambia la calibración, no por frame.

## Corrección de perspectiva, en la práctica

Cada celda calcula sus pesos `q` en el punto donde se cruzan sus diagonales; se pasan `uv * q` y `q`
como atributo, y el fragment divide. Un vértice compartido entre celdas toma el promedio de las que
lo tocan: así alcanza un solo VBO en vez de duplicar vértices por celda.

**Limitación conocida.** Al subdividir un quad en perspectiva, los puntos interiores se interpolan
en el espacio de pantalla, no siguiendo la proyección. El resultado es una malla que aproxima la
perspectiva por tramos y se nota una leve curvatura en el centro con subdivisiones medias. Se
corrige ajustando los puntos a mano, que es para lo que está la malla, o más adelante sembrando los
puntos con la homografía cuando la superficie viene de un 1×1.

## Orden de operaciones

```
efecto (FBO, resolución de la superficie)
   ↓ textura
malla/quad con warp  →  framebuffer de salida
   ↓
máscara (stencil)
   ↓
color: gamma / brillo / contraste por superficie
```

El efecto **nunca** conoce el warp. Eso permite intercambiar efectos sin recalibrar. Ver [[Modulo-Efectos]].

## Resolución del FBO

Igual al bounding box de la superficie en pantalla, redondeado a múltiplo de 8, con tope configurable. Una superficie chica no paga render 1080p. Ver [[Presupuesto-de-Rendimiento]].

Relacionado: [[Modulo-Calibracion]] · [[Modulo-Render]]
