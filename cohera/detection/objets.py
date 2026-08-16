"""De quoi deux clauses parlent-elles en commun ?

La question que le ciblage ne pose pas. Un canal établit qu'une paire mérite d'être
examinée — même grandeur, cosinus élevé, concepts voisins — jamais qu'elle porte sur le
même objet. C'est pourtant ce que suppose toute comparaison de valeurs : la clé de
comparaison d'architecture.md §5.8 met l'objet canonique en troisième position, à côté de
la dimension et du rôle.

**Pourquoi pas la clé de comparaison elle-même.** Mesuré au J5 : elle ne retient qu'un seul
objet par clause, celui de plus fort IDF, et l'égalité de ce singleton échoue sur I02
(« contrôle des EPI » contre « EPI »), I13 (« intervention réalisée » contre « port du
harnais antichute »), I14, I15 et N01 — cinq cas sur six où il faudrait pourtant conclure.
Un **recouvrement** d'ensembles tolère ces flottements de tête de groupe là où une égalité
de singleton ne le fait pas.

Les identifiants sont ramenés à leur représentant canonique par le pont inter-documents du
J3 : c'est ce qui fait que « EPI » de D1 rencontre « équipements de protection » de D2.
"""

from __future__ import annotations

from cohera.graphe.alias import Pont
from cohera.graphe.concepts import TypeConcept, Vocabulaire


def objets_canoniques(clause_id: str, vocabulaire: Vocabulaire, pont: Pont) -> set[str]:
    """Les concepts de type OBJET de la clause, en représentants canoniques."""
    return {
        pont.canoniques.get(concept.concept_id, concept.concept_id)
        for concept in vocabulaire.concepts_de(clause_id)
        if concept.type is TypeConcept.OBJET
    }


def objets_partages(
    clause_a: str, clause_b: str, vocabulaire: Vocabulaire, pont: Pont
) -> int:
    """Combien d'objets canoniques les deux clauses ont en commun."""
    return len(
        objets_canoniques(clause_a, vocabulaire, pont)
        & objets_canoniques(clause_b, vocabulaire, pont)
    )
