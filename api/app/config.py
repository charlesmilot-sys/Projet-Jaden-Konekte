"""Configuration lue dans les variables d'environnement (aucun secret dans le code)."""
import os

DATABASE_URL = os.environ["DATABASE_URL"]