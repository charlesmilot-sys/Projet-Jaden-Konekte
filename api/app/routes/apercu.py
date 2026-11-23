"""Vue d'ensemble : l'état de toutes mes parcelles en un seul appel (haut du tableau de bord)."""
from fastapi import APIRouter

from app.db import pool
from app.erreurs import reponses
from app.schemas import ApercuParcelle
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1", tags=["Tableau de bord"])

REQUETE = """
SELECT p.id, p.code, p.nom, p.culture,
       h.valeur AS humidite, h.ts AS humidite_ts, d.valide AS humidite_fiable,
       -- seuil d'arrosage : la clause « sol/humidite » de la règle, s'il y en a une
       (SELECT (cl->>'valeur')::float FROM jsonb_array_elements(r.condition->'et') cl
         WHERE cl->>'capteur' = 'sol/humidite' LIMIT 1) AS seuil,
       r.active AS regle_active, r.derniere_decision,
       v.etat AS vanne_etat, v.jusqua AS vanne_jusqua, coalesce(v.en_ligne, false) AS en_ligne,
       (SELECT count(*) FROM commande c
         WHERE c.equipement = v.id AND c.action = 'ouvrir' AND c.statut = 'confirmee'
           AND c.cree_le > now() - interval '24 hours') AS arrosages_24h,
       (SELECT max(c.cree_le) FROM commande c
         WHERE c.equipement = v.id AND c.action = 'ouvrir' AND c.statut = 'confirmee') AS dernier_arrosage
FROM parcelle p
JOIN exploitation e ON e.id = p.exploitation
LEFT JOIN LATERAL (
    SELECT id FROM capteur WHERE parcelle = p.id AND grandeur = 'humidite' AND actif ORDER BY id LIMIT 1
) cs ON true
-- dernière mesure VALIDE (la valeur affichée) et dernière mesure reçue (panne si invalide)
LEFT JOIN LATERAL (
    SELECT valeur, ts FROM mesure WHERE capteur = cs.id AND valide ORDER BY ts DESC LIMIT 1
) h ON true
LEFT JOIN LATERAL (
    SELECT valide FROM mesure WHERE capteur = cs.id ORDER BY ts DESC LIMIT 1
) d ON true
LEFT JOIN regle r ON r.parcelle = p.id
LEFT JOIN equipement v ON v.parcelle = p.id AND v.type = 'vanne'
WHERE (%(admin)s OR e.proprietaire = %(uid)s)
ORDER BY p.id
"""


@router.get(
    "/apercu",
    response_model=list[ApercuParcelle],
    summary="Vue d'ensemble de mes parcelles (humidité, seuil, vanne, arrosages des dernières 24 h)",
    responses=reponses(401, 422),
)
async def apercu(utilisateur: UtilisateurCourant):
    async with pool.connection() as conn:
        cur = await conn.execute(
            REQUETE, {"admin": utilisateur.role == "administrateur", "uid": utilisateur.id}
        )
        return await cur.fetchall()
