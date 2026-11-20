from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


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
    valeur: float = Field(description="Dernière valeur VALIDE")
    unite: str
    ts: datetime
    fiable: bool = Field(True, description="False si la dernière mesure reçue a été rejetée "
                                           "(capteur en panne) : la valeur affichée est alors ancienne")


class EtatParcelle(BaseModel):
    """Ce que le tableau de bord affiche en direct pour une parcelle."""
    mesures: dict[str, ValeurCourante]   # clé : grandeur (humidite, temperature…)
    vanne: Equipement | None


# --- Règle d'arrosage -------------------------------------------------------------

class Clause(BaseModel):
    capteur: Literal["sol/humidite", "air/temperature", "air/luminosite", "pluvio/intensite"] | None = None
    meteo: Literal["pluie_6h"] | None = None
    op: Literal["<", "<=", ">", ">="]
    valeur: float

    @model_validator(mode="after")
    def une_seule_source(self):
        if (self.capteur is None) == (self.meteo is None):
            raise ValueError("une clause porte soit sur un capteur, soit sur la météo")
        return self


class Condition(BaseModel):
    et: list[Clause] = Field(min_length=1)


class Action(BaseModel):
    equipement: Literal["vanne"] = "vanne"
    action: Literal["ouvrir"] = "ouvrir"
    duree_s: int = Field(600, ge=10, le=3600)


class RegleEntree(BaseModel):
    nom: str = Field(min_length=1, max_length=80)
    condition: Condition
    action: Action
    active: bool = True
    delai_min_s: int = Field(7200, ge=0)


class RegleModification(BaseModel):
    """Seuls les champs envoyés sont modifiés."""
    nom: str | None = Field(None, min_length=1, max_length=80)
    condition: Condition | None = None
    action: Action | None = None
    active: bool | None = None
    delai_min_s: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def au_moins_un_champ(self):
        if not self.model_fields_set:
            raise ValueError("indiquez au moins un champ à modifier")
        for champ in self.model_fields_set:
            if getattr(self, champ) is None:
                raise ValueError(f"le champ {champ} ne peut pas être null")
        return self


class Regle(BaseModel):
    id: int
    parcelle: int
    nom: str
    condition: Condition
    action: Action
    active: bool
    delai_min_s: int
    derniere_execution: datetime | None = None


# --- Diagnostics ----------------------------------------------------------------

class Diagnostic(BaseModel):
    id: int
    parcelle: int | None = None
    classe: str | None = Field(default=None, examples=["Tomato___Late_blight"])
    libelle: str | None = Field(default=None, description="Nom de la maladie en français",
                                examples=["Mildiou"])
    score: float | None = Field(default=None, ge=0, le=1, examples=[0.94])
    fiable: bool | None = Field(default=None,
                                description="Score au-dessus du seuil de confiance ; "
                                            "sinon il faut reprendre la photo")
    modele: str | None = Field(default=None, examples=["mobilenetv3-tomate-v1"])
    statut: Literal["en_cours", "termine", "echec"]
    image_url: str
    confirme: bool | None = Field(default=None,
                                  description="Validation par l'exploitant (null tant qu'il n'a pas répondu)")
    cree_le: datetime
    termine_le: datetime | None = None


class PageDiagnostics(BaseModel):
    elements: list[Diagnostic]
    page: int
    taille: int
    total: int


class Confirmation(BaseModel):
    confirme: bool


# --- Assistant agronome ----------------------------------------------------------

class QuestionAssistant(BaseModel):
    question: str = Field(min_length=3, max_length=500,
                          examples=["Comment reconnaître le mildiou sur la tomate ?"])
