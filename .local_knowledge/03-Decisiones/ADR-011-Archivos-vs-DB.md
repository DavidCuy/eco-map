---
tags: [adr, datos]
estado: aceptada
fecha: 2026-09-26
---

# ADR-011 — Contenido voluminoso en archivos, metadatos en SQLite

**Estado:** aceptada · **Fecha:** 2026-09-26

## Contexto

Tres clases de datos: configuración pequeña y consultable (superficies, capas, parámetros), definiciones de efectos (JSON + GLSL), y binarios (videos, imágenes, capturas de calibración, previews).

## Decisión

| Dato | Dónde | Por qué |
|---|---|---|
| Superficies, escenas, capas, settings | **SQLite** | pequeño, relacional, transaccional |
| `points`, `params`, `mask` | **SQLite, columna JSON** | siempre se leen y escriben enteros; no se consultan por campo |
| Manifiesto de efecto (`effect.json`) | **Archivo** (fuente de verdad) | es el artefacto que se edita y versiona |
| Catálogo de efectos | **SQLite** (espejo del manifiesto) | permite joins e integridad referencial con `layer` |
| Shaders `.glsl` | **Archivo** | texto que se edita en un editor; en la DB sería opaco |
| Previews, videos, imágenes | **Archivo** en volumen `ecomap-media` | binarios grandes; nunca BLOBs en SQLite |
| Capturas de calibración | **Archivo** temporal, se borran al terminar | ~22 imágenes por sesión |
| Homografía resultante | **SQLite** | nueve números |

Regla: **si pesa más de ~64 KB o se edita con un editor de texto, es un archivo.** La DB guarda la ruta relativa y los metadatos.

### Enmienda (2026-10-09): las escenas guardadas son archivos

La tabla de arriba dice que las escenas van en SQLite, y para la **escena de trabajo** sigue siendo así: hay una, siempre, y se autoguarda sola mientras se la toca.

Lo que cambia es que una escena **guardada con nombre** pasa a ser un archivo JSON en `scenes_dir`. La regla original no lo contemplaba porque mira el tamaño y cómo se edita; acá pesa otra cosa: la escena guardada es un **documento del operador**, no estado interno del sistema. Se copia a otro equipo, se respalda fuera del aparato, se manda por chat. Nada de eso se hace con una fila.

El archivo lleva la instalación entera —caras con su malla, capas, calibración y efecto global— y abrirlo reemplaza todo. Las capas referencian las caras **por nombre**, no por id: los ids no significan nada fuera de la base que los generó.

Eso cubre también lo que pedía el export/import de configuración (#29), que deja de necesitar su propio formato.

**Consecuencia que hay que tener presente:** abrir una escena pisa la calibración física, que cuesta veinte minutos de ajustar esquinas. Por eso antes de abrir se guarda siempre un respaldo automático, y se conservan los últimos diez. Ver [[Modulo-Calibracion]].

## Sincronización catálogo ↔ disco

Al arrancar el web, y con `POST /api/effects/reload`, se escanea el volumen de efectos:

1. Por cada `effect.json` válido → `INSERT OR REPLACE` en `effect`, `available = 1`.
2. Efectos que están en la DB pero ya no en disco → `available = 0`. **No se borran**: hay capas que los referencian.
3. Manifiesto inválido → `available = 0`, entrada en `event_log` y aviso en la UI.

## Consecuencias

- Respaldo = `ecomap.db` + volumen de efectos + volumen de media. Tres piezas, documentadas juntas en [[Despliegue-Raspberry]].
- El volumen de efectos es **separado** del de la DB: se puede compartir, versionar o reemplazar un paquete de efectos sin tocar la configuración. Ver [[Docker-Local]].
- La DB se mantiene en el orden de los cientos de KB: cabe en RAM y se respalda en un segundo.

Relacionado: [[Modelo-de-Datos]] · [[Modulo-Efectos]] · [[ADR-004-SQLite]]
