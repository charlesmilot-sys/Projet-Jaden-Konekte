"""Contrôle d'accès au niveau objet, commun à toutes les routes d'une parcelle."""
from fastapi import HTTPException
from psycopg import AsyncConnection

from app.schemas import Utilisateur


async def parcelle_autorisee(conn: AsyncConnection, parcelle_id: int, utilisateur: Utilisateur) -> dict:
    """Renvoie les codes MQTT de la parcelle, ou lève 404 si elle n'existe pas ou n'est pas à l'utilisateur."""
    cur = await conn.execute(
        """
        SELECT p.id, p.code AS parcelle, e.code AS exploitation
        FROM parcelle p
        JOIN exploitation e ON e.id = p.exploitation
        WHERE p.id = %(id)s AND (%(admin)s OR e.proprietaire = %(uid)s)
        """,
        {"id": parcelle_id, "admin": utilisateur.role == "administrateur", "uid": utilisateur.id},
    )
    ligne = await cur.fetchone()
    if ligne is None:
        raise HTTPException(404, f"La parcelle {parcelle_id} n'existe pas ou ne vous appartient pas.")
    return ligne