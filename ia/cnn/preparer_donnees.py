"""
Prépare le sous-ensemble « tomate » de PlantVillage en dossiers train/ et val/.

1. Téléchargez PlantVillage (version « color »), par exemple depuis Kaggle
   (jeu « PlantVillage Dataset ») ou via TensorFlow Datasets (plant_village).
2. Lancez :
       python preparer_donnees.py --source chemin/vers/plantvillage/color --sortie donnees
   Seuls les dossiers dont le nom commence par « Tomato » sont conservés.
"""
import argparse
import random
import shutil
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--sortie", default="donnees")
    ap.add_argument("--val", type=float, default=0.2, help="part des images en validation")
    ap.add_argument("--prefixe", default="Tomato")
    a = ap.parse_args()
    random.seed(0)

    dossiers = sorted(d for d in Path(a.source).iterdir() if d.is_dir() and d.name.startswith(a.prefixe))
    if not dossiers:
        raise SystemExit(f"Aucun dossier « {a.prefixe}* » dans {a.source}")
    for d in dossiers:
        images = sorted(p for p in d.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        random.shuffle(images)
        n_val = int(len(images) * a.val)
        for i, img in enumerate(images):
            dest = Path(a.sortie) / ("val" if i < n_val else "train") / d.name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img, dest / img.name)
        print(f"{d.name:<55} {len(images) - n_val:>5} train  {n_val:>5} val")


if __name__ == "__main__":
    main()
