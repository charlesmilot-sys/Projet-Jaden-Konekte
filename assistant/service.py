"""Service de l'assistant agronome (RAG) : question -> passages des fiches -> réponse de Groq, en streaming SSE.

Service séparé, sans port publié : seule l'API (qui vérifie le jeton JWT) peut l'appeler.
Au démarrage : chargement du modèle d'embeddings, puis réindexation des fiches (la base reste synchronisée
avec le dossier des fiches)."""
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

import embeddings
import indexation
import llm

DATABASE_URL = os.environ["DATABASE_URL"]
DOSSIER_FICHES = Path(os.environ.get("DOSSIER_FICHES", "/fiches"))
NB_PASSAGES = int(os.environ.get("NB_PASSAGES", "6"))
# Sous cette similarité, aucun passage ne parle de la question : on n'appelle même pas le LLM
SEUIL_SIMILARITE = float(os.environ.get("SEUIL_SIMILARITE", "0.15"))

pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=False,
                           kwargs={"row_factory": dict_row})
etat: dict = {}


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    embeddings.charger()
    with Connection.connect(DATABASE_URL) as conn:
        etat["passages"] = indexation.indexer(conn, DOSSIER_FICHES)
    await pool.open()
    yield
    await pool.close()


app = FastAPI(title="Jaden Konekté — assistant agronome", version="1.0.0", lifespan=cycle_de_vie)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def requete_mots(question: str) -> str:
    """« Comment reconnaître le mildiou ? » -> 'comment | reconnaître | mildiou' (OU logique).
    Le dictionnaire français de PostgreSQL retire ensuite les mots vides et réduit chaque mot à sa racine."""
    return " | ".join(re.findall(r"\w{3,}", question.lower())) or "rien"


async def rechercher(question: str, k: int = NB_PASSAGES) -> list[dict]:
    """Recherche HYBRIDE : sens (embeddings, pgvector) + mots exacts (recherche plein texte de PostgreSQL).

    Les embeddings trouvent les passages qui parlent de la même chose avec d'autres mots ; la recherche
    plein texte rattrape les termes précis (« mildiou », « igname ») que le petit modèle d'embeddings
    représente mal. Les deux classements sont fusionnés par Reciprocal Rank Fusion :
    score = 1/(60 + rang_sens) + 1/(60 + rang_mots)."""
    vecteur = embeddings.vers_pg((await run_in_threadpool(embeddings.encoder, [question]))[0])
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            WITH sens AS (
                SELECT id, 1 - (embedding <=> %(v)s::vector) AS similarite,
                       row_number() OVER (ORDER BY embedding <=> %(v)s::vector) AS rang
                FROM passage
            ),
            mots AS (
                SELECT id, row_number() OVER (ORDER BY ts_rank(to_tsvector('french', contenu), q) DESC) AS rang
                FROM passage, to_tsquery('french', %(mots)s) AS q
                WHERE to_tsvector('french', contenu) @@ q
            )
            SELECT p.source, p.section, p.contenu, s.similarite,
                   1.0 / (60 + s.rang) + COALESCE(1.0 / (60 + m.rang), 0) AS score
            FROM passage p
            JOIN sens s ON s.id = p.id
            LEFT JOIN mots m ON m.id = p.id
            ORDER BY score DESC
            LIMIT %(k)s
            """,
            {"v": vecteur, "mots": requete_mots(question), "k": k},
        )
        return await cur.fetchall()


def evenement(nom: str, donnees: dict) -> str:
    return f"event: {nom}\ndata: {json.dumps(donnees, ensure_ascii=False)}\n\n"


CROCHETS = str.maketrans({"【": "[", "】": "]"})


def sources_citees(texte: str, passages: list[dict]) -> list[dict]:
    numeros = sorted({int(n) for n in re.findall(r"\[(\d+)\]", texte) if 1 <= int(n) <= len(passages)})
    return [{"numero": n, "source": passages[n - 1]["source"], "section": passages[n - 1]["section"]}
            for n in numeros]


async def generer(question: str):
    passages = await rechercher(question)
    texte = ""
    try:
        if not passages or max(p["similarite"] for p in passages) < SEUIL_SIMILARITE:
            texte = llm.PHRASE_HORS_FICHES
            yield evenement("texte", {"t": texte})
        else:
            async for morceau in llm.repondre(question, passages):
                # gpt-oss écrit parfois ses citations 【1】 (crochets chinois) : on les ramène à [1]
                morceau = morceau.translate(CROCHETS)
                texte += morceau
                yield evenement("texte", {"t": morceau})
    except llm.ErreurLLM as e:
        yield evenement("erreur", {"detail": str(e)})
        return
    except Exception:
        yield evenement("erreur", {"detail": "L'assistant n'a pas pu répondre, réessayez plus tard."})
        return
    hors_fiches = llm.PHRASE_HORS_FICHES in texte
    yield evenement("fin", {
        "hors_fiches": hors_fiches,
        "sources": [] if hors_fiches else sources_citees(texte, passages),
        "modele": llm.MODELE,
    })


@app.get("/sante")
def sante():
    return {"statut": "ok", "passages": etat.get("passages"), "modele": llm.MODELE}


@app.post("/questions")
async def poser_question(q: Question):
    return StreamingResponse(generer(q.question), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.post("/recherche")
async def recherche(q: Question):
    """Pour l'évaluation : les passages trouvés, sans appeler le LLM."""
    return [{k: (float(v) if k == "score" else v) for k, v in p.items() if k != "contenu"}
            for p in await rechercher(q.question)]
