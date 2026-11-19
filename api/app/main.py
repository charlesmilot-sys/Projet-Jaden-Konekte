from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import erreurs, mqtt
from app.db import pool
from app.routes import auth, diagnostics, flux, mesures, parcelles, regles, vanne


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    await pool.open()
    mqtt.demarrer()
    yield
    mqtt.arreter()
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
app.include_router(vanne.router)
app.include_router(regles.router)
app.include_router(flux.router)
app.include_router(diagnostics.router)

# Le tableau de bord (HTML, CSS, JS) est servi par l'API elle-même : même origine, pas de CORS.
# Monté en dernier : les routes /api/... restent prioritaires.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True), name="tableau")
