"""Configuration lue dans les variables d'environnement (aucun secret dans le code)."""
import os

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_DUREE_S = int(os.environ.get("JWT_DUREE_S", "3600"))

MQTT_HOTE = os.environ.get("MQTT_HOTE", "mqtt")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_UTILISATEUR = os.environ.get("MQTT_UTILISATEUR")
MQTT_MOT_DE_PASSE = os.environ.get("MQTT_MOT_DE_PASSE")