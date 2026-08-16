"""detection/portees.py — le test de recouvrement à 4 cas, plus le cinquième.

architecture.md §7.2 : « deux valeurs différentes ne sont une incohérence que si elles
s'appliquent au même périmètre ». C'est la source n°1 de faux positifs, et la v1 s'y était
trompée en traitant « conditions vides d'un côté » comme un recouvrement.

Frames synthétiques, hors ligne. Les cas réels du corpus sont dans `test_a2.py`.
"""

from __future__ import annotations

import pytest

from cohera.detection.portees import (
    RelationPortees,
    portee_effective,
    plus_stricte,
    relation_portees,
)
from cohera.extraction.frames import (
    ClauseFrame,
    Condition,
    Dimension,
    Grandeur,
    Monotonie,
    Operateur,
    StatutGrandeur,
    TypeCondition,
)
from cohera.graphe.conditions import construire_algebre

# ------------------------------------------------------------------------- fabriques


def delai(clause_id: str, secondes: int, *, surface: str = "", conditions=()) -> ClauseFrame:
    return ClauseFrame(
        clause_id=clause_id,
        quantites=[
            Grandeur(
                role="delai", dimension=Dimension.TEMPS, valeur=secondes / 3600,
                unite="heures", valeur_si=secondes, operateur=Operateur.EGAL,
                surface=surface or f"{secondes // 3600} heures",
                monotonie=Monotonie.PLUS_PETIT, statut=StatutGrandeur.NORMAL,
            )
        ],
        conditions=list(conditions),
    )


def spatial(lieu: str) -> Condition:
    return Condition(
        surface=f"en {lieu}", type=TypeCondition.SPATIAL,
        concept_cible=lieu, operateur="APPARTIENT",
    )


def circonstanciel(surface: str) -> Condition:
    return Condition(surface=surface, type=TypeCondition.CIRCONSTANCIEL)


def algebre_de(*frames: ClauseFrame):
    return construire_algebre({f.clause_id: f for f in frames})


# --------------------------------------------------------- la table à 4 cas de §7.2


def test_aucune_condition_des_deux_cotes_donne_des_portees_identiques() -> None:
    """La ligne « Identiques » : I01, I03, I12, I15, N08. Valeur différente ->
    CONTRADICTION, ce que le détecteur en tire."""
    a, b = delai("A", 172800), delai("B", 432000)
    assert relation_portees(a, b, algebre_de(a, b)) is RelationPortees.IDENTIQUE


def test_conditions_spatiales_disjointes_donnent_des_portees_disjointes() -> None:
    """La ligne « Disjointes » : N04. Les deux règles ne se rencontrent jamais, donc aucune
    valeur ne peut en contredire une autre."""
    a = delai("A", 86400, conditions=[spatial("zone A")])
    b = delai("B", 604800, conditions=[spatial("zone de stockage")])
    assert relation_portees(a, b, algebre_de(a, b)) is RelationPortees.DISJOINTE


def test_une_condition_d_un_seul_cote_donne_une_inclusion() -> None:
    """La ligne « Inclusion » : N01. B est conditionnée, A ne l'est pas, donc B ⊂ A."""
    a = delai("A", 172800)
    b = delai("B", 86400, conditions=[circonstanciel("En cas d'accident")])
    assert relation_portees(a, b, algebre_de(a, b)) is RelationPortees.INCLUSION_B_DANS_A
    assert relation_portees(b, a, algebre_de(a, b)) is RelationPortees.INCLUSION_A_DANS_B


def test_deux_conditions_incomparables_donnent_une_portee_indeterminee() -> None:
    """La ligne « Indéterminée » : escalade obligatoire vers l'étage C. Deux
    circonstancielles distinctes se recouvrent peut-être, mais aucune règle typée ne le
    dit — c'est la matière du LLM au J6."""
    a = delai("A", 86400, conditions=[circonstanciel("En cas d'accident grave")])
    b = delai("B", 604800, conditions=[circonstanciel("En cas de sinistre")])
    assert relation_portees(a, b, algebre_de(a, b)) is RelationPortees.INDETERMINEE


def test_la_meme_condition_des_deux_cotes_donne_des_portees_identiques() -> None:
    """I05 : les deux clauses parlent de la zone A. Même périmètre, donc comparables."""
    a = delai("A", 86400, conditions=[spatial("zone A")])
    b = delai("B", 604800, conditions=[spatial("zone A")])
    assert relation_portees(a, b, algebre_de(a, b)) is RelationPortees.IDENTIQUE


def test_une_condition_incluse_dans_l_autre_donne_une_inclusion() -> None:
    """« zone A » ⊂ « site de Radès » : la clause de la zone A est le sous-cas."""
    a = delai("A", 86400, conditions=[spatial("zone A")])
    b = delai("B", 604800, conditions=[spatial("site de Radès")])
    assert relation_portees(a, b, algebre_de(a, b)) is RelationPortees.INCLUSION_A_DANS_B


def test_une_seule_condition_disjointe_suffit_a_disjoindre_les_portees() -> None:
    """La portée d'une clause est la CONJONCTION de ses conditions : si l'une des deux ne
    peut jamais coexister avec une condition d'en face, l'intersection est vide, quel que
    soit ce que disent les autres."""
    a = delai("A", 86400, conditions=[spatial("zone A"), circonstanciel("En cas d'accident")])
    b = delai("B", 604800, conditions=[spatial("zone de stockage")])
    assert relation_portees(a, b, algebre_de(a, b)) is RelationPortees.DISJOINTE


# --------------------------------------------------- la lecture de la monotonie


@pytest.mark.parametrize(
    "monotonie, valeur_a, valeur_b, attendu",
    [
        (Monotonie.PLUS_PETIT, 86400, 172800, "A"),      # delai : 24 h plus strict que 48 h
        (Monotonie.PLUS_PETIT, 172800, 86400, "B"),
        (Monotonie.PLUS_GRAND, 157680000, 94608000, "A"),  # conservation : 5 ans > 3 ans
        (Monotonie.PLUS_GRAND, 94608000, 157680000, "B"),
        (Monotonie.PLUS_PETIT, 86400, 86400, None),
    ],
)
def test_plus_stricte_lit_la_monotonie_du_role(
    monotonie: Monotonie, valeur_a: int, valeur_b: int, attendu: str | None
) -> None:
    """« Plus strict » se lit dans `config/registre_grandeurs.yaml`, jamais en dur
    (`.claude/rules/detection.md`). Les deux sens sont testés, sans quoi on ne saurait pas
    si la monotonie est lue ou si un `<` a été codé en dur."""
    a = delai("A", valeur_a).quantites[0]
    b = delai("B", valeur_b).quantites[0]
    a.monotonie = b.monotonie = monotonie
    assert plus_stricte(a, b, monotonie) == attendu


# ------------------------------ les conditions qui ne font que redire une grandeur


def test_une_condition_qui_redit_la_grandeur_ne_restreint_pas_la_portee() -> None:
    """**Mesuré au J5** : exactement 3 conditions du corpus contiennent la surface d'une
    grandeur de leur propre clause — D1 §7.1 et D2 §7.1 (« pour les interventions réalisées
    à plus de 3 mètres » face à la grandeur « 3 mètres », I13) et D2 §5.5 (« dès lors que
    l'exposition dépasse 80 dB(A) » face à « 80 dB(A) », I14).

    Sans cette règle, I13 devient INDETERMINEE — deux conditions POPULATIONNELLES que rien
    ne compare — et I14 devient une SPÉCIALISATION, puisque seule D2 serait conditionnée et
    qu'elle est la plus stricte. Les deux incohérences disparaîtraient."""
    frame = delai("A", 86400, surface="24 heures",
                  conditions=[circonstanciel("dans un délai de 24 heures maximum")])
    assert portee_effective(frame) == []


def test_une_condition_qui_ne_redit_pas_la_grandeur_reste_une_restriction() -> None:
    """Le cas négatif, et c'est N01 : « En cas d'accident avec arrêt de travail » ne
    contient pas « 24 heures », donc la condition compte bel et bien."""
    frame = delai("B", 86400, surface="24 heures",
                  conditions=[circonstanciel("En cas d'accident avec arrêt de travail")])
    assert len(portee_effective(frame)) == 1
