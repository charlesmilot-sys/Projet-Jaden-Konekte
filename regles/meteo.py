"""Prévisions de pluie Open-Meteo (sans clé), avec cache."""
import logging
import time

import httpx

log = logging.getLogger("regles")

URL = "https://api.open-meteo.com/v1/forecast"
DUREE_CACHE_S = 30 * 60        # une prévision est réutilisée pendant 30 min
AGE_MAX_SECOURS_S = 3 * 3600   # si l'API ne répond plus, une prévision de moins de 3 h reste utilisable

# (lat, lon) arrondis -> (horodatage, {"pluie_6h": mm})
_cache: dict[tuple[float, float], tuple[float, dict[str, float]]] = {}


def previsions(lat: float | None, lon: float | None) -> dict[str, float] | None:
    """Cumul de pluie prévu sur les 6 prochaines heures, ou None si indisponible."""
    if lat is None or lon is None:
        return None
    cle = (round(lat, 2), round(lon, 2))
    maintenant = time.time()
    en_cache = _cache.get(cle)
    if en_cache and maintenant - en_cache[0] < DUREE_CACHE_S:
        return en_cache[1]

    try:
        r = httpx.get(URL, params={
            "latitude": cle[0], "longitude": cle[1],
            "hourly": "precipitation", "forecast_hours": 6, "timezone": "GMT",
        }, timeout=5)
        r.raise_for_status()
        pluies = r.json()["hourly"]["precipitation"]
        valeur = {"pluie_6h": round(sum(p or 0 for p in pluies), 1)}
        _cache[cle] = (maintenant, valeur)
        log.info("Météo %s : %.1f mm prévus sur 6 h", cle, valeur["pluie_6h"])
        return valeur
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        if en_cache and maintenant - en_cache[0] < AGE_MAX_SECOURS_S:
            log.warning("Open-Meteo indisponible (%s) : prévision en cache réutilisée", e)
            return en_cache[1]
        log.warning("Open-Meteo indisponible (%s) et pas de prévision récente", e)
        return None
