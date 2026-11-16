"""Historique agrégé des mesures d'une parcelle (graphiques du tableau de bord)."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.db import pool
from app.erreurs import reponses
from app.schemas import Grandeur, Periode, SerieMesures
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1/parcelles", tags=["Mesures"])

# Pour chaque période : durée de la fenêtre et taille d'une tranche
PERIODES = {
    "24h": ("24 hours", "1 hour"),   # 24 points
    "7j": ("7 days", "6 hours"),     # 28 points
}


@router.get(
    "/{id}/mesures",
    response_model=SerieMesures,
    summary="Historique agrégé d'une grandeur (moyenne, min, max par tranche)",
    description="Seules les mesures valides sont agrégées. Tranches de 1 h sur 24 h, de 6 h sur 7 jours.",
    responses=reponses(401, 404, 422),
)
async def historique(
    id: int,
    utilisateur: UtilisateurCourant,
    grandeur: Annotated[Grandeur, Query()],
    periode: Annotated[Periode, Query()] = "24h",
):
    duree, tranche = PERIODES[periode]
    async with pool.connection() as conn:
        # 1. Le capteur de cette grandeur, sur une parcelle à laquelle l'utilisateur a droit
        cur = await conn.execute(
            """
            SELECT c.id, c.unite
            FROM capteur c
            JOIN parcelle p ON p.id = c.parcelle
            JOIN exploitation e ON e.id = p.exploitation
            WHERE p.id = %(parcelle)s AND c.grandeur = %(grandeur)s
              AND (%(admin)s OR e.proprietaire = %(uid)s)
            """,
            {"parcelle": id, "grandeur": grandeur,
             "admin": utilisateur.role == "administrateur", "uid": utilisateur.id},
        )
        capteur = await cur.fetchone()
        if capteur is None:
            raise HTTPException(404, f"Aucun capteur « {grandeur} » sur la parcelle {id}, "
                                     "ou parcelle introuvable.")

        # 2. Agrégats par tranche, sur la fenêtre qui se termine à la mesure valide la plus récente
        cur = await conn.execute(
            """
            SELECT time_bucket(%(tranche)s::interval, ts) AS debut,
                   round(avg(valeur)::numeric, 2)::float AS moyenne,
                   round(min(valeur)::numeric, 2)::float AS min,
                   round(max(valeur)::numeric, 2)::float AS max,
                   count(*) AS nombre
            FROM mesure
            WHERE capteur = %(capteur)s AND valide
              AND ts > (SELECT max(ts) FROM mesure WHERE capteur = %(capteur)s AND valide)
                       - %(duree)s::interval
            GROUP BY debut
            ORDER BY debut
            """,
            {"tranche": tranche, "duree": duree, "capteur": capteur["id"]},
        )
        points = await cur.fetchall()

    return SerieMesures(grandeur=grandeur, unite=capteur["unite"], periode=periode,
                        intervalle=tranche, points=points)