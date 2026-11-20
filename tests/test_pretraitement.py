"""Prétraitement des images du CNN : même format que pendant l'entraînement."""
import io

import numpy as np
from PIL import Image

from conftest import charger

p = charger("ia/cnn/pretraitement.py", "pretraitement")


def octets(largeur, hauteur, couleur=(40, 160, 40), format="JPEG"):
    b = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), couleur).save(b, format)
    return b.getvalue()


def test_format_de_sortie():
    x = p.preparer_octets(octets(640, 480))
    assert x.shape == (3, 224, 224)
    assert x.dtype == np.float32


def test_toutes_tailles_et_png():
    for l, h in [(100, 300), (2000, 1000), (224, 224)]:
        assert p.preparer_octets(octets(l, h, format="PNG")).shape == (3, 224, 224)


def test_image_en_niveaux_de_gris_convertie():
    b = io.BytesIO()
    Image.new("L", (300, 300), 128).save(b, "PNG")
    assert p.preparer_octets(b.getvalue()).shape == (3, 224, 224)


def test_normalisation_imagenet():
    """Un pixel égal à la moyenne ImageNet doit donner 0 après normalisation."""
    moyenne = tuple(round(m * 255) for m in (0.485, 0.456, 0.406))
    x = p.preparer_octets(octets(300, 300, moyenne, "PNG"))
    assert np.abs(x).max() < 0.02


def test_softmax():
    probas = p.softmax(np.array([[2.0, 1.0, 0.1]]))
    assert np.isclose(probas.sum(), 1.0)
    assert probas.argmax() == 0
