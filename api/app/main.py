import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import erreurs, mqtt, provision
from app.amorcage import amorcer
from app.db import pool
from app.routes import apercu, assistant, auth, diagnostics, flux, mesures, parcelles, regles, vanne


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    await pool.open()
    await amorcer()
    mqtt.demarrer()
    annonce = asyncio.create_task(provision.annoncer_toutes())   # en arrière-plan : n'attend pas le broker
    yield
    annonce.cancel()
    mqtt.arreter()
    await pool.close()


app = FastAPI(
    title="Jaden Konekté API",
    version="1.0.0",
    description="Suivi des jardins connectés (capteurs, arrosage, diagnostic, assistant).",
    lifespan=cycle_de_vie,
)
erreurs.installer(app)


@app.middleware("http")
async def toujours_verifier(request, call_next):
    """Interface : le navigateur revérifie chaque fichier (réponse 304 s'il n'a pas changé),
    pour ne jamais garder une ancienne version de la page, du CSS ou du JavaScript."""
    reponse = await call_next(request)
    if not request.url.path.startswith("/api/"):
        reponse.headers["Cache-Control"] = "no-cache"
    return reponse

app.include_router(auth.router)
app.include_router(parcelles.router)
app.include_router(mesures.router)
app.include_router(vanne.router)
app.include_router(regles.router)
app.include_router(flux.router)
app.include_router(apercu.router)
app.include_router(diagnostics.router)
app.include_router(assistant.router)

# Le tableau de bord (HTML, CSS, JS) est servi par l'API elle-même : même origine, pas de CORS.
# Monté en dernier : les routes /api/... restent prioritaires.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True), name="tableau")
