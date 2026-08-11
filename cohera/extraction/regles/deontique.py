"""Modalité et force déontique.

PERMISSION (1), RECOMMANDATION (2), OBLIGATION (3), INTERDICTION (4).
L'écart de force alimente A1 : I04 oppose 1 à 4 (écart 3, conflit fort),
I05 oppose 2 à 3 (écart 1, non concluant seul).

Lit `texte_autonome`, pas `texte_source` : une clause issue d'une liste à chapeau (CAP02,
D1 §4.4) ne porte son marqueur déontique que dans le chapeau redistribué, jamais dans son
propre texte source. `modalite`/`force`/`negation` sont des valeurs, pas des surfaces —
l'invariant de preuve littérale ne s'applique qu'à `modalite_surface`, qui n'est posé que
si le marqueur trouvé vérifie aussi comme sous-chaîne de `texte_source`.

Priorité : DEFINITION d'abord (guillemets + verbe définitionnel ou copule) l'emporte sur
tout marqueur déontique par ailleurs présent dans la même phrase (D1 §3.2) — la clause
définit un terme, elle n'impose pas une obligation à un acteur.
"""

from __future__ import annotations

import re
from functools import lru_cache

from cohera.extraction.config import charger_lexique_extraction
from cohera.extraction.frames import Modalite
from cohera.ingestion.autonomisation import sujet_nominal
from cohera.ingestion.modeles import Clause
from cohera.ingestion.phrases import analyseur


@lru_cache(maxsize=1)
def _lexique():
    return charger_lexique_extraction()


# ------------------------------------------------------------------------- définition


def _est_definition(texte: str) -> bool:
    qualification = _lexique().qualification
    if not re.search(qualification.motif_terme_defini, texte):
        return False
    if re.search(qualification.motif_definition_copule, texte, re.IGNORECASE):
        return True
    return any(
        re.search(rf"\b{re.escape(verbe)}\b", texte, re.IGNORECASE)
        for verbe in qualification.verbes_definitionnels
    )


# --------------------------------------------------------------------------- marqueur


@lru_cache(maxsize=1)
def _marqueurs_tries():
    return sorted(
        _lexique().qualification.marqueurs_deontiques, key=lambda e: len(e.marqueur), reverse=True
    )


def _chercher_marqueur(texte: str) -> tuple[object, re.Match] | tuple[None, None]:
    for entree in _marqueurs_tries():
        trouve = re.search(rf"\b{re.escape(entree.marqueur)}\b", texte, re.IGNORECASE)
        if trouve:
            return entree, trouve
    return None, None


# --------------------------------------------------------------------------- négation


def _tete_pour_empan(doc, debut: int, fin: int):
    """Le token dont l'empan chevauche `[debut:fin)` le plus à droite — le verbe porteur
    du marqueur pour un marqueur multi-mots (« sont autorisées » -> le token « autorisées »)."""
    candidats = [t for t in doc if t.idx < fin and t.idx + len(t.text) > debut]
    return candidats[-1] if candidats else None


def _negation_directe(tete) -> bool:
    """Une particule de négation est-elle un ENFANT DIRECT du token porteur du marqueur ?

    Distingue « ne doit pas valider » (`pas` est enfant de `doit`) de « doit ne pas
    valider » (`pas` est enfant de `valider`, l'infinitif enchâssé, pas de `doit`)."""
    particules = set(_lexique().negation.particules)
    return any(
        enfant.dep_ == "advmod" and enfant.lemma_.lower() in particules for enfant in tete.children
    )


def _marqueur_contient_deja_la_negation(marqueur: str) -> bool:
    """« ne sont pas autorisées » encode déjà l'INTERDICTION dans son texte : la retrouver
    structurellement (`pas` enfant de `autorisées`) ne doit pas l'inverser une seconde
    fois. Seuls les marqueurs à la forme positive (« doit », « est autorisée »…) sont
    candidats à l'inversion."""
    particules = set(_lexique().negation.particules)
    return any(mot in particules for mot in marqueur.lower().split())


# ------------------------------------------------------------------------------ repli


def _present_indicatif(token) -> bool:
    return "Pres" in token.morph.get("Tense") and "Fin" in token.morph.get("VerbForm")


def _sujet_dans_gazetteer(doc) -> bool:
    sujet = sujet_nominal(doc)
    if sujet is None:
        return False
    surface = sujet.text.lower()
    return any(role.lower() in surface for role in _lexique().gazetteer_roles)


# ------------------------------------------------------------------------------ l'entrée


def extraire_modalite(clause: Clause) -> dict[str, object]:
    texte = clause.texte_autonome

    if _est_definition(texte):
        return {"modalite": Modalite.DEFINITION, "force": None}

    entree, correspondance = _chercher_marqueur(texte)
    if entree is not None:
        nlp = analyseur()
        doc = nlp(texte)
        tete = _tete_pour_empan(doc, correspondance.start(), correspondance.end())

        modalite = entree.modalite
        negation = tete is not None and _negation_directe(tete)
        if negation and not _marqueur_contient_deja_la_negation(entree.marqueur):
            inversee = _lexique().negation.inversion.get(modalite.value)
            if inversee:
                modalite = Modalite(inversee)

        resultat: dict[str, object] = {
            "modalite": modalite,
            "force": entree.force,
            "negation": negation,
        }
        surface = correspondance.group(0)
        if surface in clause.texte_source:
            resultat["modalite_surface"] = surface
        return resultat

    nlp = analyseur()
    doc = nlp(texte)
    racine = next((jeton for jeton in doc if jeton.dep_ == "ROOT"), None)
    if racine is not None and _present_indicatif(racine) and _sujet_dans_gazetteer(doc):
        return {
            "modalite": Modalite.OBLIGATION,
            "force": 3,
            "negation": False,
            "confiance_extraction": 0.78,
        }

    return {}
