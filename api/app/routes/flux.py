"""Flux temps réel (SSE) : dernières valeurs valides et état de la vanne d'une parcelle."""
import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.acces import parcelle_autorisee
from app.db import pool
from app.erreurs import reponses
from app.schemas import EtatParcelle
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1/parcelles", tags=["Tableau de bord"])

PERIODE_S = 2      # fréquence de lecture de la base
PING_S = 15        # commentaire envoyé régulièrement pour garder la connexion ouverte


async def lire_etat(parcelle_id: int) -> EtatParcelle:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT c.grandeur, c.unite, m.valeur, m.ts, d.valide AS fiable
            FROM capteur c
            -- dernière mesure VALIDE : la valeur affichée
            JOIN LATERAL (
                SELECT valeur, ts FROM mesure
                WHERE capteur = c.id AND valide
                ORDER BY ts DESC LIMIT 1
            ) m ON true
            -- dernière mesure reçue, valide ou non : si elle est invalide, le capteur est en panne
            JOIN LATERAL (
                SELECT valide FROM mesure WHERE capteur = c.id ORDER BY ts DESC LIMIT 1
            ) d ON true
            WHERE c.parcelle = %s AND c.actif
            """,
            (parcelle_id,),
        )
        mesures = {l["grandeur"]: l for l in await cur.fetchall()}
        cur = await conn.execute(
            """
            SELECT id, type, etat, jusqua, derniere_cmd, en_ligne, maj_le
            FROM equipement WHERE parcelle = %s AND type = 'vanne'
            """,
            (parcelle_id,),
        )
        vanne = await cur.fetchone()
    return EtatParcelle(mesures=mesures, vanne=vanne)


@router.get(
    "/{id}/flux",
    summary="Flux temps réel de la parcelle (Server-Sent Events)",
    description="Envoie un événement `etat` (JSON `EtatParcelle`) à la connexion, puis à chaque "
                "changement : nouvelle mesure valide, état de la vanne, objet en ligne ou hors ligne.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}, **reponses(401, 404, 422)},
)
async def flux(id: int, utilisateur: UtilisateurCourant, request: Request):
    async with pool.connection() as conn:
        await parcelle_autorisee(conn, id, utilisateur)   # 404 avant d'ouvrir le flux

    async def evenements():
        precedent = None
        dernier_envoi = time.monotonic()
        while not await request.is_disconnected():
            etat = (await lire_etat(id)).model_dump_json()
            if etat != precedent:
                yield f"event: etat\ndata: {etat}\n\n"
                precedent = etat
                dernier_envoi = time.monotonic()
            elif time.monotonic() - dernier_envoi > PING_S:
                yield ": ping\n\n"
                dernier_envoi = time.monotonic()
            await asyncio.sleep(PERIODE_S)

    return StreamingResponse(
        evenements(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )