from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class Probleme(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None


# --- Authentification -------------------------------------------------------

class Inscription(BaseModel):
    prenom: str = Field(min_length=1, max_length=40)
    nom: str = Field(min_length=1, max_length=40)
    courriel: EmailStr = Field(max_length=120)
    mot_de_passe: str = Field(min_length=8, max_length=128)


class Connexion(BaseModel):
    courriel: EmailStr
    mot_de_passe: str


class Jeton(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class Utilisateur(BaseModel):
    id: int
    prenom: str
    nom: str
    courriel: EmailStr
    role: Literal["exploitant", "administrateur"]


# --- Parcelles ----------------------------------------------------------------

class Parcelle(BaseModel):
    id: int
    code: str = Field(examples=["p1"])
    nom: str = Field(examples=["Carré de tomates"])
    culture: str = Field(examples=["tomate"])
    surface_m2: float | None = None


class PageParcelles(BaseModel):
    elements: list[Parcelle]
    page: int
    taille: int
    total: int