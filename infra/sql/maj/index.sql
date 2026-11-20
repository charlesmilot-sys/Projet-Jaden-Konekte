-- Index ajoutés au schéma (à exécuter une fois sur une base créée avant leur ajout)
CREATE INDEX IF NOT EXISTS parcelle_exploitation_idx ON parcelle (exploitation);
CREATE INDEX IF NOT EXISTS capteur_parcelle_idx ON capteur (parcelle);
CREATE INDEX IF NOT EXISTS equipement_parcelle_idx ON equipement (parcelle);
CREATE INDEX IF NOT EXISTS commande_equipement_idx ON commande (equipement, cree_le DESC);
CREATE INDEX IF NOT EXISTS diagnostic_auteur_idx ON diagnostic (auteur, cree_le DESC);
CREATE INDEX IF NOT EXISTS historique_exploitation_idx ON historique (exploitation, ts DESC);
