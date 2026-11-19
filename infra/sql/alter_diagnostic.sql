-- Ajout du libellé français dans les diagnostics (base déjà créée)
ALTER TABLE diagnostic ADD COLUMN IF NOT EXISTS libelle VARCHAR(120);
