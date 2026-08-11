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
def pont(vocabulaire):
    """Le pont inter-documents, construit une seule fois.

    Encode ~350 libellés avec bge-m3 : quelques secondes au premier passage, puis servi par
    le cache disque de `cohera/embeddings.py`. C'est précisément la raison d'être de ce
    cache, et cette fixture en est le premier bénéficiaire.
    """
    from cohera.graphe.alias import construire_pont

    return construire_pont(vocabulaire)
