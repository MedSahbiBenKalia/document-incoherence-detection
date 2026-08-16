"""Types partagés par les canaux, la fusion et le filtre de comparabilité.

Un module de types séparé plutôt qu'un import croisé : les canaux produisent des
:class:`Appariement`, la fusion les consomme, et le filtre travaille sur des
:class:`ContexteClause`. Les faire vivre dans l'un des trois créerait un cycle.

**L'identité d'une paire est non ordonnée.** Le canal CLE émet toujours de D1 vers D2
(`a.doc_id < b.doc_id`), mais le canal vectoriel interroge l'index clause par clause et
peut très bien rendre la même paire dans les deux sens. Sans clé normalisée, la fusion
compterait deux paires là où il n'y en a qu'une, et le budget serait faussé. D'où
:attr:`Appariement.cle`, qui trie les deux identifiants.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from cohera.extraction.frames import Modalite


class Canal(StrEnum):
    """Les cinq canaux de ciblage (architecture.md §6.1 à §6.5).

    ``STRUCTUREL`` est déclaré mais n'est pas implémenté au J4 : le plan à 7 jours ne liste
    que les canaux 2 à 5, et l'arête ``RENVOIE_A`` sur laquelle il repose n'est pas chargée
    dans le graphe — la requête rendrait 0 ligne. Voir `canaux/structurel.py`.
    """

    STRUCTUREL = "STRUCTUREL"
    CLE = "CLE"
    CONCEPTUEL = "CONCEPTUEL"
    VECTORIEL = "VECTORIEL"
    DIMENSION = "DIMENSION"


#: Identité non ordonnée d'une paire de clauses.
ClePaire = tuple[str, str]


def cle_paire(clause_a: str, clause_b: str) -> ClePaire:
    """La clé non ordonnée d'une paire : ``(min, max)`` des deux identifiants."""
    return (clause_a, clause_b) if clause_a <= clause_b else (clause_b, clause_a)


class Appariement(BaseModel):
    """Une paire proposée par **un** canal, avec son rang dans ce canal.

    ``score`` est l'échelle propre du canal (cosinus, poids IDF cumulé, 1.0 pour une
    égalité exacte) : il n'est comparable qu'à l'intérieur du canal. C'est ``rang`` que la
    fusion consomme, jamais ``score`` — voir `fusion_rrf.py`.
    """

    clause_a: str
    clause_b: str
    canal: Canal
    score: float
    rang: int

    @property
    def cle(self) -> ClePaire:
        return cle_paire(self.clause_a, self.clause_b)


class ContexteClause(BaseModel):
    """Ce qu'il faut savoir d'une clause pour juger de sa comparabilité.

    Volontairement plat et sans dépendance au graphe : le Cypher collecte ces attributs,
    et toute la logique de `comparabilite.py` se teste hors ligne sur des objets construits
    à la main.
    """

    clause_id: str
    doc_id: str = ""
    ref: str = ""
    modalite: Modalite | None = None
    #: Bornes de validité en ISO (``2025-01-01``) ou ``None``. Comparables en tant que
    #: chaînes : le format ISO est ordonné lexicographiquement.
    date_debut_validite: str | None = None
    date_fin_validite: str | None = None
    #: Les couples ``(dimension, role)`` des grandeurs portées par la clause.
    dimensions_roles: list[tuple[str, str]] = Field(default_factory=list)
    #: Codes des référentiels externes cités (`CITE_NORME`).
    normes_citees: list[str] = Field(default_factory=list)
    #: Identifiants des concepts canoniques d'IDF suffisant mentionnés par la clause.
    concepts_canoniques: list[str] = Field(default_factory=list)
    #: Couples ``(doc_id, ref)`` visés par un renvoi explicite de cette clause.
    #:
    #: Peuplé depuis les `Reference` des Clause Frames, **pas** depuis le graphe :
    #: `chargeur.py` n'écrit pas d'arête `RENVOIE_A`.
    renvois: list[tuple[str, str]] = Field(default_factory=list)
