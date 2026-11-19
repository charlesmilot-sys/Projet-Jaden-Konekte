"""Évalue le modèle ONNX exporté sur le jeu de validation (le modèle réellement déployé).

    python evaluer_onnx.py --modele tomate_mobilenetv3.onnx --classes classes.json --donnees donnees/val

Produit evaluation.json : exactitude globale, précision et rappel par classe, matrice de confusion.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from pretraitement import preparer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modele", default="tomate_mobilenetv3.onnx")
    ap.add_argument("--classes", default="classes.json")
    ap.add_argument("--donnees", default="donnees/val")
    ap.add_argument("--lot", type=int, default=64)
    ap.add_argument("--sortie", default="evaluation.json")
    a = ap.parse_args()

    classes = json.loads(Path(a.classes).read_text(encoding="utf-8"))
    session = ort.InferenceSession(a.modele, providers=["CPUExecutionProvider"])
    entree = session.get_inputs()[0].name

    fichiers = [(p, i) for i, c in enumerate(classes)
                for p in sorted((Path(a.donnees) / c).iterdir()) if p.is_file()]
    print(f"{len(fichiers)} images de validation, {len(classes)} classes")

    n = len(classes)
    confusion = np.zeros((n, n), dtype=int)       # lignes : vraie classe, colonnes : prédite
    for debut in range(0, len(fichiers), a.lot):
        lot = fichiers[debut:debut + a.lot]
        x = np.stack([preparer(Image.open(p)) for p, _ in lot])
        predites = session.run(None, {entree: x})[0].argmax(axis=1)
        for (_, vraie), pred in zip(lot, predites):
            confusion[vraie, pred] += 1

    exactitude = np.trace(confusion) / confusion.sum()
    par_classe = {}
    print(f"\n{'classe':<48} {'précision':>9} {'rappel':>7} {'images':>7}")
    for i, c in enumerate(classes):
        vp = confusion[i, i]
        precision = vp / max(confusion[:, i].sum(), 1)
        rappel = vp / max(confusion[i, :].sum(), 1)
        par_classe[c] = {"precision": round(float(precision), 4), "rappel": round(float(rappel), 4),
                         "images": int(confusion[i, :].sum())}
        print(f"{c:<48} {precision:>9.3f} {rappel:>7.3f} {confusion[i, :].sum():>7}")
    print(f"\nExactitude globale : {exactitude:.4f}")

    Path(a.sortie).write_text(json.dumps({
        "modele": Path(a.modele).name, "exactitude": round(float(exactitude), 4),
        "par_classe": par_classe, "classes": classes, "confusion": confusion.tolist(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Résultats enregistrés dans {a.sortie}")


if __name__ == "__main__":
    main()
