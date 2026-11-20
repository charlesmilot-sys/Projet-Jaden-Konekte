"""Validation des mesures du sol (service d'ingestion) : bornes, vitesse de variation, hystérésis."""
from datetime import datetime, timedelta

from conftest import charger

v = charger("ingestion/validation.py", "validation")

T0 = datetime(2026, 11, 20, 8, 0)


def capteur_sol():
    # Valeurs de capteurs_test.sql : humidité 5–70 %, baisse max 0,5 %/min, hausse max 2 %/min
    return v.Capteur(id=1, min_valide=5, max_valide=70, baisse_max_min=0.5, hausse_max_min=2)


def test_valeur_normale_acceptee():
    assert v.valider(capteur_sol(), v.Etat(), 35.0, T0)


def test_valeur_hors_bornes_refusee():
    assert not v.valider(capteur_sol(), v.Etat(), 999.0, T0)
    assert not v.valider(capteur_sol(), v.Etat(), 0.0, T0)


def test_chute_brutale_refusee():
    """48 % puis 0,0 % cinq minutes plus tard : un sol ne sèche pas si vite (capteur débranché)."""
    c, e = capteur_sol(), v.Etat()
    assert v.valider(c, e, 48.0, T0)
    assert not v.valider(c, e, 6.0, T0 + timedelta(minutes=5))   # dans les bornes, mais -8,4 %/min


def test_secheresse_lente_acceptee():
    c, e = capteur_sol(), v.Etat()
    assert v.valider(c, e, 40.0, T0)
    assert v.valider(c, e, 38.0, T0 + timedelta(minutes=10))     # -0,2 %/min : plausible


def test_arrosage_rapide_accepte():
    """Variation asymétrique : le sol se mouille bien plus vite qu'il ne sèche."""
    c, e = capteur_sol(), v.Etat()
    assert v.valider(c, e, 20.0, T0)
    assert v.valider(c, e, 35.0, T0 + timedelta(minutes=10))     # +1,5 %/min


def test_hysteresis_trois_valeurs_plausibles():
    """Après une valeur aberrante, il faut 3 valeurs plausibles d'affilée pour refaire confiance."""
    c, e = capteur_sol(), v.Etat()
    assert v.valider(c, e, 40.0, T0)
    assert not v.valider(c, e, 999.0, T0 + timedelta(minutes=1))
    assert e.suspect
    assert not v.valider(c, e, 40.0, T0 + timedelta(minutes=2))
    assert not v.valider(c, e, 40.0, T0 + timedelta(minutes=3))
    assert v.valider(c, e, 40.0, T0 + timedelta(minutes=4))
    assert not e.suspect


def test_valeur_aberrante_ne_remplace_pas_la_derniere_valide():
    c, e = capteur_sol(), v.Etat()
    v.valider(c, e, 40.0, T0)
    v.valider(c, e, 999.0, T0 + timedelta(minutes=1))
    assert e.derniere_valeur == 40.0
