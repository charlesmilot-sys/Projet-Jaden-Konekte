-- Règles d'arrosage de démonstration : délai court (2 min) pour voir l'effet avec le simulateur accéléré
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
WHERE e.code = 'expl-1'
ON CONFLICT (parcelle) DO NOTHING;
