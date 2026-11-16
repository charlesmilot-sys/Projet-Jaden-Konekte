"""Règles de validation des mesures (sans dépendance à MQTT ni à la base : faciles à tester)."""
from dataclasses import dataclass
from datetime import datetime

# Nombre de valeurs plausibles d'affilée pour qu'un capteur suspect redevienne fiable
N_RETABLISSEMENT = 3


@dataclass
class Capteur:
    id: int
    min_valide: float | None
    max_valide: float | None
    baisse_max_min: float | None
    hausse_max_min: float | None


@dataclass
class Etat:
    """Ce que le service retient d'un capteur entre deux messages."""
    derniere_valeur: float | None = None   # dernière mesure VALIDE
    dernier_ts: datetime | None = None     # date de la dernière mesure VALIDE
    dernier_ts_vu: datetime | None = None  # date du dernier message reçu (valide ou non)
    suspect: bool = False
    plausibles_daffilee: int = 0


def dans_les_bornes(capteur: Capteur, valeur: float) -> bool:
    """Règle 1 : bornes plausibles."""
    if capteur.min_valide is not None and valeur < capteur.min_valide:
        return False
    if capteur.max_valide is not None and valeur > capteur.max_valide:
        return False
    return True


def variation_plausible(capteur: Capteur, etat: Etat, valeur: float, ts: datetime) -> bool:
    """Règle 2 : vitesse de variation depuis la dernière mesure valide."""
    if etat.derniere_valeur is None or etat.dernier_ts is None:
        return True  # première mesure : rien à comparer
    minutes = (ts - etat.dernier_ts).total_seconds() / 60
    if minutes <= 0:
        return True
    vitesse = (valeur - etat.derniere_valeur) / minutes  # unités par minute
    if vitesse < 0 and capteur.baisse_max_min is not None and -vitesse > capteur.baisse_max_min:
        return False
    if vitesse > 0 and capteur.hausse_max_min is not None and vitesse > capteur.hausse_max_min:
        return False
    return True


def valider(capteur: Capteur, etat: Etat, valeur: float, ts: datetime) -> bool:
    """Applique les trois règles et met à jour l'état du capteur. Renvoie True si la mesure est valide."""
    plausible = dans_les_bornes(capteur, valeur) and variation_plausible(capteur, etat, valeur, ts)

    if not plausible:
        # Règle 3 : une seule valeur fausse suffit pour rendre le capteur suspect
        etat.suspect = True
        etat.plausibles_daffilee = 0
        return False

    if etat.suspect:
        # Règle 3 : il faut N valeurs plausibles d'affilée pour lui refaire confiance
        etat.plausibles_daffilee += 1
        if etat.plausibles_daffilee < N_RETABLISSEMENT:
            return False
        etat.suspect = False
        etat.plausibles_daffilee = 0

    etat.derniere_valeur = valeur
    etat.dernier_ts = ts
    return True