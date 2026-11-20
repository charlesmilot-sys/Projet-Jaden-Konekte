"""Assistant agronome : l'API vérifie le jeton, puis relaie la réponse du service assistant au fil de l'eau.
La clé Groq n'est connue que du service assistant ; le navigateur ne la voit jamais."""
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import ASSISTANT_URL
from app.erreurs import reponses
from app.schemas import QuestionAssistant
from app.securite import UtilisateurCourant

router = APIRouter(prefix="/api/v1/assistant", tags=["Assistant"])


@router.post(
    "/questions",
    summary="Poser une question à l'assistant agronome (réponse en streaming SSE)",
    description="Flux `text/event-stream` : des événements `texte` ({\"t\": morceau}), puis `fin` "
                "({\"hors_fiches\", \"sources\": [{numero, source, section}], \"modele\"}) "
                "ou `erreur` ({\"detail\"}). La réponse s'appuie uniquement sur les fiches techniques.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}, **reponses(401, 422, 503)},
)
async def poser_question(donnees: QuestionAssistant, utilisateur: UtilisateurCourant):
    client = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5))
    try:
        requete = client.build_request("POST", f"{ASSISTANT_URL}/questions", json=donnees.model_dump())
        reponse = await client.send(requete, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(503, "L'assistant ne répond pas, réessayez plus tard.")
    if reponse.status_code != 200:
        await reponse.aclose()
        await client.aclose()
        raise HTTPException(503, "L'assistant n'a pas pu traiter la question.")

    async def relayer():
        try:
            async for morceau in reponse.aiter_raw():
                yield morceau
        finally:
            await reponse.aclose()
            await client.aclose()

    return StreamingResponse(relayer(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
