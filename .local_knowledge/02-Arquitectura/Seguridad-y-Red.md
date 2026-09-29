---
tags: [arquitectura, seguridad, red]
---

# Seguridad y red

## Postura v1

La Pi vive en una red local (o en su propio AP). **Sin login** en v1: agregar auth antes de que haya algo que proteger cuesta tiempo y complica el uso a oscuras con un celular.

Mitigaciones que sí van en v1:

- Bind por defecto a `0.0.0.0:8000` **pero** documentar el bloqueo por firewall y no exponer a internet jamás.
- `mDNS` (`avahi`) → `http://eco-map.local:8000`, sin repartir IPs.
- El socket IPC es un **Unix domain socket** con permisos `0600`, no un puerto TCP. Nada de red entre web y render.
- CORS cerrado (la UI se sirve desde el mismo origen).
- Los endpoints de import de configuración validan el JSON con Pydantic antes de tocar la DB.
- Los shaders se cargan de disco, **no** se aceptan por HTTP en v1: subir GLSL arbitrario es ejecución de código en la GPU.

## Configuración de red desde la web

La Pi se configura sin teclado: escanear wifi, conectarse, modo AP de rescate y mDNS. Diseño completo en **[[Modulo-Red]]**.

Consecuencias de seguridad de esa capacidad, y cómo se acotan:

- El contenedor web monta el **socket D-Bus del sistema** para hablar con NetworkManager. Es la mayor elevación de privilegio del diseño: control de la red del host. Se limita a ese contenedor y a ese módulo. Ver [[ADR-009-Todo-en-Contenedores]].
- La **PSK nunca toca `ecomap.db`** ni los logs: la guarda NetworkManager. En los logs se enmascara.
- `GET /api/network/networks` expone las redes vecinas — información de reconocimiento. Aceptado en LAN; primer endpoint a proteger cuando haya auth.
- Rate limit en los endpoints de red: probar PSKs desde la misma LAN es un ataque plausible.
- Cambiar de red **no debe** poder dejar la Pi inalcanzable: conexión con rollback automático y AP de rescate. Es tanto un requisito de usabilidad como de disponibilidad.

## Cuándo agregar auth

Cuando aparezca alguna de estas: la Pi se conecta a wifi compartido o público, hay más de un operador, o se habilita subir efectos por la web. Ahí: token único en `setting`, cookie firmada, y HTTPS con certificado autofirmado.

## Modo AP (punto de acceso)

Para instalaciones sin wifi disponible, o como rescate cuando no hay red conocida a los 45 s de arrancar: hotspot vía NetworkManager, SSID `eco-map-setup`, la Pi en `192.168.50.1`. Detalle en [[Modulo-Red]], despliegue en [[Despliegue-Raspberry]].

Relacionado: [[Modulo-Red]] · [[Modulo-Web-API]] · [[Vision-Producto]]
