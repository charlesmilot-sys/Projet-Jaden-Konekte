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




# --- Vanne --------------------------------------------------------------------

class Equipement(BaseModel):
    id: int
    type: Literal["vanne"]
    etat: Literal["ouverte", "fermee"]
    jusqua: datetime | None = Field(None, description="Fermeture prévue si la vanne est ouverte")
    derniere_cmd: str | None = Field(None, examples=["cmd-42"])
    en_ligne: bool = Field(description="Dernier statut publié par l'objet (online / offline)")
    maj_le: datetime | None = None


class CommandeEntree(BaseModel):
    action: Literal["ouvrir", "fermer"]
    duree_s: int = Field(600, ge=10, le=3600, description="Utilisée seulement pour « ouvrir »")


class Commande(BaseModel):
    id: str = Field(examples=["cmd-3f2a9c1e5b7d"])
    action: Literal["ouvrir", "fermer"]
    duree_s: int | None = None
    origine: Literal["manuelle", "regle", "agent"]
    statut: Literal["envoyee", "confirmee", "echec"]
    cree_le: datetime




# --- Flux temps réel ------------------------------------------------------------

class ValeurCourante(BaseModel):
    valeur: float
    unite: str
    ts: datetime


class EtatParcelle(BaseModel):
    """Ce que le tableau de bord affiche en direct pour une parcelle."""
    mesures: dict[str, ValeurCourante]   # clé : grandeur (humidite, temperature…)
    vanne: Equipement | None