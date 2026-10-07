---
tags: [hardware, camara]
---

# Cámara

**Decisión v1: cámara web USB**, por presupuesto. Ver [[ADR-010-Camara-USB]].

## Qué buscar en una webcam (o en la que ya tengas)

| Criterio | Por qué importa |
|---|---|
| **Soporta MJPG a 640×480 @ 30 fps** | YUYV sin comprimir satura el USB y cae a pocos fps |
| **Controles V4L2 de exposición y balance manuales** | sin ellos, el Gray code no se decodifica de forma confiable |
| **Enfoque fijo, o autofoco desactivable** | un reenfoque a mitad de la secuencia de patrones la arruina |
| **Campo de visión amplio** | debe ver toda el área proyectada con 20 % de margen |
| Cable largo o extensión USB activa | la cámara va junto al proyector, no junto a la Pi |

Verificar antes de comprar o de dar por buena una que ya tengas:

```bash
v4l2-ctl --list-formats-ext -d /dev/video0   # ¿hay MJPG?
v4l2-ctl --list-ctrls -d /dev/video0         # ¿exposure_auto? ¿white_balance_automatic?
```

Modelos que suelen cumplir: Logitech C270 (barata, cumple lo mínimo), C920 (mejor óptica y controles). Las webcams genéricas muy baratas a veces exponen los controles pero los ignoran — probar antes de calibrar.

## Colocación

- **Lo más cerca posible del eje del proyector**, encima o al lado. Menos paralaje = mejor homografía y menos oclusión.
- Debe ver toda el área proyectada con margen.
- **Fija y rígida.** Si se mueve, la calibración automática queda inválida.
- Enfoque bloqueado (cinta si hace falta).

## Ajustes para calibrar

- Exposición y balance de blancos manuales y fijos durante toda la secuencia de patrones.
- Ganancia baja: el ruido rompe el umbralizado.
- 15 fps es suficiente; más solo cuesta CPU.

## Opciones para v2

| Cámara | Pros | Contras |
|---|---|---|
| Pi Camera Module 3 | ISP nativo, stream `lores` sin costo de CPU, autofoco | cuesta dinero, exige libcamera/picamera2 en el contenedor |
| Módulo NoIR + iluminador IR | detecta movimiento casi a oscuras, sin contaminar la proyección | color inútil para calibración de color |

El caso NoIR es interesante para efectos reactivos: la cámara IR no ve la luz visible del proyector, así que **elimina el lazo de realimentación positiva** descrito en [[Modulo-Camara-Feedback]].

Relacionado: [[Modulo-Camara-Feedback]] · [[Proyector]] · [[ADR-010-Camara-USB]]
