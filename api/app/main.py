from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query

from app import erreurs
from app.db import pool
from app.schemas import PageParcelles, Probleme


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    await pool.open()
    yield
    await pool.close()


app = FastAPI(
    title="Jaden Konekté API",
    version="1.0.0",
    description="Suivi des jardins connectés (capteurs, arrosage, diagnostic, assistant).",
    lifespan=cycle_de_vie,
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
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS total FROM parcelle")
        total = (await cur.fetchone())["total"]
        cur = await conn.execute(
            """
            SELECT id, code, nom, culture, surface_m2
            FROM parcelle
            ORDER BY id
            LIMIT %s OFFSET %s
            """,
            (taille, (page - 1) * taille),
        )
        lignes = await cur.fetchall()
    return PageParcelles(elements=lignes, page=page, taille=taille, total=total)