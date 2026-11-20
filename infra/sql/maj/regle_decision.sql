-- Dernière décision de la règle d'arrosage (base créée avant cet ajout)
ALTER TABLE regle ADD COLUMN IF NOT EXISTS derniere_evaluation TIMESTAMPTZ;
ALTER TABLE regle ADD COLUMN IF NOT EXISTS derniere_decision TEXT;
