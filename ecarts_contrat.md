# Écarts entre le contrat initial et l'implémentation

Le contrat `openapi.yaml` a été rédigé **avant** l'implémentation (version 1.0.0, voir l'historique Git).
Il a ensuite été comparé à la spécification générée par FastAPI (`http://localhost:8000/openapi.json`) ;
les écarts ci-dessous ont été intégrés dans la version 1.1.0. Depuis, `tests/test_contrat.py` vérifie
automatiquement que le contrat et le code exposent exactement les mêmes routes et les mêmes codes de réponse.

Aucune route du contrat initial n'a été supprimée.

| # | Contrat 1.0.0 | Implémentation (contrat 1.1.0) | Raison |
|---|---|---|---|
| 1 | `POST /api/v1/questions` | `POST /api/v1/assistant/questions` | Regrouper les routes de l'assistant sous une ressource dédiée ; `/questions` seul ne disait pas à qui la question est posée. |
| 2 | Événements SSE `morceau` (`{"texte"}`), `sources`, `fin` (`{"hors_fiches"}`) | `texte` (`{"t"}`), `fin` (`{"hors_fiches", "sources", "modele"}`), `erreur` (`{"detail"}`) | Les sources ne sont connues qu'à la fin : on ne garde que celles réellement citées dans la réponse (numéros entre crochets), pas tous les passages retrouvés. Une fois le flux commencé (statut 200 déjà envoyé), une erreur du LLM ne peut plus être un code HTTP : d'où l'événement `erreur`. |
| 3 | Question de 1 000 caractères au plus | 500 caractères au plus | Limiter la consommation du quota gratuit de Groq ; une question d'exploitant tient largement en 500 caractères. |
| 4 | — | `GET /api/v1/parcelles/{id}/flux` (SSE) | Mise à jour en direct du tableau de bord, exigée par le sujet mais oubliée dans le contrat initial. |
| 5 | — | `PATCH /api/v1/diagnostics/{id}` (`{"confirme"}`) | Confirmation du diagnostic par l'exploitant : réponse à la limite du CNN sur les photos prises au champ. |
| 6 | — | `GET /api/v1/diagnostics/{id}/image` | `image_url` devait pointer vers une ressource ; la photo est protégée par le même contrôle d'accès que le diagnostic. |
| 7 | `Diagnostic` | + `fiable`, `termine_le` | `fiable` : score sous le seuil de confiance (0,7, celui de la fiche « Que faire en cas de maladie détectée ? ») → reprendre la photo. |
| 8 | `Regle` | + `derniere_evaluation`, `derniere_decision` | Expliquer à l'exploitant pourquoi la règle arrose ou non (pluie prévue, capteur en panne…). |
| 9 | Pas de 422 sur les lectures | 422 sur toutes les routes à paramètre de chemin ou de requête | FastAPI valide les paramètres (ex. `/parcelles/abc`) et répond 422 au format Problem Details. |
| 10 | Pas de 503 | 503 sur `POST …/commandes`, `POST /diagnostics`, `POST /assistant/questions` | Ces routes dépendent d'un autre service (broker MQTT, service d'inférence, service assistant) qui peut être indisponible. |
