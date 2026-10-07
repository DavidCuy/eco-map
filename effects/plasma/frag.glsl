// Plasma: suma de senos, el efecto mas viejo del libro.
//
// Cuatro senos alcanzan para que el patron no se lea como periodico. Son
// baratos incluso en el V3D de la Pi: nada de bucles, nada de pow, nada de
// texturas.

vec3 effect(vec2 uv) {
    // Centrado y con correccion de aspecto: sin esto el patron se estira en
    // superficies que no son cuadradas, y las superficies casi nunca lo son.
    vec2 p = (uv - 0.5) * p_scale;
    p.x *= u_resolution.x / max(u_resolution.y, 1.0);

    float t = u_time * p_speed;
    float v = sin(p.x + t)
            + sin(p.y + t * 0.9)
            + sin((p.x + p.y) * 0.7 + t * 1.3)
            + sin(length(p) * 1.5 - t * 1.1);

    float m = 0.5 + 0.125 * v;  // los cuatro senos dan -4..4
    return mix(p_color_a, p_color_b, m) * p_brightness;
}
