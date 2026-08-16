"""graphe/conditions.py — l'algèbre RECOUVRE / INCLUS_DANS / DISJOINT_DE.

Les **6 cas symboliques** exigés par `plan-1-semaine.md` §J5, plus le cas négatif qui
compte autant : ce que les règles typées ne tranchent pas ne produit pas d'arête, il part
en file d'attente pour le J6.

Fonctions pures, aucun serveur : l'algèbre travaille sur des `Condition` construites à la
main, exactement comme `test_comparabilite.py` travaille sur des `ContexteClause`. La
matérialisation dans Neo4j est vérifiée à part, dans `test_chargeur.py`.
"""

from __future__ import annotations

import pytest

from cohera.extraction.frames import Condition, TypeCondition
from cohera.graphe.conditions import (
    Regle,
    Relation,
    construire_algebre,
    file_attente,
    relation_conditions,
)

# ------------------------------------------------------------------------- fabriques


def spatial(lieu: str, surface: str | None = None) -> Condition:
    return Condition(
        surface=surface if surface is not None else f"en {lieu}",
        type=TypeCondition.SPATIAL,
        concept_cible=lieu,
        operateur="APPARTIENT",
    )


def seuil(operateur: str, valeur: float, surface: str) -> Condition:
    return Condition(
        surface=surface, type=TypeCondition.SEUIL, operateur=operateur, valeur=valeur
    )


def circonstanciel(surface: str) -> Condition:
    return Condition(surface=surface, type=TypeCondition.CIRCONSTANCIEL)


# ------------------------------------------------------- les 6 cas symboliques du plan


def test_cas_1_identite_de_surface_normalisee_recouvre() -> None:
    """« En zone A » et « en zone A » sont la même condition : même `condition_id`, donc
    RECOUVRE. C'est ce qui fait que le corpus n'a qu'une condition « zone A » pour trois
    clauses (D1 §5.2, D1 §5.4, D2 §5.4)."""
    relation, regle = relation_conditions(spatial("zone A", "En zone A"), spatial("zone A", "en zone A"))
    assert relation is Relation.RECOUVRE
    assert regle is Regle.IDENTITE


def test_cas_2_spatial_meme_parent_valeurs_distinctes_disjoint() -> None:
    """« zone A » / « zone de stockage » : deux enfants distincts de « site de Radès ».
    C'est ce qui protège N04 — mêmes objets, périodicités différentes, mais les deux
    règles ne se rencontrent jamais."""
    relation, regle = relation_conditions(spatial("zone A"), spatial("zone de stockage"))
    assert relation is Relation.DISJOINT_DE
    assert regle is Regle.SPATIAL_FRERES


def test_cas_3_spatial_enfant_dans_parent_inclus_dans() -> None:
    """« zone A » ⊂ « site de Radès ». La relation est orientée : de l'inclus vers
    l'incluant."""
    relation, regle = relation_conditions(spatial("zone A"), spatial("site de Radès"))
    assert relation is Relation.INCLUS_DANS
    assert regle is Regle.SPATIAL_HIERARCHIE


def test_cas_4_seuil_de_sens_oppose_disjoint() -> None:
    """« au-delà de 2 m » et « en deçà de 2 m » ne peuvent pas être vraies ensemble."""
    relation, regle = relation_conditions(
        seuil(">", 2.0, "au-delà de 2 mètres"), seuil("<", 2.0, "en deçà de 2 mètres")
    )
    assert relation is Relation.DISJOINT_DE
    assert regle is Regle.SEUIL_SENS_OPPOSE


def test_cas_5_seuil_meme_sens_valeurs_distinctes_inclus_dans() -> None:
    """« au-delà de 5 m » est un sous-cas de « au-delà de 2 m » : tout ce qui dépasse 5 m
    dépasse 2 m."""
    relation, regle = relation_conditions(
        seuil(">", 5.0, "au-delà de 5 mètres"), seuil(">", 2.0, "au-delà de 2 mètres")
    )
    assert relation is Relation.INCLUS_DANS
    assert regle is Regle.SEUIL_MEME_SENS


def test_cas_6_condition_vide_d_un_cote_inclus_dans() -> None:
    """Le cas de N01, et la correction v2 d'architecture.md §7.2 : une clause sans
    condition couvre tous les cas, donc la clause conditionnée est incluse en elle. La v1
    y voyait un recouvrement, donc un conflit — c'est faux."""
    relation, regle = relation_conditions(
        circonstanciel("En cas d'accident avec arrêt de travail"), None
    )
    assert relation is Relation.INCLUS_DANS
    assert regle is Regle.CONDITION_VIDE


def test_cas_6_dans_l_autre_sens() -> None:
    """La condition vide à gauche : c'est l'autre qui est incluse, pas celle-ci."""
    relation, regle = relation_conditions(None, circonstanciel("En cas d'incident grave"))
    assert regle is Regle.CONDITION_VIDE
    assert relation is Relation.INCLUT


def test_deux_conditions_vides_sont_identiques() -> None:
    """Deux clauses sans condition couvrent le même périmètre : c'est le cas IDENTIQUES de
    la table §7.2, celui de I01, I03, I12, I15 et N08."""
    relation, regle = relation_conditions(None, None)
    assert relation is Relation.RECOUVRE
    assert regle is Regle.IDENTITE


# ----------------------------------------------- le cas négatif : ce qu'on ne tranche pas


def test_deux_types_incompatibles_restent_indetermines() -> None:
    """Une condition spatiale et un seuil de durée ne se comparent pas par une règle
    typée. L'architecture réserve ce cas au vecteur puis au LLM (§5.7, niveaux 3 et 4) —
    donc au J6."""
    relation, regle = relation_conditions(
        spatial("zone A"), seuil("<", 30.0, "30 minutes")
    )
    assert relation is Relation.INDETERMINEE
    assert regle is Regle.TYPES_INCOMPATIBLES


def test_un_lieu_inconnu_ne_produit_jamais_une_disjonction() -> None:
    """`.claude/rules/detection.md` : en cas de doute on escalade, on ne rejette pas. Un
    lieu absent de `config/detection.yaml` est une ignorance, pas une disjonction — sans
    quoi deux clauses parlant du même endroit sous deux noms seraient déclarées sans
    rapport, et l'incohérence disparaîtrait en silence."""
    relation, regle = relation_conditions(spatial("zone A"), spatial("atelier de peinture"))
    assert relation is Relation.INDETERMINEE
    assert regle is Regle.LIEU_INCONNU


def test_deux_circonstancielles_distinctes_restent_indeterminees() -> None:
    """« En cas d'accident avec arrêt de travail » et « En cas d'incident grave » se
    recouvrent probablement, mais aucune règle typée ne le dit. C'est exactement la
    matière du LLM au J6."""
    relation, _ = relation_conditions(
        circonstanciel("En cas d'accident avec arrêt de travail"),
        circonstanciel("En cas d'incident grave"),
    )
    assert relation is Relation.INDETERMINEE


# ------------------------------------------------------------------------- symétrie


@pytest.mark.parametrize(
    "a, b",
    [
        (spatial("zone A"), spatial("zone de stockage")),
        (spatial("zone A"), spatial("zone A")),
        (seuil(">", 2.0, "au-delà de 2 m"), seuil("<", 2.0, "en deçà de 2 m")),
    ],
)
def test_les_relations_symetriques_le_sont_vraiment(a: Condition, b: Condition) -> None:
    """RECOUVRE et DISJOINT_DE ne dépendent pas de l'ordre des arguments. Si elles en
    dépendaient, l'arête écrite dans le graphe dépendrait de l'ordre d'itération des
    frames, et le chargement cesserait d'être idempotent."""
    assert relation_conditions(a, b)[0] is relation_conditions(b, a)[0]


def test_l_inclusion_s_inverse_quand_on_echange_les_arguments() -> None:
    """INCLUS_DANS est orientée : l'échanger doit donner INCLUT, pas INCLUS_DANS."""
    assert relation_conditions(spatial("zone A"), spatial("site de Radès"))[0] is Relation.INCLUS_DANS
    assert relation_conditions(spatial("site de Radès"), spatial("zone A"))[0] is Relation.INCLUT


def test_un_synonyme_de_lieu_recouvre_sa_forme_retenue() -> None:
    """« sur l'ensemble du site » désigne le site entier. Sans la table de synonymes il
    serait un frère de « zone A », donc DISJOINT à tort — et I04 (D2 §7.4 « interdite sur
    l'ensemble du site ») cesserait d'être comparable à D1 §7.4."""
    assert relation_conditions(spatial("l'ensemble du site"), spatial("site de Radès"))[0] is Relation.RECOUVRE
    assert relation_conditions(spatial("zone A"), spatial("l'ensemble du site"))[0] is Relation.INCLUS_DANS


# ---------------------------------------------------------------- l'algèbre du corpus


def test_l_algebre_dedoublonne_par_condition_id(frames) -> None:
    """Le rendement d'architecture.md §5.7 : le recouvrement se calcule une fois par paire
    de conditions DISTINCTES, pas une fois par paire de clauses. « En zone A » apparaît
    dans trois clauses et ne compte qu'une fois."""
    algebre = construire_algebre(frames)
    identifiants = {c for paire in algebre.aretes for c in (paire.condition_a, paire.condition_b)}
    assert len(algebre.conditions) < sum(len(f.conditions) for f in frames.values())
    assert identifiants <= set(algebre.conditions)


def test_l_algebre_n_ecrit_aucune_arete_indeterminee(frames) -> None:
    """Une relation indéterminée n'est pas une arête du graphe : c'est une ligne de la file
    d'attente du J6."""
    algebre = construire_algebre(frames)
    assert all(arete.relation is not Relation.INDETERMINEE for arete in algebre.aretes)
    assert file_attente(algebre), "aucune paire en file d'attente : le J6 n'aurait rien à faire"


def test_la_file_d_attente_s_ecrit_et_se_relit(frames, tmp_path) -> None:
    """Le J6 consommera ce fichier comme il consommera `zone_grise.jsonl` : une paire par
    ligne, avec les deux surfaces et le motif pour que l'arbitrage soit lisible sans
    rejouer le pipeline."""
    import json

    from cohera.graphe.conditions import ecrire_file_attente

    algebre = construire_algebre(frames)
    chemin = ecrire_file_attente(algebre, tmp_path / "file.jsonl")

    lignes = [json.loads(l) for l in chemin.read_text("utf-8").splitlines() if l]
    assert len(lignes) == len(algebre.indeterminees)
    assert all({"surface_a", "surface_b", "type_a", "type_b", "motif"} <= set(l) for l in lignes)


def test_zone_a_et_zone_de_stockage_sont_disjointes_dans_le_corpus(frames) -> None:
    """N04 au niveau de l'algèbre, sur les conditions réellement extraites du corpus et
    non sur des fabriques de test. Les deux surfaces sont celles de D1 §5.2 et D2 §5.2."""
    algebre = construire_algebre(frames)
    zone_a = spatial("zone A", "En zone A")
    stockage = spatial("zone de stockage", "En zone de stockage")
    assert algebre.relation(zone_a, stockage) is Relation.DISJOINT_DE
