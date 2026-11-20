# Jaden Konekté

Plateforme de suivi des jardins et petites exploitations agricoles : capteurs connectés (MQTT),
arrosage manuel ou automatique tenant compte de la météo, diagnostic des maladies de la tomate sur photo
(CNN en ONNX) et assistant agronome qui répond à partir de fiches techniques en citant ses sources (RAG).

Projet individuel — Master 2 Intelligence Artificielle, Applications et Services Web, Université des Antilles.

## Démarrage

Prérequis : Docker Desktop (ou Docker Engine avec Compose v2) et une clé d'API Groq gratuite
(<https://console.groq.com>, menu « API Keys »).

```bash
cd infra
cp .env.exemple .env        # puis remplacer chaque « change-moi » (voir ci-dessous)
docker compose up -d --build
```

La première construction prend quelques minutes (téléchargement du modèle d'embeddings, environ 220 Mo).
À la création de la base, PostgreSQL exécute `infra/sql/schema.sql` puis `infra/sql/demo.sql` :
la plateforme démarre avec une exploitation de démonstration et ses trois parcelles, alimentées par le simulateur.

| Adresse | Contenu |
|---|---|
| <http://localhost:8000> | Tableau de bord |
| <http://localhost:8000/docs> | Documentation interactive de l'API |

Comptes :

| Compte | Courriel | Mot de passe |
|---|---|---|
| Exploitant de démonstration (parcelles p1, p2, p3) | `test@exemple.fr` | `DEMO_MOT_DE_PASSE` du fichier `.env` |
| Administrateur (voit toutes les parcelles) | `ADMIN_COURRIEL` du fichier `.env` | `ADMIN_MOT_DE_PASSE` du fichier `.env` |

N'importe qui peut aussi s'inscrire (`POST /api/v1/utilisateurs`) : il obtient un compte exploitant sans parcelle.

### Variables d'environnement (`infra/.env`)

Aucun secret n'est versionné : `.env` est ignoré par Git, `.env.exemple` en donne la liste.

| Variable | Rôle |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Base de données |
| `JWT_SECRET` | Signature des jetons (une longue chaîne aléatoire) |
| `MQTT_MDP_INGESTION`, `MQTT_MDP_API`, `MQTT_MDP_REGLES`, `MQTT_MDP_SIMULATEUR` | Un compte MQTT par service (droits définis dans `infra/mosquitto/acl`) |
| `GROQ_API_KEY` | Clé du LLM de l'assistant (reste dans le service `assistant`) |
| `GROQ_MODELE` | Facultatif, `openai/gpt-oss-120b` par défaut |
| `ADMIN_COURRIEL`, `ADMIN_MOT_DE_PASSE` | Compte administrateur, créé au démarrage de l'API |
| `DEMO_MOT_DE_PASSE` | Mot de passe du compte de démonstration |

## Architecture

Les principaux flux :

- **Mesures** : simulateur → MQTT → `ingestion` (validation) → table `mesure` → `api` → tableau de bord (SSE).
- **Commande de vanne** : tableau de bord → `api` (ou `regles`) → MQTT → vanne → état confirmé → `ingestion`.
- **Règle d'arrosage** : `regles` lit les mesures valides et la pluie prévue (Open-Meteo), puis ouvre la vanne.
- **Diagnostic** : photo → `api` (contrôles) → `inference` (ONNX Runtime) → table `diagnostic`.
- **Assistant** : question → `api` (jeton) → `assistant` (recherche dans `passage`) → Groq → réponse en SSE.

| Service | Dossier | Rôle |
|---|---|---|
| `mqtt` | `infra/mosquitto` | Broker Mosquitto : comptes par service et ACL |
| `db` | `infra/sql` | PostgreSQL 16, TimescaleDB (hypertable `mesure`), pgvector (table `passage`) |
| `simulateur` | `simulateur` | Trois parcelles simulées (capteurs, vanne, pannes volontaires), temps accéléré ×60 |
| `ingestion` | `ingestion` | Abonné à `jaden/#` : validation des mesures, confirmation des commandes, statut des objets |
| `regles` | `regles` | Vérifie la règle de chaque parcelle toutes les 30 s (humidité du sol + pluie prévue) |
| `api` | `api` | API REST (JWT, Problem Details), flux SSE, tableau de bord (`api/static`) |
| `inference` | `inference` | Diagnostic CNN : MobileNetV3-Small en ONNX, chargé une seule fois |
| `assistant` | `assistant` | RAG : indexation des fiches, recherche hybride, réponse de Groq en streaming |

Ports exposés : l'API (8000), le broker (1883, 9001) et la base (5432, utile en développement).
`inference` et `assistant` n'ont aucun port publié : seule l'API les joint, par le réseau interne de Docker.

Le contrat de l'API est `openapi.yaml` (OpenAPI 3.1) ; ses écarts avec le contrat initial sont expliqués
dans `ecarts_contrat.md`.

## Tests

Avec la plateforme démarrée :

```bash
cd infra
docker compose --profile tests run --rm tests
```

37 tests : validation des mesures, règle d'arrosage, prétraitement des images, découpage des fiches
(tests unitaires) ; authentification, contrôle d'accès, diagnostic et conformité au contrat OpenAPI
(tests de bout en bout sur l'API en marche).

## Intelligence artificielle

**Diagnostic (CNN).** Le modèle `ia/cnn/modele/tomate_mobilenetv3.onnx` est fourni. Pour le réentraîner
(GPU conseillé, par exemple Google Colab) :

```bash
cd ia/cnn
python preparer_donnees.py --source <dossier PlantVillage color> --sortie donnees
python entrainement.py --donnees donnees --epoques 5      # ONNX + historique.json + courbes.png
python evaluer_onnx.py                                    # évaluation du fichier ONNX : evaluation.json
```

**Assistant (RAG).** Les fiches de `ia/rag/fiches` sont réindexées à chaque démarrage du service.
Évaluation sur les 20 questions de référence :

```bash
cd infra
docker compose exec assistant python evaluer.py
docker compose cp assistant:/tmp/evaluation_rag.md ../ia/rag/evaluation_rag.md
```

## Exploitation

```bash
docker compose logs -f regles          # décisions de la règle d'arrosage
docker compose logs -f ingestion       # mesures rejetées, commandes confirmées
docker compose stop                    # arrêter sans rien effacer
docker compose start                   # relancer
```

`docker compose down -v` supprime aussi les données (base, photos) : la base est alors recréée avec les
données de démonstration au démarrage suivant.

Une base créée avec une version antérieure du schéma se met à jour avec les scripts de `infra/sql/maj/`
(`docker compose cp` puis `psql -f`).

## Structure du dépôt

```
api/            API FastAPI et tableau de bord (static/)
assistant/      service RAG (indexation, recherche, Groq) et script d'évaluation
inference/      service d'inférence ONNX
ingestion/      service d'ingestion MQTT et règles de validation
regles/         service de la règle d'arrosage et client Open-Meteo
simulateur/     simulateur de parcelles (kit)
ia/cnn/         entraînement, export et évaluation du CNN ; modèle ONNX
ia/rag/         fiches techniques, questions de référence, évaluation de l'assistant
infra/          compose.yaml, Mosquitto, SQL (schéma, démonstration, mises à jour)
tests/          tests pytest
contrats/, serveur-central/, esp32/   éléments du kit pour les bonus (non utilisés)
```

## Utilisation de l'IA générative

Le projet a été réalisé avec l'aide de Claude (Anthropic) ; son usage est détaillé dans le rapport.
