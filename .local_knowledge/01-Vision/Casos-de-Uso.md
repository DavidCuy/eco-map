---
tags: [vision, requisitos]
---

# Casos de uso

## CU-01 Definir superficie
Usuario abre la web, crea una **superficie**, la ve como quad sobre el preview y arrastra las 4 esquinas hasta que la proyección encaja con el objeto físico. Ver [[Modulo-Calibracion]].

## CU-02 Refinar con grilla
Superficie no plana (columna, tela). Usuario sube la resolución de la malla (3x3, 5x5) y mueve puntos interiores. Ver [[Warping-y-Homografia]].

## CU-03 Auto-calibrar con cámara
Usuario pulsa *Auto-calibrar*. El sistema proyecta patrones (Gray code / ArUco), la cámara los lee y calcula la homografía proyector↔cámara. Ver [[Modulo-Camara-Feedback]].

## CU-04 Asignar efecto
Usuario elige un efecto del catálogo, lo asigna a una superficie y ajusta parámetros con sliders. El cambio se ve **en vivo** (<100 ms). Ver [[Contratos-API]].

## CU-05 Guardar escena
Conjunto de superficies + efectos + parámetros = **escena**. Se guarda y se puede activar al arranque. Ver [[Modelo-de-Datos]].

## CU-06 Efecto reactivo
La cámara detecta movimiento en la zona proyectada y el efecto responde (partículas siguen a la persona). Ver [[Modulo-Camara-Feedback]].

## CU-07 Modo kiosco
Al bootear, la Pi arranca render + web sin intervención. Ver [[Despliegue-Raspberry]].

## CU-08 Configurar el wifi sin teclado
Instalación en un lugar nuevo. La Pi no encuentra red conocida y levanta el AP `eco-map-setup`. El usuario se conecta desde el celular, entra a la web, escanea redes, elige la suya, pone la clave y confirma. Si la clave estaba mal, la Pi vuelve sola al AP. Ver [[Modulo-Red]].

## CU-09 Desarrollar sin hardware
Desarrollador en su laptop: `docker compose` levanta web + render headless con cámara simulada. Calibra, crea escenas y escribe shaders viendo el resultado en el preview del navegador, sin proyector ni Pi ni cámara. Ver [[Docker-Local]].

## Requisitos no funcionales

| ID | Requisito |
|----|-----------|
| RNF-1 | 1080p @ 60 fps (efectos simples) / @ 30 fps (partículas) en Pi 4 |
| RNF-2 | Latencia slider → pixel proyectado < 100 ms |
| RNF-3 | Arranque a proyección < 20 s desde power-on |
| RNF-4 | Config completa persistida en un solo archivo `.db` respaldable |
| RNF-5 | Todo el sistema desarrollable y ejecutable sin hardware adicional (CU-09) |
| RNF-6 | Ningún cambio de configuración de red puede dejar la Pi inalcanzable (CU-08) |

Relacionado: [[Presupuesto-de-Rendimiento]] · [[Eco-Map]]
