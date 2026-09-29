---
tags: [vision]
---

# Visión de producto

## Problema

El videomapping típico exige laptop + software propietario (MadMapper, Resolume) + operador. Para instalaciones fijas y pequeñas (fachada de local, escenografía, arte de barrio) eso es caro y frágil.

## Propuesta

Una caja: Raspberry Pi + proyector + cámara USB/CSI. Se enciende y proyecta. Se configura desde el celular o laptop entrando a `http://eco-map.local:8000`.

## Principios

1. **Cero teclado en la Pi.** Toda configuración por web, **incluido el wifi**. Ver [[Modulo-Web-API]] · [[Modulo-Red]].
2. **Persistente.** Se corta la luz, vuelve, retoma la escena activa. Ver [[ADR-004-SQLite]].
3. **La cámara es parte del sistema, no un accesorio.** Ver [[Modulo-Camara-Feedback]].
4. **Efectos como datos, no como código.** Un efecto = shader GLSL + manifiesto de parámetros, en archivos. Ver [[Modulo-Efectos]] · [[ADR-011-Archivos-vs-DB]].
5. **Simple primero.** SQLite, un proceso de render, sin colas ni brokers. Ver [[ADR-006-IPC-Web-Render]].
6. **Desarrollable sin hardware.** Contenedores, render headless, cámara simulada. Ver [[Modulo-Render]].

## Fuera de alcance v1

- Múltiples proyectores / edge blending.
- Sincronización de audio / timeline tipo DAW.
- Multiusuario con login. (v1: red local confiable, sin auth, sin tabla de usuarios. Ver [[Seguridad-y-Red]].)
- 3D mesh mapping real (solo quads + grilla 2D).
- Cámara CSI. v1 usa webcam USB por presupuesto. Ver [[ADR-010-Camara-USB]].

Relacionado: [[Casos-de-Uso]] · [[Roadmap]] · [[Eco-Map]]
