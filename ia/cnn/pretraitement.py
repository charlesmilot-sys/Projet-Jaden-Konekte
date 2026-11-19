"""Pré-traitement d'une image, identique à la validation de l'entraînement (torchvision) :
redimensionnement du petit côté à 256, recadrage central 224, normalisation ImageNet.
Utilisé par l'évaluation ET par le service d'inférence : le modèle voit en production
exactement ce qu'il a vu pendant sa validation."""
import io

import numpy as np
from PIL import Image

TAILLE = 224
MOY = np.array([0.485, 0.456, 0.406], dtype=np.float32)
ECART = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preparer(image: Image.Image) -> np.ndarray:
    """PIL -> tableau (3, 224, 224) float32 normalisé."""
    image = image.convert("RGB")
    l, h = image.size
    echelle = 256 / min(l, h)
    image = image.resize((round(l * echelle), round(h * echelle)), Image.BILINEAR)
    l, h = image.size
    gauche, haut = (l - TAILLE) // 2, (h - TAILLE) // 2
    image = image.crop((gauche, haut, gauche + TAILLE, haut + TAILLE))
    x = np.asarray(image, dtype=np.float32) / 255.0
    x = (x - MOY) / ECART
    return x.transpose(2, 0, 1)  # HWC -> CHW


def preparer_octets(contenu: bytes) -> np.ndarray:
    return preparer(Image.open(io.BytesIO(contenu)))


def softmax(logits: np.ndarray) -> np.ndarray:
    e = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)
