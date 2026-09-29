---
tags: [glosario]
---

# Glosario

- **Superficie (surface)** — región física a mapear. En datos: un quad o malla con sus puntos de destino. Ver [[Modelo-de-Datos]].
- **Warping** — deformar la imagen de origen para que calce con la superficie real. Ver [[Warping-y-Homografia]].
- **Homografía** — matriz 3x3 que mapea un plano a otro. Base del warping de quads.
- **Keystone** — caso particular de warping: corregir el trapecio por proyector no perpendicular.
- **Máscara (mask)** — polígono que recorta lo que se ve, para no derramar luz fuera del objeto.
- **Efecto (effect)** — shader GLSL + manifiesto JSON de parámetros. Ver [[Modulo-Efectos]].
- **Escena (scene)** — snapshot activable: superficies + efectos + parámetros.
- **Capa (layer)** — asignación efecto↔superficie con orden y blend mode.
- **Uniform** — variable que la app pasa al shader (tiempo, color, intensidad, textura de cámara).
- **Framebuffer / FBO** — textura fuera de pantalla donde se renderiza el efecto antes de deformarlo.
- **Gray code** — secuencia de patrones binarios proyectados para identificar cada píxel desde la cámara. Ver [[Modulo-Camara-Feedback]].
- **KMS/DRM** — API de video de Linux para dibujar en pantalla sin servidor X. Ver [[ADR-005-Motor-Render-OpenGL]].
- **IPC** — comunicación entre el proceso web y el de render. Ver [[ADR-006-IPC-Web-Render]].
- **Headless** — modo del render sin salida física: dibuja a un FBO y lo publica como MJPEG. Base del desarrollo sin hardware. Ver [[Modulo-Render]].
- **Volumen** — almacenamiento persistente de Docker. Cuatro: `ecomap-data`, `ecomap-effects`, `ecomap-media`, `ecomap-bus`. Ver [[Docker-Local]].
- **NetworkManager** — servicio de red del host que la web controla por D-Bus para escanear y conectar wifi. Ver [[Modulo-Red]].
- **Checkpoint / rollback de red** — mecanismo que revierte un cambio de red si nadie confirma que funcionó. Evita dejar la Pi inalcanzable.
- **Modo AP** — la Pi levanta su propio wifi (`eco-map-setup`) cuando no hay red conocida.
- **mDNS** — resolución de `eco-map.local` en la LAN sin DNS ni IP fija.

Relacionado: [[Eco-Map]]
