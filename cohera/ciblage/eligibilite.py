"""Filtres d'éligibilité, appliqués AVANT tout canal.

F2 écarte les paires dont les périodes de validité sont disjointes (N07),
F3 écarte celles couvertes par une dérogation en vigueur (N05).

Ces trois filtres écartent des paires que le corpus **a lui-même déjà résolues**
(architecture.md §6.0) : un document abrogé, deux clauses qui ne sont jamais en vigueur en
même temps, une exception déclarée et approuvée. Ils coûtent une requête et suppriment la
majorité des faux positifs d'un système documentaire réel.

**F3 ne supprime pas la paire, il la requalifie.** Une dérogation déclarée n'est pas une
incohérence, mais elle n'est pas non plus un non-événement : elle doit figurer dans la
rubrique « dérogations en vigueur » du rapport, avec son échéance et son approbateur. Une
dérogation sans justification, sans approbateur ou expirée est elle-même une constatation
(détecteur A8, J5).

**Où les données sont prises.** F1 lit le graphe. F2 lit les bornes de validité portées par
les clauses. F3 lit les `Derogation` des Clause Frames et **non** le graphe : `chargeur.py`
n'écrit pas d'arête `DEROGE_A`, exactement comme il n'écrit pas de `RENVOIE_A`.
"""

from __future__ import annotations

from neo4j import Session
from pydantic import BaseModel

from cohera.ciblage.modeles import ContexteClause
from cohera.extraction.frames import ClauseFrame


class PaireEcartee(BaseModel):
    """Une paire écartée par un filtre d'éligibilité, avec le motif qui l'explique.

    `.claude/rules/detection.md` : « Toute paire écartée par un filtre est journalisée avec
    son motif. » Un rejet est définitif et silencieux ; il doit donc rester traçable.
    """

    clause_a: str
    clause_b: str
    filtre: str
    motif: str


# ------------------------------------------------------------ F1 · documents abrogés


def requete_f1() -> str:
    """Marque les documents abrogés ou remplacés comme non éligibles (architecture.md §6.0).

    Idempotent : réécrire ``eligible`` à la même valeur ne crée rien.
    """
    return (
        "MATCH (d:Document)\n"
        "SET d.eligible = NOT (d.statut = 'ABROGE'\n"
        "                      OR EXISTS { (:Document)-[:ANNULE_ET_REMPLACE]->(d) })\n"
        "RETURN d.doc_id AS doc_id, d.eligible AS eligible"
    )


def appliquer_f1(session: Session) -> dict[str, bool]:
    """Applique F1 et rend l'éligibilité de chaque document.

    Sur les fixtures, les deux documents sont EN_VIGUEUR et aucune arête
    `ANNULE_ET_REMPLACE` n'est chargée : les deux ressortent éligibles. Le filtre n'est donc
    pas exercé par ce corpus, et son test le dit plutôt que de le laisser croire.
    """
    return {
        enregistrement["doc_id"]: bool(enregistrement["eligible"])
        for enregistrement in session.run(requete_f1())
    }


# ---------------------------------------------------------- F2 · validités disjointes


def periodes_disjointes(a: ContexteClause, b: ContexteClause) -> bool:
    """Les deux clauses ne sont-elles jamais en vigueur en même temps ?

    Fonction pure. C'est le cas de N07 : « fixé à un » jusqu'au 31 décembre 2024 contre
    « au minimum deux » à compter du 1er janvier 2025 — deux valeurs différentes, mais
    aucune date à laquelle les deux s'appliquent.

    Une borne absente vaut « depuis toujours » ou « pour toujours » : sans date, une clause
    est en vigueur, et deux clauses sans dates ne sont jamais disjointes.
    """
    return _finit_avant(a, b) or _finit_avant(b, a)


def _finit_avant(premier: ContexteClause, second: ContexteClause) -> bool:
    fin, debut = premier.date_fin_validite, second.date_debut_validite
    return bool(fin and debut and fin < debut)


# --------------------------------------------------------------- F3 · dérogations


def derogations_declarees(frames: dict[str, ClauseFrame]) -> dict[str, str]:
    """``clause_id -> surface de la cible``, pour les dérogations déclarées et résolues.

    Fonction pure. La paire couverte n'est pas supprimée : c'est à la restitution de la
    lister à part, et au détecteur A8 de juger la dérogation elle-même.
    """
    return {
        clause_id: frame.derogation.cible
        for clause_id, frame in frames.items()
        if frame.derogation is not None and frame.derogation.cible_resolue
    }
