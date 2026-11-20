"""Découpe les fiches techniques par section (titres ##) et les range dans la table passage (pgvector).
Chaque passage garde le nom du fichier et le titre de la section : c'est ce qui permet de citer les sources."""
import re
from pathlib import Path

from psycopg import Connection

import embeddings


def decouper(dossier: Path) -> list[dict]:
    passages = []
    for fichier in sorted(dossier.glob("*.md")):
        texte = fichier.read_text(encoding="utf-8")
        titre_fiche = texte.splitlines()[0].lstrip("# ").strip()
        for bloc in re.split(r"^## ", texte, flags=re.MULTILINE)[1:]:   # [0] = titre + avertissement
            section, _, corps = bloc.partition("\n")
            section = section.strip()
            passages.append({
                "source": fichier.name,
                "section": section,
                # Le titre de la fiche est ajouté au texte encodé : « Septoriose » seul ne dit pas « tomate »
                "contenu": f"{titre_fiche} — {section}\n{corps.strip()}",
            })
    return passages


def indexer(conn: Connection, dossier: Path) -> int:
    """Réindexe tout (quelques dizaines de passages : quelques secondes). Idempotent."""
    passages = decouper(dossier)
    vecteurs = embeddings.encoder([p["contenu"] for p in passages])
    with conn.transaction():
        conn.execute("TRUNCATE passage RESTART IDENTITY")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO passage (source, section, contenu, embedding) VALUES (%s, %s, %s, %s::vector)",
                [(p["source"], p["section"], p["contenu"], embeddings.vers_pg(v))
                 for p, v in zip(passages, vecteurs)],
            )
    return len(passages)
