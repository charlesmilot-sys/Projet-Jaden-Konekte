"""État de la vanne et commandes (ouverture / fermeture)."""
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status

from app import mqtt
from app.acces import parcelle_autorisee
from app.db import pool
from app.erreurs import reponses
from app.schemas import Commande, CommandeEntree, Equipement
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1/parcelles", tags=["Commandes"])


@router.get(
    "/{id}/equipements",
    response_model=list[Equipement],
    summary="État des équipements de la parcelle (vanne)",
    responses=reponses(401, 404, 422),
)
async def lister_equipements(id: int, utilisateur: UtilisateurCourant):
    async with pool.connection() as conn:
        await parcelle_autorisee(conn, id, utilisateur)
        cur = await conn.execute(
            """
            SELECT id, type, etat, jusqua, derniere_cmd, en_ligne, maj_le
            FROM equipement WHERE parcelle = %s ORDER BY id
            """,
            (id,),
        )
        return await cur.fetchall()


@router.get(
    "/{id}/commandes",
    response_model=list[Commande],
    summary="Journal des ordres envoyés à la vanne (les plus récents d'abord)",
    description="Ordres manuels et déclenchements de la règle d'arrosage, avec leur statut.",
    responses=reponses(401, 404, 422),
)
async def journal_commandes(
    id: int,
    utilisateur: UtilisateurCourant,
    limite: Annotated[int, Query(ge=1, le=50)] = 15,
):
    async with pool.connection() as conn:
        await parcelle_autorisee(conn, id, utilisateur)
        cur = await conn.execute(
            """
            SELECT c.id, c.action, c.duree_s, c.origine, c.statut, c.cree_le
            FROM commande c
            JOIN equipement v ON v.id = c.equipement
            WHERE v.parcelle = %s
            ORDER BY c.cree_le DESC
            LIMIT %s
            """,
            (id, limite),
        )
        return await cur.fetchall()


@router.post(
    "/{id}/commandes",
    response_model=Commande,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Envoyer un ordre à la vanne",
    description="Réponse 202 : l'ordre est publié, la confirmation par l'objet arrive ensuite "
                "(statut `confirmee`, ou `echec` sans réponse au bout de 30 s).",
    responses=reponses(401, 404, 409, 422, 503),
)
async def envoyer_commande(id: int, donnees: CommandeEntree, utilisateur: UtilisateurCourant):
    duree_s = donnees.duree_s if donnees.action == "ouvrir" else None
    async with pool.connection() as conn:
        parcelle = await parcelle_autorisee(conn, id, utilisateur)

        cur = await conn.execute(
            "SELECT id, en_ligne FROM equipement WHERE parcelle = %s AND type = 'vanne'", (id,)
        )
        vanne = await cur.fetchone()
        if vanne is None:
            raise HTTPException(404, f"La parcelle {id} n'a pas de vanne.")
        if not vanne["en_ligne"]:
            raise HTTPException(409, "L'objet de la parcelle est hors ligne : commande impossible.")

        # 1. On enregistre la commande AVANT de l'envoyer : elle est tracée même si l'envoi échoue
        cur = await conn.execute(
            """
            INSERT INTO commande (id, equipement, action, duree_s, origine, auteur, statut)
            VALUES (%s, %s, %s, %s, 'manuelle', %s, 'envoyee')
            RETURNING id, action, duree_s, origine, statut, cree_le
            """,
            (f"cmd-{uuid4().hex[:12]}", vanne["id"], donnees.action, duree_s, utilisateur.id),
        )
        commande = await cur.fetchone()
        await conn.commit()  # validée AVANT la publication : la confirmation de l'objet doit la trouver

        # 2. Publication MQTT, dans le format attendu par l'objet
        topic = f"jaden/{parcelle['exploitation']}/{parcelle['parcelle']}/vanne/cmd"
        message = {"action": donnees.action, "id": commande["id"]}
        if duree_s is not None:
            message["duree_s"] = duree_s
        if not mqtt.publier(topic, message):
            await conn.execute("UPDATE commande SET statut = 'echec' WHERE id = %s", (commande["id"],))
            await conn.commit()
            raise HTTPException(503, "Le broker MQTT est injoignable : la commande n'a pas été envoyée.")

    return commande