"""Non-régression du point de contact J2 : `marqueurs_deontiques` est passé de
`list[str]` à `list[dict]` dans `lexique_qhse.yaml` (modalité/force par marqueur), et
`ingestion/phrases.py` doit continuer à qualifier exactement comme au J1."""

from __future__ import annotations

from cohera.ingestion.phrases import _motifs_de_qualification, qualifier


def test_la_qualification_accepte_toujours_un_enonce_normatif() -> None:
    assert qualifier("Le port du casque est obligatoire en zone A.") is True


def test_la_qualification_ecarte_toujours_une_phrase_de_cadrage() -> None:
    assert (
        qualifier("Ce document est diffusé à l'ensemble des services par voie électronique.")
        is False
    )


def test_la_qualification_ne_leve_pas_sur_le_lexique_reel_reforme() -> None:
    """`config["marqueurs_deontiques"]` est maintenant une liste de dicts : la lecture
    `["marqueur"]` doit réussir sans KeyError ni TypeError sur le vrai fichier."""
    assert len(_motifs_de_qualification()) > 0
