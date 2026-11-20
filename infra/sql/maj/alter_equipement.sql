ALTER TABLE equipement
  ADD COLUMN en_ligne     BOOLEAN NOT NULL DEFAULT false,   -- dernier statut publié par l'objet
  ADD COLUMN jusqua       TIMESTAMPTZ,                      -- fermeture prévue (vanne ouverte)
  ADD COLUMN derniere_cmd VARCHAR(40);                      -- dernière commande confirmée par l'objet