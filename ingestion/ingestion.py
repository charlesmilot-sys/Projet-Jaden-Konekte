"""Service d'ingestion : MQTT -> validation -> hypertable `mesure`."""
import json
import logging
import os
from datetime import datetime

import paho.mqtt.client as mqtt
import psycopg
from psycopg.rows import dict_row

from validation import Capteur, Etat, valider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingestion")

DATABASE_URL = os.environ["DATABASE_URL"]
MQTT_HOTE = os.environ.get("MQTT_HOTE", "mqtt")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_UTILISATEUR = os.environ.get("MQTT_UTILISATEUR")
MQTT_MOT_DE_PASSE = os.environ.get("MQTT_MOT_DE_PASSE")

TOPIC_MESURES = "jaden/+/+/+/+"   # jaden/<expl>/<parcelle>/<type>/<grandeur>

# Clé : (exploitation, parcelle, type, grandeur) -> (capteur, état)
capteurs: dict[tuple[str, str, str, str], tuple[Capteur, Etat]] = {}


def charger_capteurs(conn: psycopg.Connection) -> None:
    """Lit les capteurs actifs et, pour chacun, sa dernière mesure valide (reprise après redémarrage)."""
    lignes = conn.execute(
        """
        SELECT c.id, e.code AS expl, p.code AS parcelle, c.type, c.grandeur,
               c.min_valide, c.max_valide, c.baisse_max_min, c.hausse_max_min,
               m.valeur, m.ts
        FROM capteur c
        JOIN parcelle p ON p.id = c.parcelle
        JOIN exploitation e ON e.id = p.exploitation
        LEFT JOIN LATERAL (
            SELECT valeur, ts FROM mesure
            WHERE capteur = c.id AND valide
            ORDER BY ts DESC LIMIT 1
        ) m ON true
        WHERE c.actif
        """
    ).fetchall()
    capteurs.clear()
    for l in lignes:
        capteur = Capteur(
            id=l["id"],
            min_valide=_nombre(l["min_valide"]),
            max_valide=_nombre(l["max_valide"]),
            baisse_max_min=_nombre(l["baisse_max_min"]),
            hausse_max_min=_nombre(l["hausse_max_min"]),
        )
        etat = Etat(derniere_valeur=l["valeur"], dernier_ts=l["ts"], dernier_ts_vu=l["ts"])
        capteurs[(l["expl"], l["parcelle"], l["type"], l["grandeur"])] = (capteur, etat)
    log.info("%d capteurs chargés", len(capteurs))


def _nombre(x) -> float | None:
    return None if x is None else float(x)


def lire_message(contenu: bytes) -> tuple[float, datetime]:
    """Vérifie le format du message : {"valeur": nombre, "ts": date ISO avec fuseau, ...}."""
    donnees = json.loads(contenu)
    valeur = donnees["valeur"]
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        raise ValueError("valeur non numérique")
    ts = datetime.fromisoformat(donnees["ts"])
    if ts.tzinfo is None:
        raise ValueError("date sans fuseau horaire")
    return float(valeur), ts


def traiter(conn: psycopg.Connection, topic: str, contenu: bytes) -> None:
    morceaux = topic.split("/")
    capteur_etat = capteurs.get(tuple(morceaux[1:])) if len(morceaux) == 5 else None
    if capteur_etat is None:
        log.debug("Topic ignoré (aucun capteur connu) : %s", topic)
        return

    try:
        valeur, ts = lire_message(contenu)
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Message mal formé sur %s (%s) : %r", topic, e, contenu[:100])
        return

    capteur, etat = capteur_etat
    if etat.dernier_ts_vu is not None and ts <= etat.dernier_ts_vu:
        log.debug("Doublon ou message ancien ignoré : %s %s", topic, ts)
        return

    valide = valider(capteur, etat, valeur, ts)
    etat.dernier_ts_vu = ts
    conn.execute(
        """
        INSERT INTO mesure (ts, capteur, valeur, valide)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (capteur, ts) DO NOTHING
        """,
        (ts, capteur.id, valeur, valide),
    )
    if not valide:
        log.warning("Mesure marquée invalide : %s = %s", topic, valeur)


def main() -> None:
    conn = psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row)
    charger_capteurs(conn)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="jaden-ingestion",
        clean_session=False,  # le broker garde nos messages QoS 1 si le service redémarre
    )
    if MQTT_UTILISATEUR:
        client.username_pw_set(MQTT_UTILISATEUR, MQTT_MOT_DE_PASSE)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Connexion MQTT refusée : %s", reason_code)
            return
        c.subscribe(TOPIC_MESURES, qos=1)
        log.info("Connecté à %s:%d, abonné à %s", MQTT_HOTE, MQTT_PORT, TOPIC_MESURES)

    def on_message(c, userdata, msg):
        try:
            traiter(conn, msg.topic, msg.payload)
        except psycopg.Error:
            log.exception("Erreur base de données sur %s", msg.topic)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOTE, MQTT_PORT, keepalive=30)
    client.loop_forever()  # gère aussi la reconnexion automatique


if __name__ == "__main__":
    main()