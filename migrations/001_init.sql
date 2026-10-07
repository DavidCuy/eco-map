-- Esquema inicial de Eco-Map. Ver .local_knowledge/02-Arquitectura/Modelo-de-Datos.md
-- Reglas: puntos y parametros como JSON, contenido voluminoso en archivos (ADR-011),
-- sin tabla de usuarios (Seguridad-y-Red).

CREATE TABLE surface (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    kind        TEXT    NOT NULL DEFAULT 'quad' CHECK (kind IN ('quad', 'mesh')),
    mesh_cols   INTEGER NOT NULL DEFAULT 1,
    mesh_rows   INTEGER NOT NULL DEFAULT 1,
    points      TEXT    NOT NULL,              -- JSON [[x,y],...] normalizado 0..1, TL TR BR BL
    mask        TEXT,                          -- JSON poligono o NULL
    opacity     REAL    NOT NULL DEFAULT 1.0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Espejo del manifiesto en disco; la fuente de verdad es effects/<id>/effect.json
CREATE TABLE effect (
    id            TEXT PRIMARY KEY,
    name          TEXT    NOT NULL,
    version       TEXT    NOT NULL,
    manifest      TEXT    NOT NULL,            -- JSON completo del manifiesto
    needs_camera  INTEGER NOT NULL DEFAULT 0,
    cost          TEXT    NOT NULL DEFAULT 'low',
    available     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE scene (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    is_default  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE layer (
    id          INTEGER PRIMARY KEY,
    scene_id    INTEGER NOT NULL REFERENCES scene(id)   ON DELETE CASCADE,
    surface_id  INTEGER NOT NULL REFERENCES surface(id) ON DELETE CASCADE,
    effect_id   TEXT    NOT NULL REFERENCES effect(id),
    z_order     INTEGER NOT NULL DEFAULT 0,
    blend_mode  TEXT    NOT NULL DEFAULT 'normal'
                CHECK (blend_mode IN ('normal', 'add', 'multiply', 'screen')),
    params      TEXT    NOT NULL DEFAULT '{}', -- JSON: solo los overrides
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX ix_layer_scene ON layer(scene_id, z_order);

CREATE TABLE calibration (
    id          INTEGER PRIMARY KEY,
    method      TEXT NOT NULL CHECK (method IN ('manual', 'graycode', 'aruco')),
    homography  TEXT,                          -- JSON 3x3, camara -> proyector
    rms_error   REAL,
    camera_w    INTEGER,
    camera_h    INTEGER,
    proj_w      INTEGER,
    proj_h      INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE event_log (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL DEFAULT (datetime('now')),
    level   TEXT NOT NULL,
    source  TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE INDEX ix_event_log_ts ON event_log(ts);

INSERT INTO setting (key, value) VALUES
    ('calibration_version', '1'),
    ('blackout', '0'),
    ('test_pattern', 'off');
