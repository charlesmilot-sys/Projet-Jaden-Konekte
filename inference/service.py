"""Service d'inférence du CNN (diagnostic des maladies de la tomate).

Service séparé de l'API : il ne parle qu'au réseau interne de Docker (aucun port publié),
ne connaît ni la base ni les utilisateurs, et ne fait qu'une chose : image -> maladie.
Le modèle ONNX est chargé UNE SEULE FOIS au démarrage, puis réutilisé pour chaque requête.
"""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError

from pretraitement import preparer_octets, softmax

DOSSIER = Path(os.environ.get("DOSSIER_MODELE", "/modele"))
VERSION = os.environ.get("MODELE_VERSION", "mobilenetv3-tomate-v1")
TAILLE_MAX = 5 * 1024 * 1024          # même limite que l'API (5 Mo)
Image.MAX_IMAGE_PIXELS = 40_000_000   # refuse les « bombes de décompression »

etat: dict = {}


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    etat["session"] = ort.InferenceSession(
        str(DOSSIER / "tomate_mobilenetv3.onnx"), options, providers=["CPUExecutionProvider"]
    )
    etat["classes"] = json.loads((DOSSIER / "classes.json").read_text(encoding="utf-8"))
    etat["libelles"] = json.loads((DOSSIER / "classes_fr.json").read_text(encoding="utf-8"))
    yield
    etat.clear()


app = FastAPI(title="Jaden Konekté — inférence CNN", version="1.0.0", lifespan=cycle_de_vie)


def _predire(contenu: bytes) -> dict:
    x = preparer_octets(contenu)[np.newaxis]                       # (1, 3, 224, 224)
    logits = etat["session"].run(["logits"], {"image": x})[0][0]   # (10,)
    probas = softmax(logits)
    ordre = np.argsort(probas)[::-1][:3]                           # 3 classes les plus probables
    top = [
        {"classe": etat["classes"][i],
         "libelle": etat["libelles"].get(etat["classes"][i], etat["classes"][i]),
         "score": round(float(probas[i]), 4)}
        for i in ordre
    ]
    return {**top[0], "modele": VERSION, "top": top}


@app.get("/sante")
def sante():
    return {"statut": "ok", "modele": VERSION, "classes": len(etat.get("classes", []))}


@app.post("/predire")
async def predire(requete: Request):
    """Corps de la requête : les octets bruts de l'image (JPEG ou PNG)."""
    contenu = await requete.body()
    if len(contenu) > TAILLE_MAX:
        raise HTTPException(413, "Image trop volumineuse.")
    try:
        # Le calcul est bloquant : on le fait dans un fil à part pour ne pas figer le serveur
        return await run_in_threadpool(_predire, contenu)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(422, "Image illisible ou corrompue.")
