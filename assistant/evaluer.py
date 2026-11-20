"""Évaluation de l'assistant sur les 20 questions de référence.

À lancer DANS le conteneur (le service doit tourner) :
    docker compose exec assistant python evaluer.py
puis récupérer le rapport :
    docker compose cp assistant:/tmp/evaluation_rag.md ../ia/rag/evaluation_rag.md

Trois mesures par question :
- recherche : la fiche attendue est-elle parmi les passages retrouvés (rappel@k) ?
- citation  : la réponse cite-t-elle la fiche attendue ?
- éléments  : part des éléments attendus retrouvés dans la réponse (comparaison de mots, indicative :
              la relecture humaine des réponses, jointes au rapport, reste la référence).
"""
import json
import re
import time
import unicodedata

import httpx

URL = "http://localhost:8002"
MOTS_VIDES = {"le", "la", "les", "de", "des", "du", "un", "une", "et", "ou", "au", "aux", "en", "a",
              "pas", "sur", "par", "pour", "l", "d"}


def normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def mots(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-z0-9]+", normaliser(texte)) if m not in MOTS_VIDES and len(m) > 2}


def couverture(attendus: str, reponse: str) -> float:
    elements = [e for e in re.split(r"[,;]", attendus) if e.strip()]
    vus = mots(reponse)
    # Un élément compte s'il partage au moins la moitié de ses mots significatifs avec la réponse
    trouves = sum(1 for e in elements if mots(e) and len(mots(e) & vus) >= len(mots(e)) / 2)
    return trouves / len(elements) if elements else 0.0


def demander(client: httpx.Client, question: str) -> dict:
    texte, fin, erreur, nom = "", {}, None, None
    with client.stream("POST", f"{URL}/questions", json={"question": question}) as r:
        for ligne in r.iter_lines():
            if ligne.startswith("event: "):
                nom = ligne[7:]
            elif ligne.startswith("data: "):
                d = json.loads(ligne[6:])
                if nom == "texte":
                    texte += d["t"]
                elif nom == "fin":
                    fin = d
                elif nom == "erreur":
                    erreur = d["detail"]
    return {"reponse": texte, "erreur": erreur, **fin}


def main():
    questions = json.load(open("questions_reference.json", encoding="utf-8"))
    resultats = []
    with httpx.Client(timeout=120) as client:
        for q in questions:
            trouves = client.post(f"{URL}/recherche", json={"question": q["question"]}).json()
            for essai in range(4):      # quota gratuit atteint : on attend puis on réessaie
                r = demander(client, q["question"])
                if not (r["erreur"] or "").startswith("Quota"):
                    break
                print(f"{q['id']:>2}  quota atteint, nouvel essai dans 30 s…")
                time.sleep(30)
            attendue = q["source_attendue"]
            cites = [s["source"] for s in r.get("sources", [])]
            if attendue is None:     # question hors corpus : l'assistant doit refuser, sans inventer de dose
                ok_recherche = None
                ok_citation = bool(r.get("hors_fiches")) or not re.search(r"\d+\s*(g|ml|l|kg|%)\b", r["reponse"])
                elements = None
            else:
                ok_recherche = attendue in [p["source"] for p in trouves]
                ok_citation = attendue in cites
                elements = couverture(q["elements_attendus"], r["reponse"])
            resultats.append({**q, "passages": trouves, **r, "ok_recherche": ok_recherche,
                              "ok_citation": ok_citation, "couverture": elements})
            print(f"{q['id']:>2}  recherche={ok_recherche}  citation={ok_citation}  "
                  f"elements={elements if elements is None else round(elements, 2)}")
            time.sleep(5)            # reste sous la limite de requêtes de l'offre gratuite

    dans = [r for r in resultats if r["source_attendue"]]
    resume = {
        "rappel_recherche": sum(r["ok_recherche"] for r in dans) / len(dans),
        "citation_correcte": sum(r["ok_citation"] for r in dans) / len(dans),
        "couverture_moyenne": sum(r["couverture"] for r in dans) / len(dans),
        "hors_corpus_ok": all(r["ok_citation"] for r in resultats if not r["source_attendue"]),
        "erreurs": sum(1 for r in resultats if r["erreur"]),
    }
    json.dump({"resume": resume, "resultats": resultats}, open("/tmp/evaluation_rag.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    lignes = ["# Évaluation de l'assistant (20 questions de référence)", "",
              f"- Fiche attendue retrouvée par la recherche : {resume['rappel_recherche']:.0%}",
              f"- Fiche attendue citée dans la réponse : {resume['citation_correcte']:.0%}",
              f"- Éléments attendus présents (indicatif) : {resume['couverture_moyenne']:.0%}",
              f"- Question hors corpus correctement refusée : {'oui' if resume['hors_corpus_ok'] else 'non'}",
              f"- Erreurs : {resume['erreurs']}", "",
              "| # | Question | Fiche attendue | Recherche | Citée | Éléments |", "|---|---|---|---|---|---|"]
    oui = lambda v: "–" if v is None else ("oui" if v else "non")
    for r in resultats:
        el = "–" if r["couverture"] is None else f"{r['couverture']:.0%}"
        lignes.append(f"| {r['id']} | {r['question']} | {r['source_attendue'] or 'hors corpus'} | "
                      f"{oui(r['ok_recherche'])} | {oui(r['ok_citation'])} | {el} |")
    lignes += ["", "## Réponses", ""]
    for r in resultats:
        lignes += [f"**{r['id']}. {r['question']}**", "", r["erreur"] or r["reponse"], ""]
    open("/tmp/evaluation_rag.md", "w", encoding="utf-8").write("\n".join(lignes))
    print(json.dumps(resume, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
