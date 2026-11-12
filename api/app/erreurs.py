"""Erreurs au format Problem Details (RFC 9457)."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas import Probleme

TYPE_BASE = "https://jaden-konekte.example/erreurs/"

TITRES = {
    401: ("non-authentifie", "Authentification requise"),
    403: ("interdit", "Accès refusé"),
    404: ("introuvable", "Ressource introuvable"),
    409: ("conflit", "Conflit avec l'état actuel"),
    413: ("trop-volumineux", "Contenu trop volumineux"),
    415: ("format-non-supporte", "Format non pris en charge"),
    422: ("donnees-invalides", "Données invalides"),
    503: ("service-indisponible", "Service indisponible"),
}


def probleme(status: int, detail: str | None = None, **extra) -> JSONResponse:
    code, titre = TITRES.get(status, ("erreur", "Erreur"))
    corps = Probleme(type=TYPE_BASE + code, title=titre, status=status, detail=detail)
    return JSONResponse(
        status_code=status,
        content={**corps.model_dump(), **extra},
        media_type="application/problem+json",
    )


def installer(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def erreur_http(request: Request, exc: StarletteHTTPException):
        return probleme(exc.status_code, str(exc.detail) if exc.detail else None)

    @app.exception_handler(RequestValidationError)
    async def erreur_validation(request: Request, exc: RequestValidationError):
        erreurs = [
            {"champ": ".".join(str(x) for x in e["loc"]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return probleme(422, "La requête contient des valeurs invalides.", erreurs=erreurs)