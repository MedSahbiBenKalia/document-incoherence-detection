"""Test de recouvrement des portées.

Sans lui, N01 devient un faux positif : mêmes clés, valeurs différentes, mais la
portée de D2 §4.6 est incluse dans celle de D1 §4.2 avec une contrainte plus
stricte — c'est une spécialisation compatible, pas une contradiction.

La table à quatre cas d'architecture.md §7.2, plus le cinquième que la v2 ajoute :

===================== ============================== =========================
 relation des portées   contrainte de la restreinte    verdict
===================== ============================== =========================
 identiques             valeur différente              CONTRADICTION
 disjointes             quelconque                     aucun conflit
 inclusion (B ⊂ A)      plus stricte                   SPÉCIALISATION
 inclusion (B ⊂ A)      plus permissive                CONTRADICTION
 indéterminée           quelconque                     escalade étage C
===================== ============================== =========================

La relation est **lue** dans l'algèbre (`graphe/conditions.py`), calculée une fois pour
toutes sur les conditions distinctes du corpus. Le sens de « plus strict » est **lu** dans
`config/registre_grandeurs.yaml`, dénormalisé sur chaque grandeur à l'extraction — jamais
un `<` codé en dur (`.claude/rules/detection.md`).

**La portée d'une clause est la conjonction de ses conditions.** Une seule condition
disjointe d'en face suffit donc à vider l'intersection, quelles que soient les autres.
"""

from __future__ import annotations

from enum import StrEnum

from cohera.extraction.frames import ClauseFrame, Condition, Grandeur, Monotonie
from cohera.graphe.conditions import (
    Algebre,
    Relation,
    ignorer_les_conditions_qui_redisent_une_grandeur,
)


class RelationPortees(StrEnum):
    IDENTIQUE = "IDENTIQUE"
    DISJOINTE = "DISJOINTE"
    INCLUSION_A_DANS_B = "INCLUSION_A_DANS_B"
    INCLUSION_B_DANS_A = "INCLUSION_B_DANS_A"
    INDETERMINEE = "INDETERMINEE"


# --------------------------------------------------------------- la portée effective


def portee_effective(frame: ClauseFrame) -> list[Condition]:
    """Les conditions de la clause qui restreignent réellement sa portée.

    Une condition dont la surface **contient** celle d'une grandeur de la même clause ne
    restreint rien : elle redit la grandeur. « pour les interventions réalisées à plus de
    3 mètres » et la grandeur « 3 mètres » sont la même contrainte vue par deux
    extracteurs — `regles/grandeurs.py` en fait un `seuil_declenchement`,
    `regles/conditions.py` en refait une condition POPULATIONNELLE.

    Sans ce tri, I13 et I14 disparaissent : voir le commentaire de
    `config/detection.yaml`, section `conditions`, où le chiffre est consigné.
    """
    if not ignorer_les_conditions_qui_redisent_une_grandeur():
        return list(frame.conditions)

    surfaces = [q.surface for q in frame.quantites if q.surface]
    return [
        condition
        for condition in frame.conditions
        if not any(surface in condition.surface for surface in surfaces)
    ]


# ---------------------------------------------------------------- relation des portées


def _couvre_tout(
    conditions: list[Condition], face: list[Condition], algebre: Algebre
) -> bool:
    """Chaque condition de ``conditions`` est-elle incluse dans une condition d'en face ?

    C'est ce qui fait de ``conditions`` la portée la plus restreinte : chacune de ses
    contraintes est au moins aussi forte qu'une contrainte de l'autre côté.
    """
    return all(
        any(
            algebre.relation(condition, autre) in (Relation.INCLUS_DANS, Relation.RECOUVRE)
            for autre in face
        )
        for condition in conditions
    )


def relation_portees(
    frame_a: ClauseFrame, frame_b: ClauseFrame, algebre: Algebre
) -> RelationPortees:
    """La relation des périmètres d'application de deux clauses."""
    conditions_a = portee_effective(frame_a)
    conditions_b = portee_effective(frame_b)

    if not conditions_a and not conditions_b:
        return RelationPortees.IDENTIQUE
    if not conditions_b:
        return RelationPortees.INCLUSION_A_DANS_B
    if not conditions_a:
        return RelationPortees.INCLUSION_B_DANS_A

    # Une seule disjonction vide l'intersection de la conjonction entière.
    if any(
        algebre.relation(a, b) is Relation.DISJOINT_DE
        for a in conditions_a
        for b in conditions_b
    ):
        return RelationPortees.DISJOINTE

    a_dans_b = _couvre_tout(conditions_a, conditions_b, algebre)
    b_dans_a = _couvre_tout(conditions_b, conditions_a, algebre)

    if a_dans_b and b_dans_a:
        return RelationPortees.IDENTIQUE
    if a_dans_b:
        return RelationPortees.INCLUSION_A_DANS_B
    if b_dans_a:
        return RelationPortees.INCLUSION_B_DANS_A
    return RelationPortees.INDETERMINEE


# ----------------------------------------------------------------- « plus strict »


def plus_stricte(
    quantite_a: Grandeur, quantite_b: Grandeur, monotonie: Monotonie
) -> str | None:
    """Laquelle des deux valeurs est la plus stricte : ``"A"``, ``"B"``, ou ``None``.

    ``monotonie`` nomme le sens dans lequel la contrainte se durcit, tel que le déclare
    `config/registre_grandeurs.yaml` : ``PLUS_PETIT`` pour un délai, ``PLUS_GRAND`` pour
    une durée de conservation.
    """
    if quantite_a.valeur_si is None or quantite_b.valeur_si is None:
        return None
    if quantite_a.valeur_si == quantite_b.valeur_si:
        return None
    if monotonie is Monotonie.PLUS_PETIT:
        return "A" if quantite_a.valeur_si < quantite_b.valeur_si else "B"
    return "A" if quantite_a.valeur_si > quantite_b.valeur_si else "B"


def plus_permissive(
    quantite_a: Grandeur, quantite_b: Grandeur, monotonie: Monotonie
) -> str | None:
    """L'inverse de :func:`plus_stricte` — c'est elle qui désigne la clause fautive."""
    stricte = plus_stricte(quantite_a, quantite_b, monotonie)
    if stricte is None:
        return None
    return "B" if stricte == "A" else "A"
