"""Règle d'arrosage d'une parcelle (une seule par parcelle)."""
from fastapi import APIRouter, HTTPException, Response, status
from psycopg import sql
from psycopg.types.json import Jsonb

from app.acces import parcelle_autorisee
from app.db import pool
from app.erreurs import reponses
from app.schemas import Regle, RegleEntree, RegleModification
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1/parcelles", tags=["Règles"])

COLONNES = "id, parcelle, nom, condition, action, active, delai_min_s, derniere_execution"


def _valeur(champ: str, valeur):
    """Les objets condition et action sont stockés en JSONB."""
    if champ in ("condition", "action"):
        return Jsonb(valeur.model_dump(exclude_none=True))
    return valeur


@router.get(
    "/{id}/regle",
    response_model=Regle,
    summary="Lire la règle d'arrosage de la parcelle",
    responses=reponses(401, 404, 422),
)
async def lire_regle(id: int, utilisateur: UtilisateurCourant):
    async with pool.connection() as conn:
        await parcelle_autorisee(conn, id, utilisateur)
        cur = await conn.execute(f"SELECT {COLONNES} FROM regle WHERE parcelle = %s", (id,))
        regle = await cur.fetchone()
    if regle is None:
        raise HTTPException(404, f"La parcelle {id} n'a pas encore de règle d'arrosage.")
    return regle


@router.put(
    "/{id}/regle",
    response_model=Regle,
    summary="Créer ou remplacer la règle d'arrosage",
    responses={201: {"description": "Règle créée", "model": Regle}, **reponses(401, 404, 422)},
)
async def remplacer_regle(id: int, donnees: RegleEntree, utilisateur: UtilisateurCourant, response: Response):
    async with pool.connection() as conn:
        await parcelle_autorisee(conn, id, utilisateur)
        cur = await conn.execute(
            f"""
            INSERT INTO regle (parcelle, nom, condition, action, active, delai_min_s)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (parcelle) DO UPDATE SET
                nom = EXCLUDED.nom, condition = EXCLUDED.condition, action = EXCLUDED.action,
                active = EXCLUDED.active, delai_min_s = EXCLUDED.delai_min_s
            RETURNING {COLONNES}, (xmax = 0) AS creee
            """,
            (id, donnees.nom, _valeur("condition", donnees.condition), _valeur("action", donnees.action),
             donnees.active, donnees.delai_min_s),
        )
        regle = await cur.fetchone()
    # xmax = 0 : la ligne vient d'être insérée (201) ; sinon elle a été remplacée (200)
    response.status_code = status.HTTP_201_CREATED if regle.pop("creee") else status.HTTP_200_OK
    return regle


@router.patch(
    "/{id}/regle",
    response_model=Regle,
    summary="Modifier une partie de la règle (seuil, durée, activation…)",
    responses=reponses(401, 404, 422),
)
async def modifier_regle(id: int, donnees: RegleModification, utilisateur: UtilisateurCourant):
    champs = sorted(donnees.model_fields_set)
    affectations = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(champ)) for champ in champs
    )
    valeurs = [_valeur(champ, getattr(donnees, champ)) for champ in champs]
    async with pool.connection() as conn:
        await parcelle_autorisee(conn, id, utilisateur)
        cur = await conn.execute(
            sql.SQL("UPDATE regle SET {} WHERE parcelle = %s RETURNING " + COLONNES).format(affectations),
            (*valeurs, id),
        )
        regle = await cur.fetchone()
    if regle is None:
        raise HTTPException(404, f"La parcelle {id} n'a pas encore de règle d'arrosage.")
    return regle
