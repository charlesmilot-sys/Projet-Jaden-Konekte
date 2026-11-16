-- Données de test temporaires (le mot de passe sera remplacé par un vrai hachage avec l'authentification)
INSERT INTO utilisateur (prenom, nom, courriel, mot_de_passe)
VALUES ('Test', 'Exploitant', 'test@exemple.fr', 'a-remplacer');

INSERT INTO exploitation (proprietaire, code, nom, commune, lat, lon)
VALUES (1, 'expl-1', 'Jardin de test', 'Sainte-Rose', 16.33, -61.70);

INSERT INTO parcelle (exploitation, code, nom, culture, surface_m2) VALUES
  (1, 'p1', 'Carré de tomates', 'tomate', 25),
  (1, 'p2', 'Rang d''ignames', 'igname', 40),
  (1, 'p3', 'Treille de christophines', 'christophine', NULL);