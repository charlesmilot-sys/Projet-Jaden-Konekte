"""Appel du LLM chez Groq (API compatible OpenAI), en streaming. La clé reste dans ce service, jamais côté client."""
import json
import os
from collections.abc import AsyncIterator

import httpx

URL = "https://api.groq.com/openai/v1/chat/completions"
CLE = os.environ.get("GROQ_API_KEY", "")
MODELE = os.environ.get("GROQ_MODELE", "openai/gpt-oss-120b")

PHRASE_HORS_FICHES = "Je ne trouve pas cette information dans les fiches techniques."

CONSIGNES = f"""Tu es l'assistant agronome de Jaden Konekté, une plateforme de jardins connectés pour de petits exploitants des Antilles.
Règles :
- Réponds en français simple, en 2 à 6 phrases, UNIQUEMENT à partir des extraits numérotés fournis.
- Après chaque information, indique entre crochets le numéro de l'extrait utilisé, par exemple [2].
- Si les extraits ne permettent pas de répondre, réponds exactement : « {PHRASE_HORS_FICHES} » puis, en une phrase, oriente vers un technicien ou un conseiller agricole.
- Ne donne jamais de dose de produit de traitement, même si on te la demande.
- N'invente rien et n'utilise pas tes connaissances générales."""


class ErreurLLM(Exception):
    pass


def construire_messages(question: str, passages: list[dict]) -> list[dict]:
    extraits = "\n\n".join(
        f"[{i}] ({p['source']} — {p['section']})\n{p['contenu']}" for i, p in enumerate(passages, 1)
    )
    return [
        {"role": "system", "content": CONSIGNES},
        {"role": "user", "content": f"Extraits :\n\n{extraits}\n\nQuestion : {question}"},
    ]


async def repondre(question: str, passages: list[dict]) -> AsyncIterator[str]:
    """Renvoie la réponse morceau par morceau, au fil de sa génération."""
    corps = {
        "model": MODELE,
        "messages": construire_messages(question, passages),
        "temperature": 0.2,
        "max_completion_tokens": 1024,
        "reasoning_effort": "low",     # gpt-oss réfléchit avant de répondre : on limite cette réflexion
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
        async with client.stream("POST", URL, json=corps,
                                 headers={"Authorization": f"Bearer {CLE}"}) as r:
            if r.status_code == 401:
                raise ErreurLLM("Clé Groq refusée : vérifiez GROQ_API_KEY dans infra/.env.")
            if r.status_code == 429:
                raise ErreurLLM("Quota gratuit de Groq atteint : réessayez dans une minute.")
            if r.status_code != 200:
                detail = (await r.aread()).decode(errors="replace")[:300]
                raise ErreurLLM(f"Groq a répondu {r.status_code} : {detail}")
            # Format reçu : des lignes « data: {...} », terminées par « data: [DONE] »
            async for ligne in r.aiter_lines():
                if not ligne.startswith("data: "):
                    continue
                donnees = ligne.removeprefix("data: ")
                if donnees == "[DONE]":
                    break
                delta = json.loads(donnees)["choices"][0]["delta"]
                if delta.get("content"):       # on ignore le raisonnement interne du modèle
                    yield delta["content"]
