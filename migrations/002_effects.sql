-- US-10: los patrones de prueba del esqueleto pasan a ser efectos del catalogo,
-- leidos de archivos (ADR-011). El render ya no tiene shaders hardcodeados.

DELETE FROM setting WHERE key = 'test_pattern';

INSERT INTO setting (key, value) VALUES ('active_effect', 'grid_test')
    ON CONFLICT(key) DO NOTHING;
