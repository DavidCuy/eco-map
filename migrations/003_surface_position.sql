-- Orden de las caras en la tira de abajo del canvas.
--
-- No afecta al render: el apilado lo decide el z_order de las capas. Esto es
-- navegacion. Con el canvas mostrando una cara por vez, la tira es la forma de
-- saltar entre ellas, y poder ordenarlas como estan fisicamente —de izquierda
-- a derecha segun se ve el objeto— es la diferencia entre buscar y señalar.
--
-- Arranca copiando el id para conservar el orden que ya tenian, que era por
-- id: una base existente no cambia de aspecto al migrar.

ALTER TABLE surface ADD COLUMN position INTEGER NOT NULL DEFAULT 0;

UPDATE surface SET position = id;
