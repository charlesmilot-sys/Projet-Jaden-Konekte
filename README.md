# Kit de démarrage — Projet Jaden Konekté

Master 2 Intelligence Artificielle — Applications et Services Web
Dr. Emmanuel Biabiany, Université des Antilles

Ce kit accompagne le sujet (document Word). Il fournit l'infrastructure de départ, les contrats
et les données : **tout le reste est à concevoir et à coder par votre groupe**.

```
jaden-konekte/
├── contrats/
│   ├── reseau-regional.openapi.yaml   contrat du serveur central (annuaire + alertes + webhook)
│   ├── exemple_webhook_fastapi.py     réception d'une alerte signée (HMAC) dans votre API
│   └── client_test_reseau.py          outil en ligne de commande pour tester le réseau
├── serveur-central/                   serveur hébergé par l'enseignant (fourni pour tests en local)
├── infra/
│   ├── compose.yaml                   broker Mosquitto + PostgreSQL/TimescaleDB/pgvector
│   ├── mosquitto/                     configuration + exemple d'ACL (version sécurisée)
│   └── sql/schema.sql                 système d'information indicatif
├── simulateur/simulateur_capteurs.py  parcelles simulées : capteurs + vanne commandable (MQTT)
├── esp32/main.py                      capteur réel ou simulé (Wokwi) en MicroPython
└── ia/
    ├── cnn/                           préparation PlantVillage, entraînement MobileNetV3, export ONNX
    └── rag/                           fiches techniques + 20 questions de référence
```

## Démarrage rapide

```bash
cd infra
docker compose up -d                        # broker MQTT (1883, 9001 WebSocket) + base (5432)
docker compose --profile simu up -d         # + simulateur de 3 parcelles
# ou, sans Docker pour le simulateur :
pip install paho-mqtt && python ../simulateur/simulateur_capteurs.py --broker localhost --parcelles p1 p2

# observer le flux MQTT
docker compose exec mqtt mosquitto_sub -t 'jaden/#' -v

# commander une vanne
docker compose exec mqtt mosquitto_pub -t jaden/expl-1/p1/vanne/cmd \
  -m '{"action":"ouvrir","duree_s":600,"id":"cmd-1"}'
```

Serveur central en local (pour tester votre webhook avant la mise en réseau) :

```bash
cd serveur-central && pip install -r requirements.txt && uvicorn main:app --port 8080
# documentation interactive : http://localhost:8080/docs
```

## Conventions MQTT

| Topic | Sens | Contenu |
|---|---|---|
| `jaden/<expl>/<parcelle>/sol/humidite` | objet → plateforme | `{"valeur": 31.2, "unite": "%", "ts": "...", "capteur": "p1-sol"}` |
| `jaden/<expl>/<parcelle>/air/temperature` | objet → plateforme | idem (°C) |
| `jaden/<expl>/<parcelle>/air/luminosite` | objet → plateforme | idem (lx) |
| `jaden/<expl>/<parcelle>/pluvio/intensite` | objet → plateforme | idem (mm/h) |
| `jaden/<expl>/<parcelle>/vanne/cmd` | plateforme → objet | `{"action": "ouvrir", "duree_s": 600, "id": "cmd-42"}` |
| `jaden/<expl>/<parcelle>/vanne/etat` | objet → plateforme (retenu) | `{"etat": "ouverte", "jusqua": "...", "derniere_cmd": "cmd-42"}` |
| `jaden/<expl>/<parcelle>/statut` | objet → plateforme (retenu, LWT) | `online` / `offline` |

Le simulateur produit volontairement, de temps en temps, des **valeurs aberrantes** (capteur en panne) :
votre chaîne d'ingestion doit les détecter.
