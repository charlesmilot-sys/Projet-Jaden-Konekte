"""Outils communs aux tests.

Les services ont chacun leur dossier (ingestion/, regles/, assistant/…) et certains fichiers portent le même
nom (service.py) : on charge donc chaque module par son chemin, sous un nom unique."""
import importlib.util
import sys
from pathlib import Path

DEPOT = Path(__file__).resolve().parent.parent


def charger(chemin_relatif: str, nom: str):
    chemin = DEPOT / chemin_relatif
    sys.path.insert(0, str(chemin.parent))          # pour ses imports voisins (ex. import embeddings)
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module
