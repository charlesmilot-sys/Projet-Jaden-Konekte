from typing import Literal
from datetime import datetime
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



# --- Mesures ------------------------------------------------------------------

Grandeur = Literal["humidite", "temperature", "luminosite", "intensite"]
Periode = Literal["24h", "7j"]


class PointMesure(BaseModel):
    debut: datetime
    moyenne: float
    min: float
    max: float
    nombre: int = Field(description="Nombre de mesures valides dans la tranche")


class SerieMesures(BaseModel):
    grandeur: Grandeur
    unite: str = Field(examples=["%"])
    periode: Periode
    intervalle: str = Field(examples=["1 hour"])
    points: list[PointMesure]