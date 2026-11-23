"""Annonce des parcelles en MQTT : jaden/<exploitation>/<parcelle>/config (message retenu).

Une parcelle créée ou déplacée par l'administrateur est annoncée ; le simulateur se met alors à la
simuler et l'ingestion recharge ses capteurs. Un message vide retenu retire l'annonce.
Au démarrage de l'API, toutes les parcelles sont annoncées à nouveau (broker vidé, base recréée…).
"""
import asyncio
import logging

from app import mqtt
from app.db import pool

log = logging.getLogger("uvicorn.error")


def _topic(expl: str, parcelle: str) -> str:
    return f"jaden/{expl}/{parcelle}/config"


def annoncer(expl: str, parcelle: str, culture: str) -> bool:
    return mqtt.publier(_topic(expl, parcelle), {"culture": culture}, retenu=True)


def retirer(expl: str, parcelle: str) -> bool:
    return mqtt.publier_vide(_topic(expl, parcelle))


async def annoncer_toutes() -> None:
    for _ in range(30):                      # le client MQTT se connecte en arrière-plan
        if mqtt.client.is_connected():
            break
        await asyncio.sleep(1)
    else:
        log.warning("MQTT non connecté : parcelles non annoncées")
        return
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT e.code AS expl, p.code, p.culture FROM parcelle p JOIN exploitation e ON e.id = p.exploitation"
        )
        lignes = await cur.fetchall()
    for l in lignes:
        annoncer(l["expl"], l["code"], l["culture"])
    log.info("%d parcelles annoncées en MQTT", len(lignes))
