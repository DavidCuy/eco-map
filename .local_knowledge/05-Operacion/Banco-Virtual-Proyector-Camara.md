---
tags: [operacion, verificacion, calibracion]
---

# Banco virtual proyector-cámara

Cierra en software el lazo que en la realidad pasa por una pared: toma el frame que el render
presentó, lo deforma con una homografía **conocida**, lo degrada, y lo devuelve como si fuera una
cámara mirando la proyección.

Es una fuente de cámara más: `loopback://`, con parámetros en la URI
(`loopback://?width=640&height=480&noise=2&blur=3&gain=0.85&ambient=10`). Vive en
`src/ecomap_vision/loopback.py`.

## Por qué existe

Con hardware, de una calibración solo se puede decir *"se ve bien"*. Acá **se sabe la respuesta**:
se elige la homografía, se corre la secuencia completa de Gray code, y se compara la `H` estimada
contra la que usó el banco. Un error de reproyección bajo no alcanza como criterio — ver el bug del
pliegue, abajo.

## Cómo se usa

```powershell
podman cp scripts/verify_loopback.py eco-map_render_1://app/verify_loopback.py
podman exec eco-map_render_1 sh -c "cd /app && python verify_loopback.py"
```

El script corre el render **de verdad** (loop, bus, hilo de visión, GL con llvmpipe), manda
`op=camera` con `loopback://` y después `op=calibrate`, espera el evento `calib` final y compara.

Medición del 2026-10-07, proyector 640×360 y cámara virtual 640×480:

```
ok=True msg=3924 correspondencias, error 1.35 px
  cobertura=0.462
  composicion (debería ser identidad)
  [[ 0.996 -0.005  0.804]
   [-0.001  0.994  0.376]
   [-0.    -0.     1.   ]]
  esquinas: diferencia máxima contra la verdad 2.0 px
```

## El frame proyectado lo copia el hilo de render

`set_frame_provider()` registra en el render un proveedor del último frame presentado. La copia a
CPU la hace **el hilo de render**, no el de visión: el contexto GL está ligado al hilo que lo creó, y
leerlo desde otro falla con `cannot create texture` o devuelve basura. Solo se copia cuando hay una
cámara `loopback://` abierta — bajar el framebuffer por cuadro es caro y con una cámara real no
sirve de nada.

## Lo que encontró que los tests no veían

Tres bugs que solo se manifestaban proyectando de verdad:

1. **`u_opacity` sin asignar.** El shader de warp multiplica por ese uniform; sin asignarlo arranca
   en 0 y el proyector mostraba negro. La secuencia corría completa y fallaba al final diciendo que
   la cámara no veía el área.
2. **Medio quad.** El quad a pantalla completa son dos triángulos (seis vértices) y se renderizaba
   con `vertices=3`: media pantalla sin patrón.
3. **El pliegue del Gray code.** El peor de los tres, porque *parecía* funcionar: `rms = 0.69 px` con
   la homografía invertida. Detalle en [[Modulo-Calibracion]].

Los tres tienen ahora prueba sin GL (`tests/test_calibration.py` con dobles del contexto,
`tests/test_graycode.py` para el pliegue): el banco sirve para **encontrar**, los tests para que no
vuelvan.

## Lo que no puede simular

Y por eso no reemplaza al hardware ([[Limitaciones-por-Hardware]]):

- La exposición automática de una webcam que ignora los controles y cambia el brillo entre capturas.
- El tiempo real de asentamiento entre proyectar y capturar (el `settle`).
- El ruido de un sensor barato en penumbra.
- El refresco del proyector y su latencia de entrada.

Relacionado: [[Modulo-Calibracion]] · [[Modulo-Camara-Feedback]] · [[Modulo-Render]]
