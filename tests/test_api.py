"""Tests de bout en bout sur l'API en marche (docker compose up) : authentification, accès, erreurs.
Ignorés automatiquement si l'API ne répond pas."""
import io
import os
import uuid

import httpx
import pytest
from PIL import Image

API = os.environ.get("API_URL", "http://localhost:8000") + "/api/v1"

try:
    httpx.get(API.removesuffix("/api/v1") + "/docs", timeout=3)
    API_DISPONIBLE = True
except httpx.HTTPError:
    API_DISPONIBLE = False

pytestmark = pytest.mark.skipif(not API_DISPONIBLE, reason="API non démarrée")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=API, timeout=20) as c:
        yield c


@pytest.fixture(scope="module")
def compte(client):
    """Un nouvel exploitant, sans parcelle."""
    courriel = f"test-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/utilisateurs", json={"prenom": "Test", "nom": "Auto",
                                           "courriel": courriel, "mot_de_passe": "motdepasse-test"})
    assert r.status_code == 201
    jeton = client.post("/jetons", json={"courriel": courriel, "mot_de_passe": "motdepasse-test"}).json()
    return {"courriel": courriel, "entetes": {"Authorization": f"Bearer {jeton['access_token']}"}}


def test_inscription_courriel_deja_pris(client, compte):
    r = client.post("/utilisateurs", json={"prenom": "X", "nom": "Y", "courriel": compte["courriel"],
                                           "mot_de_passe": "autre-motdepasse"})
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


def test_mot_de_passe_trop_court(client):
    r = client.post("/utilisateurs", json={"prenom": "X", "nom": "Y", "courriel": "court@exemple.fr",
                                           "mot_de_passe": "court"})
    assert r.status_code == 422


def test_mauvais_mot_de_passe(client, compte):
    r = client.post("/jetons", json={"courriel": compte["courriel"], "mot_de_passe": "pas-le-bon"})
    assert r.status_code == 401


def test_profil(client, compte):
    r = client.get("/utilisateurs/moi", headers=compte["entetes"])
    assert r.status_code == 200
    assert r.json()["role"] == "exploitant"


@pytest.mark.parametrize("entetes", [{}, {"Authorization": "Bearer jeton.invente.xyz"}])
def test_sans_jeton_valide(client, entetes):
    assert client.get("/parcelles", headers=entetes).status_code == 401


def test_nouvel_exploitant_ne_voit_aucune_parcelle(client, compte):
    r = client.get("/parcelles", headers=compte["entetes"])
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_apercu_limite_a_mes_parcelles(client, compte):
    """La vue d'ensemble ne montre que les parcelles de l'utilisateur : aucune pour un nouveau compte."""
    r = client.get("/apercu", headers=compte["entetes"])
    assert r.status_code == 200
    assert r.json() == []
    assert client.get("/apercu").status_code == 401


def test_administration_reservee_a_l_admin(client, compte):
    """Un exploitant ne peut ni créer, ni attribuer une parcelle, ni lister les comptes : 403."""
    e = compte["entetes"]
    assert client.get("/utilisateurs", headers=e).status_code == 403
    r = client.post("/parcelles", headers=e, json={"proprietaire": 1, "nom": "Essai", "culture": "piment"})
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert client.patch("/parcelles/1", headers=e, json={"proprietaire": 1}).status_code == 403


def test_parcelle_d_un_autre_introuvable(client, compte):
    """Contrôle d'accès au niveau objet : 404 (et non 403) pour ne pas révéler son existence."""
    for chemin in ["/parcelles/1", "/parcelles/1/mesures?grandeur=humidite", "/parcelles/1/equipements",
                   "/parcelles/1/regle", "/parcelles/1/commandes"]:
        assert client.get(chemin, headers=compte["entetes"]).status_code == 404, chemin
    r = client.post("/parcelles/1/commandes", headers=compte["entetes"], json={"action": "fermer"})
    assert r.status_code == 404


def test_diagnostic_format_refuse(client, compte):
    r = client.post("/diagnostics", headers=compte["entetes"],
                    files={"image": ("faux.jpg", b"GIF89a pas une photo", "image/jpeg")})
    assert r.status_code == 415


def test_diagnostic_trop_volumineux(client, compte):
    r = client.post("/diagnostics", headers=compte["entetes"],
                    files={"image": ("gros.jpg", b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024), "image/jpeg")})
    assert r.status_code == 413


def test_diagnostic_parcelle_d_un_autre(client, compte):
    b = io.BytesIO()
    Image.new("RGB", (300, 300), (40, 160, 40)).save(b, "JPEG")
    r = client.post("/diagnostics", headers=compte["entetes"], data={"parcelle": "1"},
                    files={"image": ("f.jpg", b.getvalue(), "image/jpeg")})
    assert r.status_code == 404


def test_diagnostic_complet(client, compte):
    b = io.BytesIO()
    Image.new("RGB", (300, 300), (40, 160, 40)).save(b, "JPEG")
    r = client.post("/diagnostics", headers=compte["entetes"],
                    files={"image": ("f.jpg", b.getvalue(), "image/jpeg")})
    assert r.status_code == 201
    d = r.json()
    assert d["statut"] == "termine" and 0 <= d["score"] <= 1
    assert d["fiable"] is False                     # une image unie n'est pas une feuille
    r = client.patch(f"/diagnostics/{d['id']}", headers=compte["entetes"], json={"confirme": False})
    assert r.json()["confirme"] is False


def test_question_assistant_trop_courte(client, compte):
    r = client.post("/assistant/questions", headers=compte["entetes"], json={"question": "?"})
    assert r.status_code == 422
