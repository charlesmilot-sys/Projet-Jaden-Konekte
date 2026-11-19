"""Diagnostic par photo : l'API reçoit l'image, la confie au service d'inférence, enregistre le résultat."""
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.acces import parcelle_autorisee
from app.config import DOSSIER_IMAGES, INFERENCE_URL, SEUIL_CONFIANCE
from app.db import pool
from app.erreurs import reponses
from app.schemas import Confirmation, Diagnostic, PageDiagnostics
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1/diagnostics", tags=["Diagnostics"])

TAILLE_MAX = 5 * 1024 * 1024
# On reconnaît le format aux premiers octets du fichier (« nombre magique »),
# pas au nom ni au Content-Type envoyés par le client, qui peuvent mentir.
SIGNATURES = {b"\xff\xd8\xff": "jpg", b"\x89PNG\r\n\x1a\n": "png"}

COLONNES = """id, parcelle, classe, libelle, score, modele, statut, image_url, confirme,
              cree_le, termine_le"""
# Un exploitant ne voit que ses diagnostics ; l'administrateur les voit tous.
FILTRE = "WHERE (%(admin)s OR auteur = %(uid)s)"


def _format(contenu: bytes) -> str | None:
    return next((ext for sig, ext in SIGNATURES.items() if contenu.startswith(sig)), None)


def _vers_diagnostic(ligne: dict) -> Diagnostic:
    fiable = None if ligne["score"] is None else ligne["score"] >= SEUIL_CONFIANCE
    return Diagnostic(**ligne, fiable=fiable)


def _params(utilisateur, **extra) -> dict:
    return {"admin": utilisateur.role == "administrateur", "uid": utilisateur.id, **extra}


@router.post(
    "",
    response_model=Diagnostic,
    status_code=status.HTTP_201_CREATED,
    summary="Envoi d'une photo de feuille",
    description="Photo JPEG ou PNG, 5 Mo au plus. Si le score est sous le seuil de confiance, "
                "`fiable` vaut `false` : il faut reprendre la photo.",
    responses=reponses(401, 404, 413, 415, 422, 503),
)
async def creer_diagnostic(
    utilisateur: UtilisateurCourant,
    image: Annotated[UploadFile, File(description="Photo JPEG ou PNG, 5 Mo max")],
    parcelle: Annotated[int | None, Form(description="Parcelle concernée")] = None,
):
    # 1. Vérifications : taille, puis vrai format du fichier
    contenu = await image.read(TAILLE_MAX + 1)
    if len(contenu) > TAILLE_MAX:
        raise HTTPException(413, "Image trop volumineuse : 5 Mo au maximum.")
    extension = _format(contenu)
    if extension is None:
        raise HTTPException(415, "Format non pris en charge : envoyez une photo JPEG ou PNG.")

    async with pool.connection() as conn:
        if parcelle is not None:
            await parcelle_autorisee(conn, parcelle, utilisateur)   # 404 si pas à lui

        # 2. Le diagnostic est enregistré « en_cours » avant l'analyse : il reste tracé même en cas d'échec.
        #    L'URL de l'image contient l'id : on le réserve d'abord avec nextval().
        cur = await conn.execute(
            """
            WITH n AS (SELECT nextval('diagnostic_id_seq') AS id)
            INSERT INTO diagnostic (id, parcelle, auteur, image_url)
            SELECT id, %s, %s, '/api/v1/diagnostics/' || id || '/image' FROM n
            RETURNING id
            """,
            (parcelle, utilisateur.id),
        )
        diag_id = (await cur.fetchone())["id"]
        await conn.commit()

        # 3. Sauvegarde de la photo (preuve, et confirmation par l'exploitant)
        dossier = Path(DOSSIER_IMAGES)
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"{diag_id}.{extension}").write_bytes(contenu)

        # 4. Appel du service d'inférence
        erreur = None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(f"{INFERENCE_URL}/predire", content=contenu)
            if r.status_code == 422:
                erreur = (422, "Image illisible ou corrompue.")
            else:
                r.raise_for_status()
                resultat = r.json()
        except httpx.HTTPError:
            erreur = (503, "Le service de diagnostic ne répond pas, réessayez plus tard.")

        if erreur:
            await conn.execute(
                "UPDATE diagnostic SET statut = 'echec', termine_le = now() WHERE id = %s", (diag_id,)
            )
            await conn.commit()
            raise HTTPException(*erreur)

        # 5. Résultat enregistré avec la version du modèle (traçabilité)
        cur = await conn.execute(
            f"""
            UPDATE diagnostic
            SET statut = 'termine', classe = %(classe)s, libelle = %(libelle)s, score = %(score)s,
                modele = %(modele)s, termine_le = now()
            WHERE id = %(id)s
            RETURNING {COLONNES}
            """,
            {**resultat, "id": diag_id},
        )
        ligne = await cur.fetchone()
        await conn.execute(
            """
            INSERT INTO historique (exploitation, utilisateur, type, details)
            SELECT (SELECT exploitation FROM parcelle WHERE id = %(parcelle)s::int), %(uid)s, 'diagnostic',
                   jsonb_build_object('diagnostic', %(id)s::int, 'classe', %(classe)s::text,
                                      'score', %(score)s::real)
            """,
            {"parcelle": parcelle, "uid": utilisateur.id, "id": diag_id,
             "classe": resultat["classe"], "score": resultat["score"]},
        )
    return _vers_diagnostic(ligne)


@router.get(
    "",
    response_model=PageDiagnostics,
    summary="Liste de mes diagnostics (paginée), du plus récent au plus ancien",
    responses=reponses(401, 422),
)
async def lister_diagnostics(
    utilisateur: UtilisateurCourant,
    page: Annotated[int, Query(ge=1)] = 1,
    taille: Annotated[int, Query(ge=1, le=100)] = 20,
):
    params = _params(utilisateur, limite=taille, decalage=(page - 1) * taille)
    async with pool.connection() as conn:
        cur = await conn.execute(f"SELECT count(*) AS total FROM diagnostic {FILTRE}", params)
        total = (await cur.fetchone())["total"]
        cur = await conn.execute(
            f"SELECT {COLONNES} FROM diagnostic {FILTRE} "
            "ORDER BY cree_le DESC, id DESC LIMIT %(limite)s OFFSET %(decalage)s",
            params,
        )
        lignes = await cur.fetchall()
    return PageDiagnostics(elements=[_vers_diagnostic(l) for l in lignes],
                           page=page, taille=taille, total=total)


async def _lire(conn, id: int, utilisateur) -> dict:
    cur = await conn.execute(
        f"SELECT {COLONNES} FROM diagnostic {FILTRE} AND id = %(id)s", _params(utilisateur, id=id)
    )
    ligne = await cur.fetchone()
    if ligne is None:
        raise HTTPException(404, f"Le diagnostic {id} n'existe pas ou ne vous appartient pas.")
    return ligne


@router.get("/{id}", response_model=Diagnostic, summary="Détail d'un diagnostic",
            responses=reponses(401, 404, 422))
async def lire_diagnostic(id: int, utilisateur: UtilisateurCourant):
    async with pool.connection() as conn:
        return _vers_diagnostic(await _lire(conn, id, utilisateur))


@router.patch(
    "/{id}",
    response_model=Diagnostic,
    summary="Confirmer ou infirmer un diagnostic (validation par l'exploitant)",
    responses=reponses(401, 404, 409, 422),
)
async def confirmer_diagnostic(id: int, donnees: Confirmation, utilisateur: UtilisateurCourant):
    async with pool.connection() as conn:
        ligne = await _lire(conn, id, utilisateur)
        if ligne["statut"] != "termine":
            raise HTTPException(409, "Seul un diagnostic terminé peut être confirmé.")
        cur = await conn.execute(
            f"UPDATE diagnostic SET confirme = %s WHERE id = %s RETURNING {COLONNES}",
            (donnees.confirme, id),
        )
        return _vers_diagnostic(await cur.fetchone())


@router.get("/{id}/image", summary="Photo envoyée pour un diagnostic",
            response_class=FileResponse, responses=reponses(401, 404, 422))
async def lire_image(id: int, utilisateur: UtilisateurCourant):
    async with pool.connection() as conn:
        await _lire(conn, id, utilisateur)      # même contrôle d'accès que le détail
    for extension, media in (("jpg", "image/jpeg"), ("png", "image/png")):
        chemin = Path(DOSSIER_IMAGES) / f"{id}.{extension}"
        if chemin.exists():
            return FileResponse(chemin, media_type=media)
    raise HTTPException(404, "Image introuvable.")
