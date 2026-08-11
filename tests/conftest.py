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
