// Patron de calibracion.
//
// Tres cosas, y cada una tiene su motivo:
//   - Ajedrez: deja ver la deformacion de la malla celda por celda.
//   - Marco: marca el limite exacto de la superficie contra el derrame de luz.
//   - Esquinas de colores: permiten saber cual es cual desde el otro lado de la
//     sala, cuando la superficie esta rotada o espejada y el ajedrez solo no
//     alcanza para orientarse.
//
// Convencion de las esquinas, en coordenadas de superficie:
//   TL roja · TR verde · BR azul · BL amarilla

vec3 effect(vec2 uv) {
    vec2 cell = floor(uv * p_cells);
    float checker = mod(cell.x + cell.y, 2.0);
    vec3 color = vec3(checker * p_contrast + 0.08);

    // Marco de grosor constante en pixeles, no en UV: una superficie chica no
    // deberia tener un borde proporcionalmente mas grueso.
    vec2 px = 1.0 / u_resolution;
    float border = 4.0;
    if (uv.x < px.x * border || uv.x > 1.0 - px.x * border ||
        uv.y < px.y * border || uv.y > 1.0 - px.y * border) {
        color = vec3(0.0, 0.95, 0.85);
    }

    if (p_corners) {
        float m = 0.06;
        if (uv.x < m && uv.y > 1.0 - m) color = vec3(1.0, 0.15, 0.15);
        if (uv.x > 1.0 - m && uv.y > 1.0 - m) color = vec3(0.15, 1.0, 0.15);
        if (uv.x > 1.0 - m && uv.y < m) color = vec3(0.25, 0.4, 1.0);
        if (uv.x < m && uv.y < m) color = vec3(1.0, 0.9, 0.1);
    }
    return color;
}
