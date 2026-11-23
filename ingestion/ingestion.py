"""Service d'ingestion : MQTT -> validation -> hypertable `mesure`."""
import json
import logging
import os
import threading
import time
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

TOPIC = "jaden/#"                  # mesures, statut des objets et état des vannes
DELAI_CONFIRMATION_S = 30          # au-delà, une commande non confirmée passe en échec

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
    """Aiguille chaque message selon son topic."""
    morceaux = topic.split("/")
    if not contenu and morceaux[-1] != "config":
        return   # message vide : effacement d'un message retenu (parcelle retirée), rien à enregistrer
    if len(morceaux) == 4 and morceaux[3] == "statut":
        traiter_statut(conn, morceaux[1], morceaux[2], contenu)
    elif len(morceaux) == 4 and morceaux[3] == "config":
        # Parcelle annoncée ou retirée par l'API : ses capteurs viennent d'être créés ou déplacés
        log.info("Parcelle %s/%s %s : rechargement des capteurs", morceaux[1], morceaux[2],
                 "annoncée" if contenu else "retirée")
        charger_capteurs(conn)
    elif len(morceaux) == 5 and morceaux[3:] == ["vanne", "etat"]:
        traiter_etat_vanne(conn, morceaux[1], morceaux[2], contenu)
    elif len(morceaux) == 5:
        traiter_mesure(conn, topic, morceaux, contenu)


# --- Mesures ------------------------------------------------------------------

def traiter_mesure(conn: psycopg.Connection, topic: str, morceaux: list[str], contenu: bytes) -> None:
    capteur_etat = capteurs.get(tuple(morceaux[1:]))
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


# --- Objets et vannes -----------------------------------------------------------

# Met à jour la vanne d'une parcelle désignée par ses codes MQTT
MAJ_VANNE = """
    UPDATE equipement q SET {colonnes}, maj_le = now()
    FROM parcelle p JOIN exploitation e ON e.id = p.exploitation
    WHERE q.parcelle = p.id AND q.type = 'vanne'
      AND e.code = %(expl)s AND p.code = %(parcelle)s
"""


def traiter_statut(conn: psycopg.Connection, expl: str, parcelle: str, contenu: bytes) -> None:
    statut = contenu.decode(errors="replace").strip()
    if statut not in ("online", "offline"):
        log.warning("Statut inconnu pour %s/%s : %r", expl, parcelle, statut)
        return
    conn.execute(MAJ_VANNE.format(colonnes="en_ligne = %(en_ligne)s"),
                 {"en_ligne": statut == "online", "expl": expl, "parcelle": parcelle})
    log.info("Objet %s/%s : %s", expl, parcelle, statut)


def traiter_etat_vanne(conn: psycopg.Connection, expl: str, parcelle: str, contenu: bytes) -> None:
    try:
        donnees = json.loads(contenu)
        etat = donnees["etat"]
        if etat not in ("ouverte", "fermee"):
            raise ValueError(f"état inconnu {etat!r}")
        jusqua = datetime.fromisoformat(donnees["jusqua"]) if donnees.get("jusqua") else None
        derniere_cmd = donnees.get("derniere_cmd")
    except (ValueError, KeyError, TypeError) as e:
        log.warning("État de vanne mal formé pour %s/%s (%s)", expl, parcelle, e)
        return

    conn.execute(
        MAJ_VANNE.format(colonnes="etat = %(etat)s, jusqua = %(jusqua)s, derniere_cmd = %(cmd)s"),
        {"etat": etat, "jusqua": jusqua, "cmd": derniere_cmd, "expl": expl, "parcelle": parcelle},
    )
    if derniere_cmd:
        # La vanne confirme avoir exécuté cette commande
        cur = conn.execute(
            "UPDATE commande SET statut = 'confirmee' WHERE id = %s AND statut <> 'confirmee' RETURNING id",
            (derniere_cmd,),
        )
        if cur.fetchone():
            log.info("Commande %s confirmée par %s/%s (vanne %s)", derniere_cmd, expl, parcelle, etat)


def surveiller_commandes(conn: psycopg.Connection) -> None:
    """Toutes les 10 s : une commande sans confirmation depuis plus de 30 s passe en échec."""
    while True:
        time.sleep(10)
        try:
            cur = conn.execute(
                """
                UPDATE commande SET statut = 'echec'
                WHERE statut = 'envoyee' AND cree_le < now() - make_interval(secs => %s)
                RETURNING id
                """,
                (DELAI_CONFIRMATION_S,),
            )
            for ligne in cur.fetchall():
                log.warning("Commande %s sans confirmation : échec", ligne["id"])
        except psycopg.Error:
            log.exception("Erreur pendant la surveillance des commandes")


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
        c.subscribe(TOPIC, qos=1)
        log.info("Connecté à %s:%d, abonné à %s", MQTT_HOTE, MQTT_PORT, TOPIC)

    def on_message(c, userdata, msg):
        try:
            traiter(conn, msg.topic, msg.payload)
        except psycopg.Error:
            log.exception("Erreur base de données sur %s", msg.topic)

    threading.Thread(target=surveiller_commandes, args=(conn,), daemon=True).start()

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOTE, MQTT_PORT, keepalive=30)
    client.loop_forever()  # gère aussi la reconnexion automatique


if __name__ == "__main__":
    main()