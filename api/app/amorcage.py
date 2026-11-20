"""Comptes créés au démarrage de l'API à partir des variables d'environnement (jamais dans le dépôt).

- Administrateur : il n'existe pas de route publique pour devenir administrateur (l'inscription crée
  toujours un exploitant). Le compte est créé, ou son mot de passe remis à jour, depuis ADMIN_COURRIEL
  et ADMIN_MOT_DE_PASSE.
- Compte de démonstration : créé sans mot de passe utilisable par infra/sql/demo.sql ; son mot de
  passe est fixé ici depuis DEMO_MOT_DE_PASSE, seulement s'il n'en a pas encore de vrai.
"""
import logging
import os

from app.db import pool
from app.securite import hacher

log = logging.getLogger("uvicorn.error")


async def amorcer() -> None:
    admin_courriel = os.environ.get("ADMIN_COURRIEL", "").strip().lower()
    admin_mdp = os.environ.get("ADMIN_MOT_DE_PASSE", "")
    demo_courriel = os.environ.get("DEMO_COURRIEL", "test@exemple.fr").strip().lower()
    demo_mdp = os.environ.get("DEMO_MOT_DE_PASSE", "")

    async with pool.connection() as conn:
        if admin_courriel and admin_mdp:
            await conn.execute(
                """
                INSERT INTO utilisateur (prenom, nom, courriel, mot_de_passe, role)
                VALUES ('Admin', 'Jaden Konekté', %s, %s, 'administrateur')
                ON CONFLICT (courriel) DO UPDATE
                SET mot_de_passe = EXCLUDED.mot_de_passe, role = 'administrateur'
                """,
                (admin_courriel, hacher(admin_mdp)),
            )
            log.info("Compte administrateur prêt : %s", admin_courriel)
        else:
            log.warning("ADMIN_COURRIEL / ADMIN_MOT_DE_PASSE absents : pas de compte administrateur")

        if demo_mdp:
            cur = await conn.execute(
                """
                UPDATE utilisateur SET mot_de_passe = %s
                WHERE courriel = %s AND mot_de_passe NOT LIKE '$argon2%%'
                """,
                (hacher(demo_mdp), demo_courriel),
            )
            if cur.rowcount:
                log.info("Mot de passe du compte de démonstration fixé : %s", demo_courriel)
