"""Conditions et portées : spatiales, temporelles, catégorielles.

Alimente l'algèbre des conditions (RECOUVRE / INCLUS_DANS / DISJOINT_DE) — mais ce
module-ci ne fait que repérer et typer une condition, jamais les comparer entre elles :
l'algèbre elle-même est le travail du J5. N04 en dépend : mêmes objets, périodicités
différentes, mais zones disjointes — encore faut-il que « zone A » et « zone de
stockage » restent deux `concept_cible` distincts, ce que ce module garantit.

Un seuil numérique comparable inter-documents (rôle enregistré dans
registre_grandeurs.yaml, ex. seuil_declenchement pour « à plus de 3 mètres ») devient une
Grandeur, pas une Condition — voir regles/grandeurs.py. Un seuil qui ne correspond à
aucun rôle enregistré (vitesse du vent en km/h, durée d'une intervention) reste ici, typé
SEUIL. Les mêmes marqueurs de contexte (`grandeurs.contextes_role`) et de délai qui
redirigent une durée vers une Grandeur dans grandeurs.py servent ici à ne PAS produire un
doublon.
"""

from __future__ import annotations

import re
from functools import lru_cache

from cohera.extraction.config import charger_lexique_extraction
from cohera.extraction.frames import Condition, TypeCondition
from cohera.ingestion.modeles import Clause

_MARQUEURS_EXCLUS_DU_SEUIL = ("sous", "dans un délai de", "délai", "retard")
_UNITES_EXCLUES_DU_SEUIL = ("mètre", "db(a)")

_MOTIF_FIN = re.compile(r"[,.;]")
_MOTIF_PREPOSITION_INITIALE = re.compile(r"^(en|dans|sur)\s+", re.IGNORECASE)


@lru_cache(maxsize=1)
def _lexique():
    return charger_lexique_extraction()


@lru_cache(maxsize=1)
def _motifs_condition() -> tuple:
    marqueurs = sorted(_lexique().conditions.marqueurs, key=lambda m: len(m.motif), reverse=True)
    return tuple((re.compile(re.escape(m.motif), re.IGNORECASE), m.type) for m in marqueurs)


def _surface_depuis(texte: str, debut: int) -> str:
    trouve = _MOTIF_FIN.search(texte, debut)
    fin = trouve.start() if trouve else len(texte)
    return texte[debut:fin].strip()


def _lieu(surface: str) -> str:
    return _MOTIF_PREPOSITION_INITIALE.sub("", surface).strip()


# -------------------------------------------------------------------------------- seuil


@lru_cache(maxsize=1)
def _motif_nombre() -> str:
    mots = sorted(_lexique().grandeurs.nombres_lettres, key=len, reverse=True)
    return r"\d+(?:[.,]\d+)?|" + "|".join(re.escape(m) for m in mots)


def _valeur_nombre(brut: str) -> float:
    brut = brut.strip().lower()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", brut):
        return float(brut.replace(",", "."))
    return float(_lexique().grandeurs.nombres_lettres[brut])


@lru_cache(maxsize=1)
def _motif_seuil() -> re.Pattern:
    return re.compile(r"(" + _motif_nombre() + r")\s*(km/h|minutes?|heures?)\b", re.IGNORECASE)


def _operateur_seuil(texte: str) -> str | None:
    motifs = sorted(_lexique().grandeurs.operateurs_seuil, key=lambda o: len(o.motif), reverse=True)
    for op in motifs:
        if re.search(re.escape(op.motif), texte, re.IGNORECASE):
            return op.operateur.value
    return None


def _contexte_role_present(texte: str) -> bool:
    """Un contexte qui redirige déjà cette durée vers une Grandeur dans grandeurs.py
    (formation, habilitation, archivage, effectif) : ne pas produire de doublon ici."""
    bas = texte.lower()
    return any(
        mot in bas for mots in _lexique().grandeurs.contextes_role.values() for mot in mots
    )


def _extraire_seuil(texte: str) -> Condition | None:
    bas = texte.lower()
    if any(marqueur in bas for marqueur in _MARQUEURS_EXCLUS_DU_SEUIL):
        return None
    if _contexte_role_present(texte):
        return None
    operateur = _operateur_seuil(texte)
    if operateur is None:
        return None
    trouve = _motif_seuil().search(texte)
    if not trouve:
        return None
    if any(exclue in trouve.group(2).lower() for exclue in _UNITES_EXCLUES_DU_SEUIL):
        return None
    return Condition(
        surface=trouve.group(0),
        type=TypeCondition.SEUIL,
        operateur=operateur,
        valeur=_valeur_nombre(trouve.group(1)),
    )


# ------------------------------------------------------------------------------ l'entrée


def extraire_conditions(clause: Clause) -> list[Condition]:
    texte = clause.texte_source
    conditions: list[Condition] = []

    for motif, type_condition in _motifs_condition():
        trouve = motif.search(texte)
        if not trouve:
            continue
        surface = _surface_depuis(texte, trouve.start())
        condition = Condition(surface=surface, type=type_condition)
        if type_condition is TypeCondition.SPATIAL:
            condition.operateur = "APPARTIENT"
            condition.concept_cible = _lieu(surface)
        conditions.append(condition)

    seuil = _extraire_seuil(texte)
    if seuil is not None:
        conditions.append(seuil)

    return conditions
