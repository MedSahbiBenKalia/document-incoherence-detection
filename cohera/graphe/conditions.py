"""Algèbre des conditions : RECOUVRE, INCLUS_DANS, DISJOINT_DE.

C'est ce qui distingue une vraie contradiction d'une spécialisation compatible
(N01) ou de deux règles qui ne se rencontrent jamais (N04).

**Règles typées uniquement** — architecture.md §5.7, niveaux 1 et 2. Identité de surface
normalisée, hiérarchie des lieux, sens des seuils, condition vide. Le niveau 3 (vecteur,
cos ≥ 0,90 / < 0,55) et le niveau 4 (LLM sur zone grise) sont le J6 : tout ce que les
règles ne tranchent pas rend `INDETERMINEE`, **ne produit aucune arête**, et part en file
d'attente. Une ignorance n'est jamais convertie en disjonction — un rejet est définitif et
silencieux, une escalade reste visible (`.claude/rules/detection.md`).

**Le rendement.** Les conditions se dédupliquent à travers tout le corpus : la relation se
calcule une fois par paire de conditions *distinctes*, pas une fois par paire de clauses.
Les nœuds `Condition` sont déjà chargés sous cette identité depuis le J3
(`chargeur.py::_charger_conditions`, `condition_id(surface, type)` sans `clause_id`) ; ce
module réutilise la même fonction d'identité, sans quoi les arêtes viseraient des nœuds
qui n'existent pas. Mesuré sur les fixtures : 23 conditions distinctes pour 78 clauses,
soit 253 paires à trancher au lieu de 1517.

**Fonction pure.** Aucune dépendance à Neo4j en dehors de :func:`materialiser`, qui est la
seule à prendre une session. L'algèbre elle-même se teste hors ligne, comme
`ciblage/comparabilite.py`.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from neo4j import Session
from pydantic import BaseModel, Field

from cohera import reglages
from cohera.extraction.frames import ClauseFrame, Condition, TypeCondition
from cohera.graphe.libelles import normaliser_libelle

# ------------------------------------------------------------------------ vocabulaire


class Relation(StrEnum):
    """La relation d'une condition A vers une condition B.

    ``INCLUT`` est l'inverse d'``INCLUS_DANS`` : elle n'est pas un type d'arête du graphe,
    seulement la façon dont :func:`relation_conditions` rend une inclusion vue depuis
    l'autre bout. La matérialisation la retourne pour n'écrire qu'un seul sens.
    """

    RECOUVRE = "RECOUVRE"
    INCLUS_DANS = "INCLUS_DANS"
    INCLUT = "INCLUT"
    DISJOINT_DE = "DISJOINT_DE"
    INDETERMINEE = "INDETERMINEE"


class Regle(StrEnum):
    """Quelle règle typée a tranché — ou pourquoi aucune n'a pu.

    Portée par chaque arête et par chaque ligne de la file d'attente : un rejet comme une
    escalade est journalisé avec son motif.
    """

    IDENTITE = "IDENTITE"
    CONDITION_VIDE = "CONDITION_VIDE"
    SPATIAL_FRERES = "SPATIAL_FRERES"
    SPATIAL_HIERARCHIE = "SPATIAL_HIERARCHIE"
    SEUIL_SENS_OPPOSE = "SEUIL_SENS_OPPOSE"
    SEUIL_MEME_SENS = "SEUIL_MEME_SENS"
    TYPES_INCOMPATIBLES = "TYPES_INCOMPATIBLES"
    LIEU_INCONNU = "LIEU_INCONNU"
    AUCUNE_REGLE_TYPEE = "AUCUNE_REGLE_TYPEE"


#: Les relations qui deviennent une arête du graphe. `INDETERMINEE` n'en est pas.
RELATIONS_MATERIALISEES = (Relation.RECOUVRE, Relation.INCLUS_DANS, Relation.DISJOINT_DE)

#: Relations invariantes par échange des deux arguments — donc à orienter arbitrairement
#: mais de façon déterministe, sans quoi un second chargement écrirait l'arête inverse.
RELATIONS_SYMETRIQUES = (Relation.RECOUVRE, Relation.DISJOINT_DE)


# ----------------------------------------------------------------------- configuration


@lru_cache(maxsize=1)
def _conditions_config() -> dict:
    return reglages.charger_config("detection").get("conditions", {})


@lru_cache(maxsize=1)
def _synonymes_de_lieu() -> dict[str, str]:
    bruts = _conditions_config().get("lieux", {}).get("synonymes", {}) or {}
    return {normaliser_libelle(k): normaliser_libelle(v) for k, v in bruts.items()}


@lru_cache(maxsize=1)
def _parents_de_lieu() -> dict[str, str | None]:
    bruts = _conditions_config().get("lieux", {}).get("parents", {}) or {}
    return {
        normaliser_libelle(k): (normaliser_libelle(v) if v else None)
        for k, v in bruts.items()
    }


def ignorer_les_conditions_qui_redisent_une_grandeur() -> bool:
    return bool(_conditions_config().get("ignorer_les_conditions_qui_redisent_une_grandeur", True))


def vider_caches() -> None:
    """Oublie la configuration mémorisée. À appeler après un `monkeypatch` de config."""
    _conditions_config.cache_clear()
    _synonymes_de_lieu.cache_clear()
    _parents_de_lieu.cache_clear()


# ------------------------------------------------------------------------- identité


def condition_id(surface: str, type_condition: str) -> str:
    """Réexport de l'identité du chargeur, pour que ce module n'en invente pas une autre.

    Les arêtes d'algèbre visent les nœuds `Condition` écrits au J3 : si les deux modules
    calculaient l'empreinte différemment, `MATCH` ne trouverait rien et l'algèbre serait
    silencieusement vide.
    """
    from cohera.graphe.chargeur import condition_id as identite

    return identite(surface, type_condition)


def _identite(condition: Condition) -> str:
    return condition_id(condition.surface, condition.type.value)


# --------------------------------------------------------------------- règles typées


def _lieu_normalise(condition: Condition) -> str | None:
    cible = condition.concept_cible or condition.surface
    normalise = normaliser_libelle(cible)
    return _synonymes_de_lieu().get(normalise, normalise) or None


def _ascendants(lieu: str) -> list[str]:
    """La chaîne des parents d'un lieu, du plus proche à la racine. Vide si inconnu."""
    parents = _parents_de_lieu()
    if lieu not in parents:
        return []
    chaine: list[str] = []
    courant = parents[lieu]
    while courant is not None and courant not in chaine:
        chaine.append(courant)
        courant = parents.get(courant)
    return chaine


def _relation_spatiale(a: Condition, b: Condition) -> tuple[Relation, Regle]:
    lieu_a, lieu_b = _lieu_normalise(a), _lieu_normalise(b)
    parents = _parents_de_lieu()

    if lieu_a is None or lieu_b is None:
        return Relation.INDETERMINEE, Regle.LIEU_INCONNU
    if lieu_a == lieu_b:
        return Relation.RECOUVRE, Regle.IDENTITE
    if lieu_a not in parents or lieu_b not in parents:
        return Relation.INDETERMINEE, Regle.LIEU_INCONNU

    if lieu_b in _ascendants(lieu_a):
        return Relation.INCLUS_DANS, Regle.SPATIAL_HIERARCHIE
    if lieu_a in _ascendants(lieu_b):
        return Relation.INCLUT, Regle.SPATIAL_HIERARCHIE
    if parents[lieu_a] is not None and parents[lieu_a] == parents[lieu_b]:
        return Relation.DISJOINT_DE, Regle.SPATIAL_FRERES
    return Relation.INDETERMINEE, Regle.AUCUNE_REGLE_TYPEE


#: Sens d'un opérateur de seuil : +1 borne par le bas, -1 borne par le haut.
_SENS = {">": 1, "≥": 1, "<": -1, "≤": -1}


def _relation_seuil(a: Condition, b: Condition) -> tuple[Relation, Regle]:
    sens_a, sens_b = _SENS.get(a.operateur or ""), _SENS.get(b.operateur or "")
    if sens_a is None or sens_b is None or a.valeur is None or b.valeur is None:
        return Relation.INDETERMINEE, Regle.AUCUNE_REGLE_TYPEE

    if sens_a != sens_b:
        # « au-delà de 2 m » et « en deçà de 2 m » : aucune situation ne satisfait les deux.
        # Sur des bornes qui se chevauchent (« > 2 » et « < 5 »), l'intersection n'est pas
        # vide et aucune règle typée ne dit laquelle inclut l'autre.
        if (sens_a > 0 and a.valeur >= b.valeur) or (sens_b > 0 and b.valeur >= a.valeur):
            return Relation.DISJOINT_DE, Regle.SEUIL_SENS_OPPOSE
        return Relation.INDETERMINEE, Regle.AUCUNE_REGLE_TYPEE

    if a.valeur == b.valeur:
        return Relation.RECOUVRE, Regle.IDENTITE
    # Même sens : la borne la plus exigeante décrit le sous-ensemble.
    plus_restrictif_est_a = (a.valeur > b.valeur) if sens_a > 0 else (a.valeur < b.valeur)
    relation = Relation.INCLUS_DANS if plus_restrictif_est_a else Relation.INCLUT
    return relation, Regle.SEUIL_MEME_SENS


_REGLES_PAR_TYPE = {
    TypeCondition.SPATIAL: _relation_spatiale,
    TypeCondition.SEUIL: _relation_seuil,
}


def relation_conditions(
    a: Condition | None, b: Condition | None
) -> tuple[Relation, Regle]:
    """La relation de ``a`` vers ``b``, et la règle typée qui l'a tranchée.

    ``None`` représente l'absence de condition. Deux absences se recouvrent ; une absence
    face à une condition rend l'autre incluse — c'est la correction v2 d'architecture.md
    §7.2, celle qui fait de N01 une spécialisation et non un conflit.
    """
    if a is None and b is None:
        return Relation.RECOUVRE, Regle.IDENTITE
    if b is None:
        return Relation.INCLUS_DANS, Regle.CONDITION_VIDE
    if a is None:
        return Relation.INCLUT, Regle.CONDITION_VIDE

    if _identite(a) == _identite(b):
        return Relation.RECOUVRE, Regle.IDENTITE
    if a.type is not b.type:
        return Relation.INDETERMINEE, Regle.TYPES_INCOMPATIBLES

    regle = _REGLES_PAR_TYPE.get(a.type)
    if regle is None:
        return Relation.INDETERMINEE, Regle.AUCUNE_REGLE_TYPEE
    return regle(a, b)


# ----------------------------------------------------------------------- l'algèbre


class AreteCondition(BaseModel):
    """Une relation matérialisable entre deux conditions distinctes."""

    condition_a: str
    condition_b: str
    relation: Relation
    regle: Regle
    surface_a: str = ""
    surface_b: str = ""


class PaireIndeterminee(BaseModel):
    """Une paire que les règles typées n'ont pas tranchée — la matière du J6."""

    condition_a: str
    condition_b: str
    surface_a: str
    surface_b: str
    type_a: str
    type_b: str
    motif: Regle


class Algebre(BaseModel):
    """Toutes les relations entre les conditions distinctes d'un corpus.

    Auditable de bout en bout, comme le :class:`~cohera.ciblage.Ciblage` du J4 : on garde
    les arêtes *et* ce qui n'a pas pu être tranché.
    """

    conditions: dict[str, Condition] = Field(default_factory=dict)
    aretes: list[AreteCondition] = Field(default_factory=list)
    indeterminees: list[PaireIndeterminee] = Field(default_factory=list)

    def relation(self, a: Condition | None, b: Condition | None) -> Relation:
        """La relation stockée entre deux conditions, ou celle que les règles rendraient.

        Les conditions vides ne sont pas des nœuds : leur cas est tranché à la volée.
        """
        if a is None or b is None:
            return relation_conditions(a, b)[0]

        ia, ib = _identite(a), _identite(b)
        if ia == ib:
            return Relation.RECOUVRE
        for arete in self.aretes:
            if (arete.condition_a, arete.condition_b) == (ia, ib):
                return arete.relation
            if (arete.condition_a, arete.condition_b) == (ib, ia):
                return _inverse(arete.relation)
        return Relation.INDETERMINEE

    @property
    def par_relation(self) -> dict[str, int]:
        comptes: dict[str, int] = {}
        for arete in self.aretes:
            comptes[arete.relation.value] = comptes.get(arete.relation.value, 0) + 1
        return comptes


def _inverse(relation: Relation) -> Relation:
    if relation is Relation.INCLUS_DANS:
        return Relation.INCLUT
    if relation is Relation.INCLUT:
        return Relation.INCLUS_DANS
    return relation


def construire_algebre(frames: dict[str, ClauseFrame]) -> Algebre:
    """Toutes les paires de conditions distinctes du corpus, tranchées une fois.

    Les paires indéterminées ne deviennent pas des arêtes : elles sont conservées à part,
    pour que :func:`file_attente` les rende au J6.
    """
    distinctes: dict[str, Condition] = {}
    for frame in frames.values():
        for condition in frame.conditions:
            distinctes.setdefault(_identite(condition), condition)

    aretes: list[AreteCondition] = []
    indeterminees: list[PaireIndeterminee] = []

    identifiants = sorted(distinctes)
    for indice, ia in enumerate(identifiants):
        for ib in identifiants[indice + 1 :]:
            a, b = distinctes[ia], distinctes[ib]
            relation, regle = relation_conditions(a, b)

            if relation is Relation.INDETERMINEE:
                indeterminees.append(
                    PaireIndeterminee(
                        condition_a=ia, condition_b=ib,
                        surface_a=a.surface, surface_b=b.surface,
                        type_a=a.type.value, type_b=b.type.value, motif=regle,
                    )
                )
                continue

            # `INCLUT` est retournée pour n'écrire qu'un seul sens dans le graphe ; les
            # relations symétriques sont orientées par l'ordre des identifiants, déjà
            # garanti croissant par la boucle.
            if relation is Relation.INCLUT:
                aretes.append(
                    AreteCondition(
                        condition_a=ib, condition_b=ia, relation=Relation.INCLUS_DANS,
                        regle=regle, surface_a=b.surface, surface_b=a.surface,
                    )
                )
            else:
                aretes.append(
                    AreteCondition(
                        condition_a=ia, condition_b=ib, relation=relation, regle=regle,
                        surface_a=a.surface, surface_b=b.surface,
                    )
                )

    return Algebre(conditions=distinctes, aretes=aretes, indeterminees=indeterminees)


def file_attente(algebre: Algebre) -> list[PaireIndeterminee]:
    """Les paires que les règles typées n'ont pas tranchées, pour le J6."""
    return algebre.indeterminees


def chemin_file_attente() -> Path:
    """`file_attente_conditions.jsonl` à la racine — consommé par le J6, comme
    `zone_grise.jsonl` l'est pour les alias."""
    return reglages.racine_projet() / "file_attente_conditions.jsonl"


def ecrire_file_attente(algebre: Algebre, chemin: Path | None = None) -> Path:
    """Écrit les paires indéterminées, une par ligne JSON."""
    chemin = chemin or chemin_file_attente()
    lignes = (paire.model_dump_json() for paire in file_attente(algebre))
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


# ------------------------------------------------------------------- matérialisation


def materialiser(session: Session, algebre: Algebre) -> int:
    """Écrit les arêtes d'algèbre dans Neo4j. **MERGE, jamais CREATE.**

    Le type de relation ne peut pas être paramétré en Cypher : une requête par type, ce
    qui reste trois requêtes pour tout le corpus.
    """
    total = 0
    for relation in RELATIONS_MATERIALISEES:
        lignes = [
            {"a": arete.condition_a, "b": arete.condition_b, "regle": arete.regle.value}
            for arete in algebre.aretes
            if arete.relation is relation
        ]
        if not lignes:
            continue
        session.run(
            f"UNWIND $paires AS p\n"
            f"MATCH (a:Condition {{condition_id: p.a}}), (b:Condition {{condition_id: p.b}})\n"
            f"MERGE (a)-[r:{relation.value}]->(b)\n"
            f"SET r.regle = p.regle",
            paires=lignes,
        )
        total += len(lignes)
    return total
