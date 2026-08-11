"""Recomposition des listes à chapeau (CAP02) — l'étape critique de la segmentation.

« L'Animateur QSE doit : a) planifier… b) tenir à jour… » découpé naïvement donne trois
fragments sans sujet ni modalité : le J2 n'y verrait ni acteur ni obligation, et le
ciblage ne les apparierait à rien.

Le chapeau est donc **redistribué** sur chaque item — dans `texte_autonome` seulement.
`texte_source` reste l'empan littéral de l'item, sans quoi l'offset ne pointerait plus
sur rien de contigu.
"""

from __future__ import annotations

import re
from functools import lru_cache

from cohera import reglages
from cohera.ingestion.structure import Ligne, Unite


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("segmentation")


@lru_cache(maxsize=1)
def _motifs_de_puce() -> tuple[re.Pattern, ...]:
    return tuple(re.compile(motif) for motif in _config()["puces"]["motifs"])


def _decalage_de_puce(ligne: Ligne) -> int | None:
    """Position du texte de l'item, la puce « a) » retirée. `None` si ce n'en est pas une."""
    for motif in _motifs_de_puce():
        trouve = motif.match(ligne.texte)
        if trouve:
            return trouve.end()
    return None


def detecter(unite: Unite) -> tuple[str, list[Ligne]] | None:
    """Renvoie `(chapeau, items)` si l'unité est une liste à chapeau, `None` sinon.

    Exige que **toutes** les lignes suivant le chapeau soient des items : un paragraphe
    qui contient une incise à tiret ne doit pas se retrouver éclaté.
    """
    if len(unite.lignes) < 2 or not unite.commence_par_un_chapeau():
        return None

    items = unite.lignes[1:]
    if not items or any(_decalage_de_puce(ligne) is None for ligne in items):
        return None

    return unite.premiere_ligne.strip(), items


def exploser(unite: Unite, texte_origine: str) -> list[dict]:
    """Une clause par item, chacune reprenant le chapeau dans son texte de travail."""
    detecte = detecter(unite)
    if detecte is None:
        return []

    chapeau, items = detecte
    sujet = _sans_deux_points(chapeau)
    produites = []

    for ligne in items:
        decalage = _decalage_de_puce(ligne)
        debut = ligne.debut + decalage
        fin = ligne.debut + len(ligne.texte.rstrip())
        corps = ligne.texte[decalage:].rstrip()

        produites.append(
            {
                "debut": debut,
                "fin": fin,
                "texte_source": texte_origine[debut:fin],
                "texte_autonome": f"{sujet} {_sans_terminaison(corps)}.",
                "chapeau": chapeau,
            }
        )
    return produites


def _sans_deux_points(chapeau: str) -> str:
    """« L'Animateur QSE doit : » → « L'Animateur QSE doit »."""
    for terminaison in _config()["chapeau"]["terminaisons"]:
        if chapeau.rstrip().endswith(terminaison):
            return chapeau.rstrip()[: -len(terminaison)].rstrip()
    return chapeau.rstrip()


def _sans_terminaison(item: str) -> str:
    """« planifier les contrôles ; » → « planifier les contrôles »."""
    for terminaison in _config()["puces"]["terminaisons"]:
        if item.endswith(terminaison):
            return item[: -len(terminaison)].rstrip()
    return item
