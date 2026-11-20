"""Le contrat openapi.yaml et la spécification générée par FastAPI décrivent exactement la même API :
mêmes routes, mêmes méthodes, mêmes codes de réponse. Ignoré si l'API ne répond pas."""
import os

import httpx
import pytest
import yaml

from conftest import DEPOT

BASE = os.environ.get("API_URL", "http://localhost:8000")
METHODES = {"get", "post", "put", "patch", "delete"}

try:
    GENERE = httpx.get(BASE + "/openapi.json", timeout=3).json()
except httpx.HTTPError:
    GENERE = None

pytestmark = pytest.mark.skipif(GENERE is None, reason="API non démarrée")


def operations(spec: dict) -> dict:
    return {(chemin, m): {str(c) for c in op.get("responses", {})}
            for chemin, d in spec["paths"].items() for m, op in d.items() if m in METHODES}


@pytest.fixture(scope="module")
def contrat():
    return yaml.safe_load((DEPOT / "openapi.yaml").read_text(encoding="utf-8"))


def test_memes_routes(contrat):
    c, g = operations(contrat), operations(GENERE)
    assert c.keys() - g.keys() == set(), "routes du contrat non implémentées"
    assert g.keys() - c.keys() == set(), "routes implémentées absentes du contrat"


def test_memes_codes_de_reponse(contrat):
    c, g = operations(contrat), operations(GENERE)
    differences = {k: (sorted(c[k]), sorted(g[k])) for k in c.keys() & g.keys() if c[k] != g[k]}
    assert differences == {}
