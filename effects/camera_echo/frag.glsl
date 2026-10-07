// Eco de camara: el frame actual mezclado con su propio pasado, desplazado y
// escalado. Es el efecto que le da nombre al proyecto.
//
// El pasado sale de `u_prev`, que es el frame anterior de esta misma capa
// (el manifiesto declara `needs_feedback`). Sin eso un shader no puede tener
// memoria: cada frame arranca de cero.
//
// # El riesgo real: realimentacion optica
//
// La camara ve la proyeccion. Si el eco se suma sin limite, lo proyectado
// alimenta lo que la camara capta y en pocos segundos la imagen se satura
// sola, sin que nadie se mueva. Tres frenos, y ninguno alcanza solo:
//
// 1. `decay` < 1 siempre: el pasado se apaga en vez de acumularse.
// 2. `gain` limita cuanto aporta la camara en cada frame.
// 3. El resultado se satura con min(): por mas vueltas del lazo, no pasa de 1.
//
// El cuarto freno no esta aca sino en la deteccion de movimiento: banda muerta
// y suavizado temporal, para que el titileo de la proyeccion no cuente como
// movimiento (ver ecomap_vision/motion.py).

vec3 effect(vec2 uv) {
    // El eco se lee de un punto levemente corrido y escalado: eso es lo que
    // produce la estela en vez de un simple desvanecido.
    vec2 centro = uv - 0.5;
    vec2 uv_eco = centro / p_zoom + 0.5;
    uv_eco += vec2(p_drift, p_drift * 0.6);

    vec3 pasado = texture(u_prev, uv_eco).rgb * p_decay;

    vec3 camara = texture(u_cam, uv).rgb;
    // Luminancia y no el color crudo: lo que interesa es donde hay algo, no de
    // que color es. Ademas evita que una pared roja tina todo el eco.
    float luz = dot(camara, vec3(0.299, 0.587, 0.114));
    vec3 aporte = p_tint * luz * p_gain;

    return min(pasado + aporte, vec3(1.0));
}
