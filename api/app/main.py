from contextlib import asynccontextmanager
from fastapi import FastAPI
from app import erreurs
from app.db import pool
from app.routes import auth, mesures, parcelles


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

app.include_router(auth.router)
app.include_router(parcelles.router)
app.include_router(mesures.router)