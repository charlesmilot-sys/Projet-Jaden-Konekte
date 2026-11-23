"""Parcelles : chaque exploitant ne voit que les siennes (contrôle d'accès au niveau objet).
Seul l'administrateur crée une parcelle et l'attribue à un exploitant."""
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from psycopg import AsyncConnection

from app import provision
from app.db import pool
from app.erreurs import reponses
from app.schemas import Attribution, PageParcelles, Parcelle, ParcelleEntree, Utilisateur
from app.securite import UtilisateurCourant

log = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/v1/parcelles", tags=["Parcelles"])

# Un administrateur voit tout ; un exploitant, seulement les parcelles de ses exploitations.
COLONNES = """p.id, p.code, p.nom, p.culture, p.surface_m2,
              e.proprietaire, u.prenom || ' ' || u.nom AS proprietaire_nom"""
FILTRE_PROPRIETAIRE = """
    FROM parcelle p
    JOIN exploitation e ON e.id = p.exploitation
    JOIN utilisateur u ON u.id = e.proprietaire
    WHERE (%(admin)s OR e.proprietaire = %(uid)s)
"""

# Coordonnées par défaut d'une nouvelle exploitation (centre de la Guadeloupe), pour la météo de la règle
LAT_DEFAUT, LON_DEFAUT = 16.25, -61.58

# Capteurs installés sur toute nouvelle parcelle : mêmes bornes de validation que la démonstration
CAPTEURS = [
    ("sol", "humidite", "%", 5, 70, 0.5, 2.0),
    ("air", "temperature", "°C", 5, 45, 1.0, 1.0),
    ("air", "luminosite", "lx", 0, 150000, None, None),
    ("pluvio", "intensite", "mm/h", 0, 200, None, None),
]


def exiger_admin(utilisateur: Utilisateur) -> None:
    if utilisateur.role != "administrateur":
        raise HTTPException(403, "Réservé à l'administrateur.")


@router.get(
    "",
    response_model=PageParcelles,
    summary="Liste de mes parcelles (paginée)",
    responses=reponses(401, 422),
)
async def lister_parcelles(
    utilisateur: UtilisateurCourant,
    page: Annotated[int, Query(ge=1)] = 1,
    taille: Annotated[int, Query(ge=1, le=100)] = 20,
):
    params = {
        "admin": utilisateur.role == "administrateur",
        "uid": utilisateur.id,
        "limite": taille,
        "decalage": (page - 1) * taille,
    }
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS total" + FILTRE_PROPRIETAIRE, params)
        total = (await cur.fetchone())["total"]
        cur = await conn.execute(
            f"SELECT {COLONNES}" + FILTRE_PROPRIETAIRE + " ORDER BY p.id LIMIT %(limite)s OFFSET %(decalage)s",
            params,
        )
        lignes = await cur.fetchall()
    return PageParcelles(elements=lignes, page=page, taille=taille, total=total)


async def _lire(conn: AsyncConnection, id: int) -> dict:
    cur = await conn.execute(
        f"SELECT {COLONNES}" + FILTRE_PROPRIETAIRE + " AND p.id = %(id)s",
        {"admin": True, "uid": 0, "id": id},
    )
    return await cur.fetchone()


async def _exploitation_de(conn: AsyncConnection, proprietaire: int, commune: str | None) -> dict:
    """L'exploitation de l'exploitant ; créée si c'est sa première parcelle (la commune est alors requise)."""
    cur = await conn.execute(
        "SELECT id, prenom, nom, role FROM utilisateur WHERE id = %s", (proprietaire,)
    )
    personne = await cur.fetchone()
    if personne is None or personne["role"] != "exploitant":
        raise HTTPException(404, f"L'exploitant {proprietaire} n'existe pas.")

    cur = await conn.execute(
        "SELECT id, code FROM exploitation WHERE proprietaire = %s ORDER BY id LIMIT 1", (proprietaire,)
    )
    exploitation = await cur.fetchone()
    if exploitation is not None:
        return exploitation
    if not commune:
        raise HTTPException(422, "Cet exploitant n'a pas encore d'exploitation : indiquez sa commune.")
    cur = await conn.execute(
        """
        INSERT INTO exploitation (proprietaire, code, nom, commune, lat, lon)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, code
        """,
        # code utilisé dans les topics MQTT : unique, dérivé de l'identifiant de l'exploitant
        (proprietaire, f"expl-u{proprietaire}", f"Exploitation de {personne['prenom']} {personne['nom']}",
         commune, LAT_DEFAUT, LON_DEFAUT),
    )
    return await cur.fetchone()


async def _code_libre(conn: AsyncConnection, exploitation: int, prefere: str | None = None) -> str:
    """Code de la parcelle dans l'exploitation (utilisé dans les topics MQTT) : le code actuel s'il est
    libre (parcelle déplacée), sinon le prochain pN."""
    if prefere:
        cur = await conn.execute(
            "SELECT 1 FROM parcelle WHERE exploitation = %s AND code = %s", (exploitation, prefere)
        )
        if await cur.fetchone() is None:
            return prefere
    cur = await conn.execute(
        """
        SELECT coalesce(max(substring(code FROM '^p([0-9]+)$')::int), 0) + 1 AS n
        FROM parcelle WHERE exploitation = %s
        """,
        (exploitation,),
    )
    return f"p{(await cur.fetchone())['n']}"


@router.post(
    "",
    response_model=Parcelle,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une parcelle équipée et l'attribuer à un exploitant (administrateur)",
    description="Crée la parcelle, ses quatre capteurs, sa vanne et une règle d'arrosage au seuil choisi, "
                "puis l'annonce en MQTT pour que les objets (ou le simulateur) et l'ingestion la prennent en compte.",
    responses=reponses(401, 403, 404, 422),
)
async def creer_parcelle(donnees: ParcelleEntree, utilisateur: UtilisateurCourant):
    exiger_admin(utilisateur)
    async with pool.connection() as conn:
        exploitation = await _exploitation_de(conn, donnees.proprietaire, donnees.commune)
        code = await _code_libre(conn, exploitation["id"])
        cur = await conn.execute(
            """
            INSERT INTO parcelle (exploitation, code, nom, culture, surface_m2)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (exploitation["id"], code, donnees.nom, donnees.culture.lower(), donnees.surface_m2),
        )
        pid = (await cur.fetchone())["id"]
        async with conn.cursor() as c:
            await c.executemany(
                """
                INSERT INTO capteur (parcelle, type, grandeur, unite, min_valide, max_valide,
                                     baisse_max_min, hausse_max_min)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(pid, *capteur) for capteur in CAPTEURS],
            )
        await conn.execute("INSERT INTO equipement (parcelle, type, etat) VALUES (%s, 'vanne', 'fermee')", (pid,))
        # Règle par défaut, comme en démonstration : délai court adapté au simulateur accéléré
        await conn.execute(
            """
            INSERT INTO regle (parcelle, nom, condition, action, active, delai_min_s)
            VALUES (%s, %s,
                    jsonb_build_object('et', jsonb_build_array(
                        jsonb_build_object('capteur', 'sol/humidite', 'op', '<', 'valeur', %s::float),
                        jsonb_build_object('meteo', 'pluie_6h', 'op', '<', 'valeur', 2))),
                    '{"equipement": "vanne", "action": "ouvrir", "duree_s": 600}', true, 120)
            """,
            (pid, f"Arrosage {donnees.nom}"[:80], donnees.seuil),
        )
        await conn.commit()   # validée AVANT l'annonce : l'ingestion doit trouver les capteurs
        parcelle = await _lire(conn, pid)

    provision.annoncer(exploitation["code"], code, parcelle["culture"])
    log.info("Parcelle %s/%s créée pour l'exploitant %s", exploitation["code"], code, donnees.proprietaire)
    return parcelle


@router.get(
    "/{id}",
    response_model=Parcelle,
    summary="Détail d'une parcelle",
    responses=reponses(401, 404, 422),
)
async def lire_parcelle(id: int, utilisateur: UtilisateurCourant):
    params = {"admin": utilisateur.role == "administrateur", "uid": utilisateur.id, "id": id}
    async with pool.connection() as conn:
        cur = await conn.execute(f"SELECT {COLONNES}" + FILTRE_PROPRIETAIRE + " AND p.id = %(id)s", params)
        ligne = await cur.fetchone()
    if ligne is None:
        raise HTTPException(404, f"La parcelle {id} n'existe pas ou ne vous appartient pas.")
    return ligne


@router.patch(
    "/{id}",
    response_model=Parcelle,
    summary="Attribuer la parcelle à un autre exploitant (administrateur)",
    description="La parcelle passe dans l'exploitation du nouvel exploitant, avec ses capteurs, sa vanne, "
                "sa règle et son historique. Ses topics MQTT changent : elle est retirée puis annoncée à nouveau.",
    responses=reponses(401, 403, 404, 422),
)
async def attribuer_parcelle(id: int, donnees: Attribution, utilisateur: UtilisateurCourant):
    exiger_admin(utilisateur)
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT p.code, p.culture, e.id AS exploitation, e.code AS expl, e.proprietaire
            FROM parcelle p JOIN exploitation e ON e.id = p.exploitation WHERE p.id = %s
            """,
            (id,),
        )
        avant = await cur.fetchone()
        if avant is None:
            raise HTTPException(404, f"La parcelle {id} n'existe pas.")
        if avant["proprietaire"] == donnees.proprietaire:
            return await _lire(conn, id)

        exploitation = await _exploitation_de(conn, donnees.proprietaire, donnees.commune)
        code = await _code_libre(conn, exploitation["id"], prefere=avant["code"])
        await conn.execute(
            "UPDATE parcelle SET exploitation = %s, code = %s WHERE id = %s", (exploitation["id"], code, id)
        )
        await conn.commit()
        parcelle = await _lire(conn, id)

    provision.retirer(avant["expl"], avant["code"])
    provision.annoncer(exploitation["code"], code, parcelle["culture"])
    log.info("Parcelle %s : %s/%s -> %s/%s", id, avant["expl"], avant["code"], exploitation["code"], code)
    return parcelle
