"""Inscription, connexion et profil."""
from fastapi import APIRouter, HTTPException, status
from psycopg.errors import UniqueViolation

from app.config import JWT_DUREE_S
from app.db import pool
from app.erreurs import reponses
from app.schemas import Connexion, Inscription, Jeton, Utilisateur
from app.securite import UtilisateurCourant, creer_jeton, hacher, verifier

router = APIRouter(prefix="/api/v1", tags=["Authentification"])


@router.post(
    "/utilisateurs",
    response_model=Utilisateur,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription (crée un exploitant)",
    responses=reponses(409, 422),
)
async def inscrire(donnees: Inscription):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO utilisateur (prenom, nom, courriel, mot_de_passe, role)
                VALUES (%s, %s, %s, %s, 'exploitant')
                RETURNING id, prenom, nom, courriel, role
                """,
                (donnees.prenom, donnees.nom, donnees.courriel.lower(), hacher(donnees.mot_de_passe)),
            )
            ligne = await cur.fetchone()
    except UniqueViolation:
        raise HTTPException(409, "Ce courriel est déjà utilisé.")
    return ligne


@router.get(
    "/utilisateurs",
    response_model=list[Utilisateur],
    summary="Liste des comptes (administrateur)",
    responses=reponses(401, 403),
)
async def lister_utilisateurs(utilisateur: UtilisateurCourant):
    if utilisateur.role != "administrateur":
        raise HTTPException(403, "Réservé à l'administrateur.")
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, prenom, nom, courriel, role FROM utilisateur ORDER BY role DESC, nom, prenom"
        )
        return await cur.fetchall()


@router.post(
    "/jetons",
    response_model=Jeton,
    summary="Connexion",
    responses=reponses(401, 422),
)
async def connecter(donnees: Connexion):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, role, mot_de_passe FROM utilisateur WHERE courriel = %s",
            (donnees.courriel.lower(),),
        )
        ligne = await cur.fetchone()
    if ligne is None or not verifier(donnees.mot_de_passe, ligne["mot_de_passe"]):
        raise HTTPException(401, "Courriel ou mot de passe incorrect.")
    return Jeton(access_token=creer_jeton(ligne["id"], ligne["role"]), expires_in=JWT_DUREE_S)


@router.get(
    "/utilisateurs/moi",
    response_model=Utilisateur,
    summary="Profil de l'utilisateur connecté",
    responses=reponses(401),
)
async def moi(utilisateur: UtilisateurCourant):
    return utilisateur