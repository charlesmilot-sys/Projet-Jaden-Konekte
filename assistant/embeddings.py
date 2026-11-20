"""Embeddings multilingues (dimension 384) calculés localement avec fastembed (ONNX Runtime, sans PyTorch).
Le MÊME modèle sert à indexer les fiches et à encoder les questions : sinon les vecteurs ne sont pas comparables."""
import os

from fastembed import TextEmbedding

MODELE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DOSSIER_CACHE = os.environ.get("DOSSIER_EMBEDDINGS", "/modele-embeddings")

_modele: TextEmbedding | None = None


def charger() -> None:
    global _modele
    _modele = TextEmbedding(MODELE, cache_dir=DOSSIER_CACHE)


def encoder(textes: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _modele.embed(textes)]


def vers_pg(vecteur: list[float]) -> str:
    """Format texte compris par pgvector : '[0.12,-0.03,...]' (converti avec ::vector dans la requête)."""
    return "[" + ",".join(f"{x:.6f}" for x in vecteur) + "]"
