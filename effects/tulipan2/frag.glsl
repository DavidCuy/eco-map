vec3 effect(vec2 uv) {
    float a = radians(p_angle);
    vec2 direccion = vec2(cos(a), sin(a));
    return texture(u_media, fract(uv + direccion * p_speed * u_time)).rgb;
}
