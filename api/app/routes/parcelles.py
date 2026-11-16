"""Parcelles : chaque exploitant ne voit que les siennes (contrôle d'accès au niveau objet)."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.db import pool
from app.erreurs import reponses
from app.schemas import PageParcelles, Parcelle
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1/parcelles", tags=["Parcelles"])

# Un administrateur voit tout ; un exploitant, seulement les parcelles de ses exploitations.
FILTRE_PROPRIETAIRE = """
    FROM parcelle p
    JOIN exploitation e ON e.id = p.exploitation
    WHERE (%(admin)s OR e.proprietaire = %(uid)s)
"""


@router.get(
    "",
    response_model=PageParcelles,
    summary="Liste de mes parcelles (paginée)",
    responses=reponses(401, 422),
)
async def lister_parcelles(
    utilisateur: UtilisateurCourant,
    page: Annotated[int, Query(ge=1)] = 1,
    taille: Annotated[int, Query(ge=1, le=100)] = 20,
):
    params = {
        "admin": utilisateur.role == "administrateur",
        "uid": utilisateur.id,
        "limite": taille,
        "decalage": (page - 1) * taille,
    }
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS total" + FILTRE_PROPRIETAIRE, params)
        total = (await cur.fetchone())["total"]
        cur = await conn.execute(
            "SELECT p.id, p.code, p.nom, p.culture, p.surface_m2"
            + FILTRE_PROPRIETAIRE
            + " ORDER BY p.id LIMIT %(limite)s OFFSET %(decalage)s",
            params,
        )
        lignes = await cur.fetchall()
    return PageParcelles(elements=lignes, page=page, taille=taille, total=total)


@router.get(
    "/{id}",
    response_model=Parcelle,
    summary="Détail d'une parcelle",
    responses=reponses(401, 404, 422),
)
async def lire_parcelle(id: int, utilisateur: UtilisateurCourant):
    params = {"admin": utilisateur.role == "administrateur", "uid": utilisateur.id, "id": id}
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT p.id, p.code, p.nom, p.culture, p.surface_m2"
            + FILTRE_PROPRIETAIRE
            + " AND p.id = %(id)s",
            params,
        )
        ligne = await cur.fetchone()
    if ligne is None:
        raise HTTPException(404, f"La parcelle {id} n'existe pas ou ne vous appartient pas.")
    return ligne