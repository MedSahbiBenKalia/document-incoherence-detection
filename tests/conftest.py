"""Fixtures partagées.

La segmentation charge `fr_core_news_lg` (~3 s) : elle est faite une fois par session,
pas une fois par test.
"""

from __future__ import annotations

import json

import pytest

from cohera import reglages
from cohera.ingestion import segmenter_jeu
from cohera.ingestion.modeles import Segmentation


@pytest.fixture(scope="session")
def jeu() -> dict[str, Segmentation]:
    return segmenter_jeu("fixtures")


@pytest.fixture(scope="session")
def d1(jeu: dict[str, Segmentation]) -> Segmentation:
    return jeu["D1"]


@pytest.fixture(scope="session")
def d2(jeu: dict[str, Segmentation]) -> Segmentation:
    return jeu["D2"]


@pytest.fixture(scope="session")
def verite() -> dict:
    """`label.json`, en LECTURE SEULE — jamais une cible à ajuster."""
    chemin = reglages.racine_projet() / "corpus" / "fixtures" / "label.json"
    return json.loads(chemin.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------ J3 : graphe


@pytest.fixture(scope="session")
def frames(jeu: dict[str, Segmentation]) -> dict:
    """Les Clause Frames du corpus, extraites une fois pour la session."""
    from cohera.extraction.regles import extraire_toutes

    return extraire_toutes(jeu)


@pytest.fixture(scope="session")
def vocabulaire(jeu: dict[str, Segmentation], frames: dict):
    """Les concepts du corpus. Réutilise l'analyseur spaCy déjà chargé par `jeu`."""
    from cohera.graphe.concepts import extraire_vocabulaire

    return extraire_vocabulaire(jeu, frames)


@pytest.fixture(scope="session")
def identifiants(jeu: dict[str, Segmentation]) -> dict[tuple[str, str], str]:
    """``(doc, ref) -> clause_id`` — la correspondance qu'annonce `label.json`.

    `label.json` désigne les clauses par leur numéro de paragraphe ; le pipeline les
    désigne par un `clause_id`. Cette table est le seul pont entre les deux, et elle est
    construite depuis la segmentation, jamais écrite à la main.
    """
    return {
        (doc_id, clause.ref): clause.clause_id
        for doc_id, segmentation in jeu.items()
        for clause in segmentation.clauses
    }


@pytest.fixture(scope="session")
def textes(jeu: dict[str, Segmentation]) -> dict[str, str]:
    """``clause_id -> texte_source`` — le texte contre lequel toute preuve est vérifiée."""
    return {
        clause.clause_id: clause.texte_source
        for segmentation in jeu.values()
        for clause in segmentation.clauses
    }


def paire_de(verite: dict, identifiant: str, identifiants: dict) -> tuple[str, str]:
    """Les deux `clause_id` d'une entrée de la vérité terrain."""
    entree = entree_de(verite, identifiant)
    a, b = entree["clause_a"], entree["clause_b"]
    return identifiants[(a["doc"], a["ref"])], identifiants[(b["doc"], b["ref"])]


def entree_de(verite: dict, identifiant: str) -> dict:
    """L'entrée de `label.json` portant cet identifiant, incohérence ou contre-exemple."""
    return next(
        e
        for rubrique in ("incoherences", "contre_exemples", "limites_connues")
        for e in verite.get(rubrique, [])
        if e.get("id") == identifiant
    )


@pytest.fixture(scope="session")
def pont(vocabulaire):
    """Le pont inter-documents, construit une seule fois.

    Encode ~350 libellés avec bge-m3 : quelques secondes au premier passage, puis servi par
    le cache disque de `cohera/embeddings.py`. C'est précisément la raison d'être de ce
    cache, et cette fixture en est le premier bénéficiaire.
    """
    from cohera.graphe.alias import construire_pont

    return construire_pont(vocabulaire)


# ---------------------------------------------------------------- J5 : détection


@pytest.fixture(scope="session")
def algebre(frames: dict):
    """L'algèbre des conditions du corpus, construite une fois.

    Fonction pure et bon marché — 23 conditions distinctes, 253 paires — mais elle est
    consommée par tous les tests de détection, autant ne la calculer qu'une fois.
    """
    from cohera.graphe.conditions import construire_algebre

    return construire_algebre(frames)
