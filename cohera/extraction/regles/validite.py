"""Dates de début et de fin de validité (CAP09) et marqueurs de dérogation (CAP10).

« jusqu'au 31 décembre 2026 », « depuis le 1er janvier 2025 », « À compter du ».
Conditionne I16 et N07 (CAP09) ainsi que I17, I18 et N05 (CAP10).

Toutes les dates du corpus sont en toutes lettres françaises — aucun format de
`segmentation.yaml` (`%d/%m/%Y`, construit pour l'en-tête) ne les couvre. `_date_longue`
fait donc son propre repérage, via `dates.mois` (config), sans dépendance nouvelle.

La cible d'une dérogation est un renvoi interne comme un autre : sa résolution réutilise
`regles/references.resoudre_reference_interne`, pas une réimplémentation.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

from cohera.extraction.config import charger_lexique_extraction
from cohera.extraction.frames import Derogation, Validite
from cohera.extraction.regles.references import resoudre_reference_interne
from cohera.ingestion.modeles import Clause, Segmentation


@lru_cache(maxsize=1)
def _lexique():
    return charger_lexique_extraction()


# --------------------------------------------------------------------------------- dates


@lru_cache(maxsize=1)
def _motif_date() -> re.Pattern:
    mois = "|".join(re.escape(m) for m in _lexique().dates.mois)
    return re.compile(rf"(\d{{1,2}})(?:er)?\s+({mois})\s+(\d{{4}})", re.IGNORECASE)


def _date_longue(texte: str) -> date | None:
    trouve = _motif_date().search(texte)
    if not trouve:
        return None
    jour = int(trouve.group(1))
    mois = _lexique().dates.mois[trouve.group(2).lower()]
    annee = int(trouve.group(3))
    return date(annee, mois, jour)


# ------------------------------------------------------------------------------- CAP09


def extraire_validite(clause: Clause) -> dict[str, object]:
    texte = clause.texte_source
    bornes: dict[str, date] = {}

    for marqueur in _lexique().validite.marqueurs_debut:
        trouve = re.search(re.escape(marqueur), texte, re.IGNORECASE)
        if trouve:
            date_trouvee = _date_longue(texte[trouve.end() :])
            if date_trouvee is not None:
                bornes["debut"] = date_trouvee
                break

    for marqueur in _lexique().validite.marqueurs_fin:
        trouve = re.search(re.escape(marqueur), texte, re.IGNORECASE)
        if trouve:
            date_trouvee = _date_longue(texte[trouve.end() :])
            if date_trouvee is not None:
                bornes["fin"] = date_trouvee
                break

    return {"validite": Validite(**bornes)} if bornes else {}


# ------------------------------------------------------------------------------- CAP10


@lru_cache(maxsize=1)
def _motif_approbateur() -> re.Pattern:
    return re.compile(
        r"approuvée?\s+par\s+(?:le\s+|la\s+|l['’]\s*)?([^,.]+?)"
        r"(?:\s+le\s+(\d{1,2}(?:er)?\s+\w+\s+\d{4})|(?=[,.]|$))",
        re.IGNORECASE,
    )


def _apres_marqueur(texte: str, marqueur: str) -> str | None:
    trouve = re.search(re.escape(marqueur), texte, re.IGNORECASE)
    return texte[trouve.end() :] if trouve else None


def _premiere_phrase(texte: str) -> str:
    trouve = re.search(r"[,.;]", texte)
    return texte[: trouve.start()].strip() if trouve else texte.strip()


def extraire_derogation(
    clause: Clause, doc_id: str, segmentations: dict[str, Segmentation]
) -> Derogation | None:
    texte = clause.texte_source
    marqueur = next(
        (m for m in _lexique().derogation.marqueurs if m.lower() in texte.lower()), None
    )
    if marqueur is None:
        return None

    apres = _apres_marqueur(texte, marqueur) or ""
    resolution = resoudre_reference_interne(apres, doc_id, segmentations)
    if resolution is None:
        # Repli : la cible peut être formulée avant le marqueur au lieu d'après lui,
        # mais dans ce corpus « par dérogation à/au » précède toujours le § — un renvoi
        # non trouvé signifie qu'il n'y en a pas.
        cible = _premiere_phrase(apres)
        document_cible, resolue = None, False
    else:
        numero, document_cible, resolue = resolution
        cible = f"§ {numero}"

    justification = None
    for m in _lexique().derogation.marqueurs_justification:
        apres_j = _apres_marqueur(texte, m)
        if apres_j is not None:
            justification = _premiere_phrase(apres_j)
            break

    approbateur, date_approbation = None, None
    trouve_approbateur = _motif_approbateur().search(texte)
    if trouve_approbateur:
        approbateur = trouve_approbateur.group(1).strip()
        if trouve_approbateur.group(2):
            date_approbation = _date_longue(trouve_approbateur.group(2))

    echeance = None
    for m in _lexique().derogation.marqueurs_echeance:
        apres_e = _apres_marqueur(texte, m)
        if apres_e is not None:
            echeance = _date_longue(apres_e)
            if echeance is not None:
                break

    return Derogation(
        cible=cible,
        cible_document=document_cible,
        cible_resolue=resolue,
        justification=justification,
        approbateur=approbateur,
        date_approbation=date_approbation,
        echeance=echeance,
    )
