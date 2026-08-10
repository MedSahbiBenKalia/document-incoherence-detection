"""Recherche vectorielle compatible avec deux générations de Neo4j.

Neo4j a changé de voie d'accès aux index vectoriels au milieu du calendrier 2026 :

* jusqu'à 2025.x — la procédure ``db.index.vector.queryNodes`` ;
* à partir de **2026.01** — la clause Cypher ``SEARCH``, plus expressive (filtrage
  *dans* l'index) ;
* depuis **2026.04**, la procédure est **dépréciée**.

Ce module choisit la bonne syntaxe au lieu de figer l'une des deux : le PoC doit tourner
aussi bien contre le conteneur épinglé en 2026.06 que contre une instance 5.x héritée.

Le découpage est fait pour que **la logique soit testable sans serveur** :
:func:`requete_vectorielle` est une fonction pure qui prend une version et rend du Cypher.
Seule :func:`recherche_vectorielle` a besoin d'une session.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from neo4j import Session

from cohera import reglages

#: Première version où la clause ``SEARCH`` est disponible.
VERSION_MIN_SEARCH: tuple[int, int] = (2026, 1)

#: Version depuis laquelle ``db.index.vector.queryNodes`` est déprécié (informatif).
VERSION_DEPRECATION_PROCEDURE: tuple[int, int] = (2026, 4)

#: Un nom d'index Cypher, et rien d'autre.
_NOM_INDEX_VALIDE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_cache_versions: dict[str, tuple[int, int]] = {}


# ------------------------------------------------------------------- version serveur


def analyser_version(brut: str) -> tuple[int, int]:
    """Extrait ``(majeur, mineur)`` d'une chaîne de version Neo4j.

    Gère les deux schémas cohabitant : calendaire (``2026.06.0`` -> ``(2026, 6)``) et
    sémantique hérité (``5.26.0`` -> ``(5, 26)``). La comparaison de tuples suffit
    ensuite à ordonner les deux mondes, puisque tout millésime dépasse tout majeur 5.
    """
    nombres = re.findall(r"\d+", brut or "")
    if len(nombres) < 2:
        raise ValueError(f"Version Neo4j inexploitable : {brut!r}")
    return (int(nombres[0]), int(nombres[1]))


def version_serveur(session: Session, *, uri: str | None = None) -> tuple[int, int]:
    """Version du serveur, mise en cache : inutile d'interroger à chaque recherche."""
    cle = uri or reglages.charger().neo4j.uri
    if cle in _cache_versions:
        return _cache_versions[cle]

    resultat = session.run(
        "CALL dbms.components() YIELD name, versions "
        "WHERE name = 'Neo4j Kernel' RETURN versions[0] AS version"
    ).single()
    if resultat is None:
        raise RuntimeError("dbms.components() n'a rien renvoyé pour 'Neo4j Kernel'.")

    version = analyser_version(resultat["version"])
    _cache_versions[cle] = version
    return version


def vider_cache() -> None:
    """Oublie les versions mémorisées. Utile en test, et après un changement d'instance."""
    _cache_versions.clear()


def supporte_clause_search(version: tuple[int, int]) -> bool:
    """La clause ``SEARCH`` est-elle disponible sur cette version ?"""
    return version >= VERSION_MIN_SEARCH


def syntaxe_effective(version: tuple[int, int]) -> str:
    """``"search"`` ou ``"procedure"``, en tenant compte de la surcharge de configuration.

    ``neo4j.syntaxe_vectorielle`` vaut ``auto`` par défaut. Les deux autres valeurs
    forcent une branche — utile pour exercer le chemin hérité en test, ou pour passer
    outre un serveur qui annonce mal sa version.
    """
    choix = reglages.charger().neo4j.syntaxe_vectorielle
    if choix in ("search", "procedure"):
        return choix
    return "search" if supporte_clause_search(version) else "procedure"


# ---------------------------------------------------------------------- construction


def valider_nom_index(index: str) -> str:
    """Vérifie qu'un nom d'index est un identifiant Cypher, et le renvoie.

    Ce n'est pas de la paranoïa gratuite : dans la clause ``SEARCH``, le nom d'index
    **ne peut pas être un paramètre**, il faut donc l'interpoler dans la requête. Sans
    ce garde-fou, un nom d'index issu de la configuration deviendrait une injection
    Cypher.
    """
    if not _NOM_INDEX_VALIDE.match(index or ""):
        raise ValueError(
            f"Nom d'index invalide : {index!r}. "
            "Attendu un identifiant Cypher : lettres, chiffres et tirets bas, "
            "ne commençant pas par un chiffre."
        )
    return index


def requete_vectorielle(version: tuple[int, int], index: str, k: int | None = None) -> str:
    """Cypher de recherche des k plus proches voisins, adapté à la version.

    Fonction **pure** : aucune connexion, donc les deux branches sont testables hors
    ligne. ``k`` et le vecteur restent des paramètres (``$k``, ``$vecteur``) ; seul le
    nom d'index est interpolé, et uniquement dans la branche ``SEARCH`` qui l'impose.
    """
    valider_nom_index(index)

    if syntaxe_effective(version) == "search":
        return (
            "CYPHER 25\n"
            "MATCH (n)\n"
            f"SEARCH n IN (VECTOR INDEX {index} FOR $vecteur LIMIT $k) SCORE AS score\n"
            "RETURN n AS noeud, score\n"
            "ORDER BY score DESC"
        )

    return (
        "CALL db.index.vector.queryNodes($index, $k, $vecteur)\n"
        "YIELD node AS noeud, score\n"
        "RETURN noeud, score\n"
        "ORDER BY score DESC"
    )


# ------------------------------------------------------------------------ exécution


def recherche_vectorielle(
    index: str,
    k: int,
    vecteur: Sequence[float],
    *,
    session: Session | None = None,
) -> list[tuple[Any, float]]:
    """Les ``k`` plus proches voisins de ``vecteur`` dans ``index``, triés du plus proche.

    Détecte la version du serveur, choisit entre la clause ``SEARCH`` et la procédure
    dépréciée, exécute, et renvoie ``[(noeud, score), ...]``.

    ``session`` est facultative : sans elle, une session est ouverte puis refermée pour
    la durée de l'appel.
    """
    valider_nom_index(index)
    if k < 1:
        raise ValueError(f"k doit valoir au moins 1, reçu {k}.")

    if session is not None:
        return _executer(session, index, k, vecteur)

    from cohera.graphe.connexion import session as ouvrir_session

    with ouvrir_session() as sess:
        return _executer(sess, index, k, vecteur)


def _executer(
    session: Session, index: str, k: int, vecteur: Sequence[float]
) -> list[tuple[Any, float]]:
    version = version_serveur(session)
    requete = requete_vectorielle(version, index, k)
    resultat = session.run(
        requete, index=index, k=k, vecteur=list(vecteur)
    )
    return [(enregistrement["noeud"], enregistrement["score"]) for enregistrement in resultat]
