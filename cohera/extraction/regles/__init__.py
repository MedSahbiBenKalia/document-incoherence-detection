"""Étage déterministe de l'extraction — toujours exécuté en premier.

Les cinq modules de règles écrivent des champs disjoints de la Clause Frame :
`grandeurs`/`conditions`/`deontique` sont de purs `Clause -> ...` (indépendants,
parallélisables) ; `references` et `validite.extraire_derogation` ont besoin du corpus
entier (`dict[str, Segmentation]`) pour résoudre un renvoi inter-documents. Cet
orchestrateur est le seul point qui les connaît tous.
"""

from __future__ import annotations

from cohera.extraction.frames import ClauseFrame, Modalite, TypeEnonce
from cohera.extraction.regles.conditions import extraire_conditions
from cohera.extraction.regles.deontique import extraire_modalite
from cohera.extraction.regles.grandeurs import extraire_grandeurs
from cohera.extraction.regles.references import extraire_references
from cohera.extraction.regles.validite import extraire_derogation, extraire_validite
from cohera.ingestion.modeles import Clause, Segmentation

_MODALITES_PRESCRIPTIVES = frozenset(
    {Modalite.OBLIGATION, Modalite.INTERDICTION, Modalite.PERMISSION, Modalite.RECOMMANDATION}
)


def _type_enonce(modalite: Modalite | None, derogation: object, references: list) -> TypeEnonce:
    """Priorité de synthèse — architecture.md §4.1 liste les cinq valeurs sans les
    ordonner. Exemples travaillés : D1 §7.5/D2 §6.3 (renvoi seul, aucun marqueur) ->
    RENVOI ; D1 §9.3 (aucun marqueur, aucune référence, aucune grandeur) -> CONSTAT ;
    D1 §10.1 (dérogation ET « sont dispensées ») -> DEROGATION, `modalite` restant
    PERMISSION indépendamment."""
    if derogation is not None:
        return TypeEnonce.DEROGATION
    if modalite is Modalite.DEFINITION:
        return TypeEnonce.DEFINITION
    if modalite in _MODALITES_PRESCRIPTIVES:
        return TypeEnonce.PRESCRIPTION
    if references and modalite is None:
        return TypeEnonce.RENVOI
    return TypeEnonce.CONSTAT


def extraire_frame(clause: Clause, doc_id: str, segmentations: dict[str, Segmentation]) -> ClauseFrame:
    """Fusionne les cinq extracteurs de règles en une Clause Frame, avec sa provenance
    champ par champ. Ne remplit jamais `acteur`/`action`/`objet`/`perimetre`/`portee` —
    hors périmètre J2 (`regles/raci.py`, étage LLM du J6)."""
    champs: dict[str, object] = {}
    source: dict[str, str] = {}

    for cle, valeur in extraire_modalite(clause).items():
        champs[cle] = valeur
        if cle != "confiance_extraction":
            source[cle] = "REGLE"

    grandeurs = extraire_grandeurs(clause)
    if grandeurs:
        champs["quantites"] = grandeurs
        source["quantites"] = "REGLE"

    conditions = extraire_conditions(clause)
    if conditions:
        champs["conditions"] = conditions
        source["conditions"] = "REGLE"

    references = extraire_references(clause, doc_id, segmentations)
    if references:
        champs["references"] = references
        source["references"] = "REGLE"

    validite = extraire_validite(clause).get("validite")
    if validite is not None:
        champs["validite"] = validite
        source["validite"] = "REGLE"

    derogation = extraire_derogation(clause, doc_id, segmentations)
    if derogation is not None:
        champs["derogation"] = derogation
        source["derogation"] = "REGLE"

    champs["type_enonce"] = _type_enonce(champs.get("modalite"), derogation, references)
    source["type_enonce"] = "REGLE"
    champs["source_extraction"] = source

    return ClauseFrame(clause_id=clause.clause_id, **champs)


def extraire_toutes(segmentations: dict[str, Segmentation]) -> dict[str, ClauseFrame]:
    """Une Clause Frame par clause du corpus, clé = `clause_id`."""
    return {
        clause.clause_id: extraire_frame(clause, doc_id, segmentations)
        for doc_id, segmentation in segmentations.items()
        for clause in segmentation.clauses
    }
