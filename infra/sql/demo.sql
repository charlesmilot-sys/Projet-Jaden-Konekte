-- Données de démonstration, chargées automatiquement par PostgreSQL à la création de la base
-- (après schema.sql). Le mot de passe du compte de démonstration n'est PAS ici : l'API le fixe au
-- démarrage à partir de DEMO_MOT_DE_PASSE (infra/.env). Aucun secret dans le dépôt.

INSERT INTO utilisateur (prenom, nom, courriel, mot_de_passe)
VALUES ('Test', 'Exploitant', 'test@exemple.fr', 'a-definir-au-demarrage');

INSERT INTO exploitation (proprietaire, code, nom, commune, lat, lon)
SELECT id, 'expl-1', 'Jardin de test', 'Sainte-Rose', 16.33, -61.70
FROM utilisateur WHERE courriel = 'test@exemple.fr';

INSERT INTO parcelle (exploitation, code, nom, culture, surface_m2)
SELECT e.id, p.code, p.nom, p.culture, p.surface
FROM exploitation e
CROSS JOIN (VALUES
    ('p1', 'Carré de tomates', 'tomate', 25),
    ('p2', 'Rang d''ignames', 'igname', 40),
    ('p3', 'Treille de christophines', 'christophine', NULL)
) AS p(code, nom, culture, surface)
WHERE e.code = 'expl-1';

-- Capteurs : bornes plausibles et vitesse de variation maximale (unités par minute) pour la validation
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

-- Une vanne par parcelle
INSERT INTO equipement (parcelle, type, etat)
SELECT p.id, 'vanne', 'fermee'
FROM parcelle p JOIN exploitation e ON e.id = p.exploitation
WHERE e.code = 'expl-1';

-- Règles d'arrosage : seuil élevé sur p1 (40 %) pour voir un déclenchement pendant la démonstration ;
-- délai court (2 min) adapté au simulateur accéléré (1 s réelle = 1 min simulée)
INSERT INTO regle (parcelle, nom, condition, action, active, delai_min_s)
SELECT p.id, 'Arrosage ' || p.nom,
       jsonb_build_object('et', jsonb_build_array(
           jsonb_build_object('capteur', 'sol/humidite', 'op', '<', 'valeur', s.seuil),
           jsonb_build_object('meteo', 'pluie_6h', 'op', '<', 'valeur', 2))),
       '{"equipement": "vanne", "action": "ouvrir", "duree_s": 600}',
       true, 120
FROM parcelle p
JOIN exploitation e ON e.id = p.exploitation
JOIN (VALUES ('p1', 40), ('p2', 25), ('p3', 25)) AS s(code, seuil) ON s.code = p.code
WHERE e.code = 'expl-1';
