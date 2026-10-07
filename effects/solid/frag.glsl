// Color plano. Sirve para alinear el proyector, para medir el derrame de luz
// sobre el objeto y como fondo de una superficie.
//
// Deliberadamente no depende de u_time: si parpadea, el problema esta en otro
// lado.

vec3 effect(vec2 uv) {
    return p_color * p_brightness;
}
