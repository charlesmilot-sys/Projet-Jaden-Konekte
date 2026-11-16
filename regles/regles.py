"""Service des règles d'arrosage : évaluation périodique, météo, ouverture de la vanne."""
import json
import logging
import os
import time
from uuid import uuid4

import paho.mqtt.client as mqtt
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import meteo
from evaluation import evaluer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("regles")

DATABASE_URL = os.environ["DATABASE_URL"]
MQTT_HOTE = os.environ.get("MQTT_HOTE", "mqtt")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_UTILISATEUR = os.environ.get("MQTT_UTILISATEUR")
MQTT_MOT_DE_PASSE = os.environ.get("MQTT_MOT_DE_PASSE")
PERIODE_S = int(os.environ.get("PERIODE_REGLES_S", "60"))

REGLES_ACTIVES = """
    SELECT r.id, r.parcelle, r.nom, r.condition, r.action, r.delai_min_s,
           r.derniere_execution,
           (r.derniere_execution IS NULL
            OR now() - r.derniere_execution >= make_interval(secs => r.delai_min_s)) AS delai_ecoule,
           p.code AS parcelle_code, e.id AS exploitation_id, e.code AS exploitation_code, e.lat, e.lon,
           q.id AS vanne, q.etat AS vanne_etat, q.en_ligne
    FROM regle r
    JOIN parcelle p ON p.id = r.parcelle
    JOIN exploitation e ON e.id = p.exploitation
    LEFT JOIN equipement q ON q.parcelle = p.id AND q.type = 'vanne'
    WHERE r.active
"""

# Dernière mesure de chaque capteur de la parcelle, valide ou non :
# si la plus récente est invalide (capteur en panne), on ne s'en sert pas.
DERNIERES_MESURES = """
    SELECT c.type || '/' || c.grandeur AS nom, m.valeur, m.valide
    FROM capteur c
    JOIN LATERAL (SELECT valeur, valide FROM mesure WHERE capteur = c.id ORDER BY ts DESC LIMIT 1) m ON true
    WHERE c.parcelle = %s AND c.actif
"""


def evaluer_regle(conn: psycopg.Connection, client: mqtt.Client, r: dict) -> None:
    prefixe = f"Règle {r['id']} ({r['exploitation_code']}/{r['parcelle_code']})"

    if not r["delai_ecoule"]:
        log.debug("%s : délai minimal non écoulé", prefixe)
        return
    if r["vanne"] is None or not r["en_ligne"]:
        log.info("%s : vanne absente ou hors ligne, règle ignorée", prefixe)
        return
    if r["vanne_etat"] == "ouverte":
        log.debug("%s : vanne déjà ouverte", prefixe)
        return

    mesures = {l["nom"]: l["valeur"] for l in conn.execute(DERNIERES_MESURES, (r["parcelle"],)) if l["valide"]}
    previsions = meteo.previsions(r["lat"], r["lon"])
    declencher, raison = evaluer(r["condition"], mesures, previsions)

    if not declencher:
        log.info("%s : pas d'arrosage (%s)", prefixe, raison)
        return

    action = r["action"]
    duree_s = int(action.get("duree_s", 600))
    commande_id = f"cmd-{uuid4().hex[:12]}"

    # 1. Commande, exécution de la règle et journal enregistrés ensemble, AVANT la publication
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO commande (id, equipement, action, duree_s, origine, regle, statut)
            VALUES (%s, %s, 'ouvrir', %s, 'regle', %s, 'envoyee')
            """,
            (commande_id, r["vanne"], duree_s, r["id"]),
        )
        conn.execute("UPDATE regle SET derniere_execution = now() WHERE id = %s", (r["id"],))
        conn.execute(
            "INSERT INTO historique (exploitation, type, details) VALUES (%s, 'regle', %s)",
            (r["exploitation_id"], Jsonb({
                "regle": r["id"], "parcelle": r["parcelle"], "commande": commande_id,
                "duree_s": duree_s, "mesures": mesures, "meteo": previsions, "raison": raison,
            })),
        )

    # 2. Publication MQTT ; la confirmation sera traitée par le service d'ingestion
    topic = f"jaden/{r['exploitation_code']}/{r['parcelle_code']}/vanne/cmd"
    info = client.publish(topic, json.dumps({"action": "ouvrir", "duree_s": duree_s, "id": commande_id}), qos=1)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        conn.execute("UPDATE commande SET statut = 'echec' WHERE id = %s", (commande_id,))
        log.error("%s : publication MQTT impossible", prefixe)
        return
    log.info("%s : ARROSAGE %d s (%s) -> %s", prefixe, duree_s, raison, commande_id)


def main() -> None:
    conn = psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jaden-regles")
    if MQTT_UTILISATEUR:
        client.username_pw_set(MQTT_UTILISATEUR, MQTT_MOT_DE_PASSE)
    client.connect_async(MQTT_HOTE, MQTT_PORT, keepalive=30)
    client.loop_start()

    log.info("Évaluation des règles toutes les %d s", PERIODE_S)
    while True:
        time.sleep(PERIODE_S)
        if not client.is_connected():
            log.warning("MQTT non connecté : évaluation reportée")
            continue
        try:
            for regle in conn.execute(REGLES_ACTIVES).fetchall():
                evaluer_regle(conn, client, regle)
        except psycopg.Error:
            log.exception("Erreur base de données pendant l'évaluation")


if __name__ == "__main__":
    main()
