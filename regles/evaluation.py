"""Évaluation d'une condition de règle (JSON). Fonctions pures : faciles à tester.

Une condition a la forme {"et": [clause, ...]} ; une clause porte soit sur un capteur
({"capteur": "sol/humidite", "op": "<", "valeur": 25}), soit sur la météo
({"meteo": "pluie_6h", "op": "<", "valeur": 2}).
"""
import operator

OPERATEURS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}

# Météo indisponible : on n'arrose que si le sol est franchement sec (seuil moins cette marge)
MARGE_SANS_METEO = 5.0


def comparer(valeur: float | None, op: str, reference: float) -> bool | None:
    """True / False, ou None si la valeur est inconnue."""
    if valeur is None:
        return None
    return OPERATEURS[op](valeur, reference)


def evaluer(condition: dict, mesures: dict[str, float], meteo: dict[str, float] | None) -> tuple[bool, str]:
    """Renvoie (déclencher ?, raison lisible).

    `mesures` : dernière valeur valide par capteur, ex. {"sol/humidite": 22.4}
    `meteo`   : prévisions, ex. {"pluie_6h": 0.3}, ou None si le service météo est indisponible
    """
    clauses = condition.get("et", [])
    raisons = []
    meteo_inconnue = False

    for clause in clauses:
        op, reference = clause["op"], float(clause["valeur"])
        if "capteur" in clause:
            nom = clause["capteur"]
            ok = comparer(mesures.get(nom), op, reference)
            if ok is None:
                return False, f"pas de mesure valide récente pour {nom}"
            if not ok:
                return False, f"{nom} = {mesures[nom]:.1f}, condition {op} {reference:g} non remplie"
            raisons.append(f"{nom} = {mesures[nom]:.1f} {op} {reference:g}")
        else:
            nom = clause["meteo"]
            ok = comparer(meteo.get(nom) if meteo else None, op, reference)
            if ok is None:
                meteo_inconnue = True
                continue
            if not ok:
                return False, f"{nom} = {meteo[nom]:.1f} mm prévus, arrosage inutile"
            raisons.append(f"{nom} = {meteo[nom]:.1f} mm")

    if meteo_inconnue:
        # Repli : sans prévision, on n'arrose que si le sol est nettement plus sec que le seuil
        for clause in clauses:
            if "capteur" in clause and clause["op"] in ("<", "<="):
                limite = float(clause["valeur"]) - MARGE_SANS_METEO
                if mesures[clause["capteur"]] >= limite:
                    return False, (f"météo indisponible et {clause['capteur']} = "
                                   f"{mesures[clause['capteur']]:.1f} ≥ {limite:g} : on attend")
        raisons.append("météo indisponible, sol très sec : arrosage par précaution")

    return True, " ; ".join(raisons)
