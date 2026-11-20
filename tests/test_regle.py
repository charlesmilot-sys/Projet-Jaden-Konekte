"""Évaluation de la règle d'arrosage (humidité du sol + prévision de pluie)."""
from conftest import charger

ev = charger("regles/evaluation.py", "evaluation")

REGLE = {"et": [
    {"capteur": "sol/humidite", "op": "<", "valeur": 25},
    {"meteo": "pluie_6h", "op": "<", "valeur": 2},
]}


def test_sol_sec_sans_pluie_arrose():
    declencher, raison = ev.evaluer(REGLE, {"sol/humidite": 20.0}, {"pluie_6h": 0.3})
    assert declencher, raison


def test_sol_humide_n_arrose_pas():
    declencher, _ = ev.evaluer(REGLE, {"sol/humidite": 35.0}, {"pluie_6h": 0.0})
    assert not declencher


def test_pluie_prevue_n_arrose_pas():
    declencher, raison = ev.evaluer(REGLE, {"sol/humidite": 20.0}, {"pluie_6h": 8.0})
    assert not declencher
    assert "inutile" in raison


def test_sans_mesure_valide_n_arrose_pas():
    declencher, raison = ev.evaluer(REGLE, {}, {"pluie_6h": 0.0})
    assert not declencher
    assert "pas de mesure valide" in raison


def test_meteo_indisponible_sol_tres_sec_arrose():
    """Repli : sans météo, on arrose seulement si le sol est 5 points sous le seuil."""
    declencher, raison = ev.evaluer(REGLE, {"sol/humidite": 18.0}, None)
    assert declencher
    assert "précaution" in raison


def test_meteo_indisponible_sol_un_peu_sec_attend():
    declencher, _ = ev.evaluer(REGLE, {"sol/humidite": 22.0}, None)
    assert not declencher
