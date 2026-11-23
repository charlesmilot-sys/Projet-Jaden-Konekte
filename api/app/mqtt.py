"""Client MQTT de l'API : publie les commandes de vanne et l'annonce des parcelles (voir provision.py)."""
import json
import logging

import paho.mqtt.client as mqtt

from app.config import MQTT_HOTE, MQTT_MOT_DE_PASSE, MQTT_PORT, MQTT_UTILISATEUR

log = logging.getLogger("uvicorn.error")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jaden-api")


def demarrer() -> None:
    if MQTT_UTILISATEUR:
        client.username_pw_set(MQTT_UTILISATEUR, MQTT_MOT_DE_PASSE)
    client.connect_async(MQTT_HOTE, MQTT_PORT, keepalive=30)
    client.loop_start()  # boucle réseau dans un thread : connexion et reconnexion automatiques


def arreter() -> None:
    client.loop_stop()
    client.disconnect()


def publier(topic: str, donnees: dict, retenu: bool = False) -> bool:
    """Publie en QoS 1. Renvoie False si le broker n'est pas joignable."""
    return _envoyer(topic, json.dumps(donnees), retenu)


def publier_vide(topic: str) -> bool:
    """Message vide retenu : efface le message retenu du topic."""
    return _envoyer(topic, b"", True)


def _envoyer(topic: str, contenu, retenu: bool) -> bool:
    if not client.is_connected():
        log.warning("MQTT non connecté : publication impossible sur %s", topic)
        return False
    info = client.publish(topic, contenu, qos=1, retain=retenu)
    return info.rc == mqtt.MQTT_ERR_SUCCESS