"""Assistant agronome : découpage des fiches, requête plein texte, sources citées."""
import os
import sys
import types

from conftest import DEPOT, charger

# Le vrai modèle d'embeddings (fastembed) n'est pas nécessaire ici : on le remplace par un module vide
sys.modules["embeddings"] = types.SimpleNamespace(encoder=None, charger=None, vers_pg=None)
os.environ.setdefault("DATABASE_URL", "postgresql://test@localhost/test")   # le pool n'est pas ouvert

indexation = charger("assistant/indexation.py", "indexation")
service = charger("assistant/service.py", "service_assistant")

FICHES = DEPOT / "ia" / "rag" / "fiches"


def test_decoupage_par_section():
    passages = indexation.decouper(FICHES)
    assert len(passages) == 32
    assert {p["source"] for p in passages} == {f.name for f in FICHES.glob("*.md")}
    mildiou = next(p for p in passages if p["section"] == "Mildiou")
    assert mildiou["source"] == "02_tomate_maladies.md"
    # le titre de la fiche est ajouté au texte : « Mildiou » seul ne dit pas « tomate »
    assert mildiou["contenu"].startswith("Fiche — Tomate : maladies et ravageurs — Mildiou")


def test_requete_plein_texte_en_ou():
    assert service.requete_mots("Comment reconnaître le mildiou ?") == "comment | reconnaître | mildiou"
    assert service.requete_mots("?!") == "rien"


def test_sources_citees():
    passages = [{"source": "a.md", "section": "A"}, {"source": "b.md", "section": "B"}]
    texte = "Réponse [2]. Autre [2][1]. Hors limite [7]."
    assert service.sources_citees(texte, passages) == [
        {"numero": 1, "source": "a.md", "section": "A"},
        {"numero": 2, "source": "b.md", "section": "B"},
    ]


def test_crochets_chinois_normalises():
    assert "Voir 【3】.".translate(service.CROCHETS) == "Voir [3]."
