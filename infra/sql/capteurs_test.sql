-- Capteurs et vannes des parcelles de test (une ligne par grandeur et par parcelle)
INSERT INTO capteur (parcelle, type, grandeur, unite, min_valide, max_valide, baisse_max_min, hausse_max_min)
SELECT p.id, c.type, c.grandeur, c.unite, c.min_valide, c.max_valide, c.baisse_max_min, c.hausse_max_min
FROM parcelle p
JOIN exploitation e ON e.id = p.exploitation
CROSS JOIN (VALUES
    ('sol',    'humidite',    '%',    5,   70,     0.5,  2.0),
    ('air',    'temperature', '°C',   5,   45,     1.0,  1.0),
    ('air',    'luminosite',  'lx',   0,   150000, NULL, NULL),
    ('pluvio', 'intensite',   'mm/h', 0,   200,    NULL, NULL)
) AS c(type, grandeur, unite, min_valide, max_valide, baisse_max_min, hausse_max_min)
WHERE e.code = 'expl-1';

INSERT INTO equipement (parcelle, type, etat)
SELECT p.id, 'vanne', 'fermee'
FROM parcelle p
JOIN exploitation e ON e.id = p.exploitation
WHERE e.code = 'expl-1';