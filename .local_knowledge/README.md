---
tags: [indice]
---

# .local_knowledge — Vault de Eco-Map

Base de conocimiento del proyecto, en formato Obsidian (enlaces `[[wikilink]]`).
Abrir esta carpeta como *vault* en Obsidian y arrancar por **[[Eco-Map]]** (nodo raíz).

## Estructura

| Carpeta | Contenido |
|---|---|
| `00-MOC/` | [[Eco-Map]] — mapa de contenidos, puerta de entrada |
| `01-Vision/` | [[Vision-Producto]] · [[Casos-de-Uso]] · [[Glosario]] |
| `02-Arquitectura/` | [[Arquitectura-General]] · [[Modulo-Web-API]] · [[Modulo-Calibracion]] · [[Warping-y-Homografia]] · [[Modulo-Render]] · [[Modulo-Efectos]] · [[Modulo-Camara-Feedback]] · [[Modulo-Red]] · [[Modelo-de-Datos]] · [[Contratos-API]] · [[Presupuesto-de-Rendimiento]] · [[Estructura-Repositorio]] · [[Seguridad-y-Red]] |
| `03-Decisiones/` | ADRs 001–014 (007 y 008 reemplazadas; el modo de 012 lo fija 014) |
| `04-Hardware/` | [[Mini-PC-Setup]] · [[Raspberry-Pi-Setup]] · [[Proyector]] · [[Camara]] |
| `05-Operacion/` | [[Docker-Local]] · [[Despliegue-Raspberry]] · [[Roadmap]] |
| `06-Referencias/` | [[Referencias-Externas]] |

## Diagramas

Los diagramas Mermaid viven en [[Arquitectura-General]]: componentes con protocolos, secuencia de cambio de parámetro y secuencia de auto-calibración. El flujo de conexión wifi con rollback está en [[Modulo-Red]].

## Convenciones

- Una nota = un concepto. Si una nota trata dos cosas, se parte.
- Toda nota cierra con una línea `Relacionado:` con wikilinks.
- Las decisiones van en ADR con estado (`aceptada` / `reemplazada`) y fecha. **Una ADR aceptada no se edita**: si cambia la decisión, se escribe una nueva que la reemplace y la vieja queda con un aviso y su análisis de alternativas intacto (ver [[ADR-007-Docker]] y [[ADR-008-Camara-Picamera2]]).
- Frontmatter `tags:` para filtrar desde el grafo de Obsidian.
- Español para prosa; inglés para identificadores, código y nombres de tablas.
