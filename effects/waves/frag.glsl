// Ondas concentricas desde un origen.
//
// El origen sigue al movimiento que detecta la camara. Sin camara, `u_motion`
// vale 0 y el origen se queda en el centro: el efecto se degrada solo en vez
// de quedarse pegado en una esquina. Cuando llegue el Hito 4 empieza a
// reaccionar sin tocar el shader.

vec3 effect(vec2 uv) {
    vec2 origen = mix(vec2(0.5), u_motion_pos, clamp(u_motion, 0.0, 1.0));

    vec2 d = uv - origen;
    // Correccion de aspecto: sin esto los circulos salen elipses en cuanto la
    // superficie no es cuadrada.
    d.x *= u_resolution.x / max(u_resolution.y, 1.0);
    float r = length(d);

    float onda = sin(r * p_scale - u_time * p_speed);
    // smoothstep y no step: el borde duro aliasea feo cuando la superficie
    // esta deformada y un pixel de pantalla cubre varios de la textura.
    float anillo = smoothstep(1.0 - p_width, 1.0, onda);

    float caida = exp(-r * p_falloff);
    return p_color * anillo * caida;
}
