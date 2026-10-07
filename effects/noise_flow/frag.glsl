// Ruido de valor con domain warping: el fbm se evalua sobre coordenadas que a
// su vez vienen de otro fbm, que es lo que da el aspecto organico en vez de
// manchas estaticas.
//
// Dos cuidados pensando en el V3D de la Pi:
//
// 1. El hash usa `highp` explicito. El header global declara `precision
//    mediump float`, y con mediump el `fract(sin(...) * 43758.0)` pierde bits
//    y el ruido se degrada en bandas visibles. Es el tipico shader que se ve
//    bien en el escritorio y feo en la Pi.
// 2. El bucle del fbm tiene cota **constante**. Un bucle de cota dinamica no
//    se puede desenrollar y el compilador del V3D lo sufre.

float hash(vec2 p) {
    highp vec2 q = p;
    highp float h = dot(q, vec2(127.1, 311.7));
    return fract(sin(h) * 43758.5453123);
}

float noise(vec2 p) {
    vec2 celda = floor(p);
    vec2 f = fract(p);
    // Suavizado de Hermite: evita que se vean las aristas de la grilla.
    vec2 u = f * f * (3.0 - 2.0 * f);

    float a = hash(celda);
    float b = hash(celda + vec2(1.0, 0.0));
    float c = hash(celda + vec2(0.0, 1.0));
    float d = hash(celda + vec2(1.0, 1.0));

    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// Tres octavas y no cuatro. El domain warping evalua fbm cinco veces por
// pixel, asi que cada octava cuesta cinco veces: con cuatro, medido bajo
// llvmpipe a 640x360, el frame se iba a 27.8 ms contra un presupuesto de 33.
// La cuarta octava agrega detalle que a distancia de proyeccion no se ve.
float fbm(vec2 p) {
    float suma = 0.0;
    float amplitud = 0.5;
    for (int i = 0; i < 3; i++) {  // cota constante, se desenrolla
        suma += amplitud * noise(p);
        p *= 2.0;
        amplitud *= 0.5;
    }
    return suma / 0.875;  // normaliza a 0..1 con tres octavas
}

vec3 effect(vec2 uv) {
    vec2 p = uv * p_scale;
    p.x *= u_resolution.x / max(u_resolution.y, 1.0);

    float t = u_time * p_speed;
    vec2 q = vec2(fbm(p + t), fbm(p + vec2(5.2, 1.3) - t));
    vec2 r = vec2(fbm(p + p_warp * q + vec2(1.7, 9.2)), fbm(p + p_warp * q + vec2(8.3, 2.8)));

    float v = fbm(p + p_warp * r);
    return mix(p_color_a, p_color_b, clamp(v * 1.6, 0.0, 1.0));
}
