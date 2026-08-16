"""Filtre de comparabilité — architecture.md §6.6, filtre n°1.

Il répond à une seule question, posée **après** la fusion et **avant** tout modèle : ces
deux clauses parlent-elles d'une matière où une contradiction est même concevable ? « Une
définition et un seuil ne se contredisent pas. »

C'est ce filtre qui rejette le contre-exemple N03 — deux phrases de cadrage citant le même
site, cosinus élevé, aucune modalité prescriptive, aucune grandeur — sans qu'aucun NLI ni
aucun LLM ne soit appelé sur la paire.

**Cinq branches, là où l'architecture en écrit trois.** Les branches NORME et CONCEPTUELLE
ont été ajoutées au J4 sur mesure : I08 et I11 sont rejetées sans elles. Le détail et la
cause commune (une prescription sans marqueur déontique laisse `modalite = null` au J2) sont
dans `config/ciblage.yaml`, et l'écart est consigné au Journal de `CLAUDE.md`.

**Fonction pure.** Conformément à la convention du dépôt (`graphe/compat.py`,
`graphe/schema.py`), toute la logique porte sur des :class:`ContexteClause` construits par
l'appelant. Le Cypher ne fait que collecter des attributs ; ce module ne connaît pas Neo4j,
donc N03 se teste hors ligne.

**Un rejet est journalisé, jamais silencieux** (`.claude/rules/detection.md`) : le verdict
porte toujours son motif, y compris quand il est négatif.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from cohera.ciblage import config_ciblage
from cohera.ciblage.modeles import ContexteClause


class Motif(StrEnum):
    """Pourquoi la paire est comparable — ou pourquoi elle ne l'est pas."""

    MODALITE = "MODALITE"
    DIMENSION = "DIMENSION"
    RENVOI = "RENVOI"
    NORME = "NORME"
    CONCEPTS = "CONCEPTS"
    AUCUNE_BRANCHE = "AUCUNE_BRANCHE"


class Verdict(BaseModel):
    """Le résultat du filtre, motif compris.

    ``bool(verdict)`` vaut ``verdict.comparable`` : le filtre se lit ``if comparable(a, b):``
    sans perdre le motif pour le journal.
    """

    comparable: bool
    motif: Motif
    explication: str = ""

    def __bool__(self) -> bool:
        return self.comparable


def _prescriptive(contexte: ContexteClause) -> bool:
    return (
        contexte.modalite is not None
        and contexte.modalite in config_ciblage.modalites_prescriptives()
    )


def _renvoie_vers(source: ContexteClause, cible: ContexteClause) -> bool:
    return (cible.doc_id, cible.ref) in source.renvois


def comparable(a: ContexteClause, b: ContexteClause) -> Verdict:
    """Ces deux clauses peuvent-elles se contredire ?

    Les branches sont évaluées de la plus précise à la plus large, et la première qui
    accepte donne le motif. L'ordre ne change pas le verdict, seulement son explication —
    et c'est l'explication qui part au journal.
    """
    if _prescriptive(a) and _prescriptive(b):
        return Verdict(
            comparable=True,
            motif=Motif.MODALITE,
            explication=f"modalités prescriptives des deux côtés ({a.modalite}, {b.modalite})",
        )

    communs = sorted(set(a.dimensions_roles) & set(b.dimensions_roles))
    if communs:
        dimension, role = communs[0]
        return Verdict(
            comparable=True,
            motif=Motif.DIMENSION,
            explication=f"même grandeur de part et d'autre ({dimension}, {role})",
        )

    if _renvoie_vers(a, b) or _renvoie_vers(b, a):
        return Verdict(
            comparable=True,
            motif=Motif.RENVOI,
            explication="renvoi explicite d'une clause vers l'autre",
        )

    if a.normes_citees and b.normes_citees:
        # Des référentiels DIVERGENTS suffisent, et sont même le cas intéressant : c'est
        # exactement la forme de I08 (ISO 45001 d'un côté, OHSAS 18001 de l'autre).
        communes = sorted(set(a.normes_citees) & set(b.normes_citees))
        detail = f"référentiel commun : {communes[0]}" if communes else "référentiels divergents"
        return Verdict(
            comparable=True,
            motif=Motif.NORME,
            explication=f"les deux clauses citent un référentiel externe ({detail})",
        )

    partages = set(a.concepts_canoniques) & set(b.concepts_canoniques)
    if len(partages) >= config_ciblage.partages_min():
        return Verdict(
            comparable=True,
            motif=Motif.CONCEPTS,
            explication=f"{len(partages)} concepts canoniques partagés",
        )

    return Verdict(
        comparable=False,
        motif=Motif.AUCUNE_BRANCHE,
        explication=(
            "aucune branche : pas de modalité prescriptive des deux côtés, "
            "pas de grandeur commune, pas de renvoi, pas de référentiel, "
            f"{len(partages)} concept(s) partagé(s) pour {config_ciblage.partages_min()} exigé(s)"
        ),
    )
