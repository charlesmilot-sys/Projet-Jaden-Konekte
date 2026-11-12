from pydantic import BaseModel, Field


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

class Probleme(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None