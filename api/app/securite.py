"""Mots de passe (Argon2), jetons JWT et utilisateur courant."""
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import JWT_DUREE_S, JWT_SECRET
from app.db import pool
from app.schemas import Utilisateur

ALGORITHME = "HS256"
_hacheur = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


# --- Mots de passe ----------------------------------------------------------

def hacher(mot_de_passe: str) -> str:
    return _hacheur.hash(mot_de_passe)


def verifier(mot_de_passe: str, empreinte: str) -> bool:
    try:
        return _hacheur.verify(empreinte, mot_de_passe)
    except (VerifyMismatchError, InvalidHashError):
        return False


# --- Jetons -------------------------------------------------------------------

def creer_jeton(utilisateur_id: int, role: str) -> str:
    maintenant = datetime.now(timezone.utc)
    charge = {
        "sub": str(utilisateur_id),
        "role": role,
        "iat": maintenant,
        "exp": maintenant + timedelta(seconds=JWT_DUREE_S),
    }
    return jwt.encode(charge, JWT_SECRET, algorithm=ALGORITHME)


def _non_authentifie(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


async def utilisateur_courant(
    identifiants: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Utilisateur:
    if identifiants is None:
        raise _non_authentifie("Jeton absent.")
    try:
        charge = jwt.decode(identifiants.credentials, JWT_SECRET, algorithms=[ALGORITHME])
        utilisateur_id = int(charge["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise _non_authentifie("Jeton invalide ou expiré.")

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, prenom, nom, courriel, role FROM utilisateur WHERE id = %s",
            (utilisateur_id,),
        )
        ligne = await cur.fetchone()
    if ligne is None:
        raise _non_authentifie("Utilisateur inconnu.")
    return Utilisateur(**ligne)


UtilisateurCourant = Annotated[Utilisateur, Depends(utilisateur_courant)]