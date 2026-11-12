from typing import Annotated

from fastapi import FastAPI, Query

from app import erreurs
from app.schemas import PageParcelles, Probleme

app = FastAPI(
    title="Jaden Konekté API",
    version="1.0.0",
    description="Suivi des jardins connectés (capteurs, arrosage, diagnostic, assistant).",
)
erreurs.installer(app)

ERREUR_422 = {422: {"model": Probleme, "description": "Données invalides",
                    "content": {"application/problem+json": {}}}}


@app.get(
    "/api/v1/parcelles",
    response_model=PageParcelles,
    summary="Liste de mes parcelles (paginée)",
    tags=["Parcelles"],
    responses=ERREUR_422,
)
async def lister_parcelles(
    page: Annotated[int, Query(ge=1)] = 1,
    taille: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return PageParcelles(elements=[], page=page, taille=taille, total=0)