---
tags: [arquitectura, datos, sqlite]
---

# Modelo de datos (SQLite)

Un archivo: `data/ecomap.db`. Modo **WAL**, `foreign_keys=ON`, `synchronous=NORMAL`. Ver [[ADR-004-SQLite]].

```sql
CREATE TABLE surface (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('quad','mesh')) DEFAULT 'quad',
  mesh_cols     INTEGER NOT NULL DEFAULT 1,
  mesh_rows     INTEGER NOT NULL DEFAULT 1,
  points        TEXT NOT NULL,          -- JSON [[x,y],...] normalizado 0..1, orden fila-mayor
  mask          TEXT,                   -- JSON polígono o NULL
  opacity       REAL NOT NULL DEFAULT 1.0,
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- catálogo: espejo en DB del manifiesto en disco, refrescado al arrancar
CREATE TABLE effect (
  id            TEXT PRIMARY KEY,       -- 'plasma'
  name          TEXT NOT NULL,
  version       TEXT NOT NULL,
  manifest      TEXT NOT NULL,          -- JSON completo
  needs_camera  INTEGER NOT NULL DEFAULT 0,
  cost          TEXT NOT NULL DEFAULT 'low',
  available     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE scene (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  is_default    INTEGER NOT NULL DEFAULT 0,   -- escena de arranque
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE layer (
  id            INTEGER PRIMARY KEY,
  scene_id      INTEGER NOT NULL REFERENCES scene(id)   ON DELETE CASCADE,
  surface_id    INTEGER NOT NULL REFERENCES surface(id) ON DELETE CASCADE,
  effect_id     TEXT    NOT NULL REFERENCES effect(id),
  z_order       INTEGER NOT NULL DEFAULT 0,
  blend_mode    TEXT NOT NULL DEFAULT 'normal',  -- normal|add|multiply|screen
  params        TEXT NOT NULL DEFAULT '{}',      -- JSON: overrides del default del manifiesto
  enabled       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_layer_scene ON layer(scene_id, z_order);

CREATE TABLE calibration (
  id            INTEGER PRIMARY KEY,
  method        TEXT NOT NULL,          -- 'manual' | 'graycode' | 'aruco'
  homography    TEXT,                   -- JSON 3x3 cam->proj
  rms_error     REAL,
  camera_w      INTEGER, camera_h INTEGER,
  proj_w        INTEGER, proj_h INTEGER,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE setting (          -- clave/valor: resolución, fps objetivo, brillo, bpm...
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE event_log (        -- diagnóstico; se poda a 5000 filas
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (datetime('now')),
  level TEXT NOT NULL, source TEXT NOT NULL, message TEXT NOT NULL
);
```

## Decisiones de modelado

- **`points` como JSON, no tabla de puntos.** Una malla 9×9 son 81 filas que siempre se leen y escriben juntas. JSON en una columna es más simple y más rápido; SQLite tiene `json_extract` si algún día hace falta consultar.
- **`params` como JSON con solo los overrides.** El default vive en el manifiesto del efecto. Si el efecto sube de versión y agrega un parámetro, las capas existentes lo heredan sin migración.
- **Catálogo de efectos espejado en DB**, pero **la fuente de verdad son los archivos**: `effect.json` y `frag.glsl` en el volumen de efectos. La DB guarda metadatos y la ruta, nunca el shader. Permite joins e integridad con `layer`, y marcar `available=0` si el shader se rompió, sin perder la referencia. Regla completa en [[ADR-011-Archivos-vs-DB]].
- **Nada de BLOBs.** Videos, imágenes, previews y capturas de calibración viven en el volumen `ecomap-media`; la DB guarda la ruta relativa. Umbral práctico: más de ~64 KB, o editable con un editor de texto → archivo.
- **Sin tabla de usuarios, sin login.** Decisión firme de v1. Ver [[Seguridad-y-Red]].
- **Las credenciales de wifi no se guardan aquí**: las administra NetworkManager en el host. Ver [[Modulo-Red]].

## Migraciones

Tabla `schema_version` + scripts `migrations/00N_*.sql` aplicados en orden al arrancar. Sin Alembic: para SQLite de un solo archivo es sobrepeso en esta etapa.

Relacionado: [[Contratos-API]] · [[ADR-004-SQLite]]
