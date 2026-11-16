"""Configuration lue dans les variables d'environnement (aucun secret dans le code)."""
import os

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_DUREE_S = int(os.environ.get("JWT_DUREE_S", "3600"))