"""Schémas et chargement des configurations du pont inter-documents (J3).

Délibérément séparé de `cohera/extraction/config.py`. Celui-ci valide les sections J2 de
`config/lexique_qhse.yaml` avec `extra="ignore"`, et `tests/test_extraction_config.py`
asserte que `LexiqueExtraction` n'expose PAS `alias` — un oubli volontaire, pas un défaut.
Y ajouter les clés du J3 casserait un test vert. On lit donc le même fichier deux fois,
avec deux modèles qui ne se marchent pas dessus.

Ce module ne contient aucune valeur métier : seuils, groupes d'alias et liste noire vivent
tous dans `config/*.yaml` (règle de `CLAUDE.md`). Il n'en porte que la *forme*, et les
garde-fous qui font échouer le chargement plutôt que de laisser passer une configuration
incohérente — une liste noire qui contredit un groupe d'alias, ou une bande de zone grise
inversée, se paierait en faux positifs silencieux bien plus tard.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cohera import reglages
from cohera.graphe.libelles import normaliser_libelle

#: Score attribué à un alias issu du lexique métier (architecture.md §5.6).
SCORE_LEXIQUE = 0.95

#: Score d'un alias par identité normalisée.
SCORE_EXACT = 1.00


# ------------------------------------------------------------------ groupes d'équivalence


class GroupeAlias(BaseModel):
    """Un groupe de termes désignant la même chose -> ALIAS_DE {LEXIQUE, 0.95}.

    `note` n'est pas décorative : le rapport du J7 doit exposer chaque alias comme une
    hypothèse d'alignement révisable par un auditeur, donc justifiée.
    """

    termes: list[str] = Field(min_length=2)
    note: str = ""

    def paires(self) -> list[tuple[str, str]]:
        """Toutes les paires du groupe. L'union-find recollera la classe d'équivalence."""
        return [
            (a, b)
            for i, a in enumerate(self.termes)
            for b in self.termes[i + 1 :]
        ]


class GroupeActeurs(BaseModel):
    """Équivalence entre rôles QHSE — `config/gazetteer_acteurs.yaml`."""

    roles: list[str] = Field(min_length=2)
    note: str = ""

    def paires(self) -> list[tuple[str, str]]:
        return GroupeAlias(termes=self.roles, note=self.note).paires()


class PaireNoire(BaseModel):
    """Une paire qui ne doit jamais produire d'arête, quel que soit le cosinus."""

    paire: tuple[str, str]
    note: str = ""


# -------------------------------------------------------------------------------- seuils


class SeuilsAlias(BaseModel):
    """Les trois réglages de la cascade vectorielle (architecture.md §5.6)."""

    alias_vecteur: float = Field(ge=0.0, le=1.0)
    zone_grise_min: float = Field(ge=0.0, le=1.0)
    zone_grise_budget: int = Field(ge=0)

    @model_validator(mode="after")
    def _bande_coherente(self) -> SeuilsAlias:
        if self.zone_grise_min >= self.alias_vecteur:
            raise ValueError(
                f"Bande de zone grise vide ou inversée : zone_grise_min="
                f"{self.zone_grise_min} >= alias_vecteur={self.alias_vecteur}. "
                "Attendu zone_grise_min < alias_vecteur (architecture.md §5.6)."
            )
        return self


# ------------------------------------------------------------------------------ le tout


class ConfigAlias(BaseModel):
    """Les trois clés J3 de `config/lexique_qhse.yaml`."""

    model_config = ConfigDict(extra="ignore")

    alias: list[GroupeAlias] = Field(default_factory=list)
    liste_noire: list[PaireNoire] = Field(default_factory=list)
    seuils: SeuilsAlias

    @model_validator(mode="after")
    def _pas_de_contradiction(self) -> ConfigAlias:
        """Un même couple ne peut pas être à la fois alias et sur la liste noire.

        La comparaison se fait sur les libellés normalisés, parce que c'est sur eux que le
        veto s'appliquera : « Casque » et « casque » doivent se voir comme une seule et
        même contradiction.
        """
        interdites = {
            frozenset((normaliser_libelle(a), normaliser_libelle(b)))
            for entree in self.liste_noire
            for a, b in (entree.paire,)
        }
        for groupe in self.alias:
            for a, b in groupe.paires():
                couple = frozenset((normaliser_libelle(a), normaliser_libelle(b)))
                if couple in interdites:
                    raise ValueError(
                        f"Configuration contradictoire : {a!r} et {b!r} sont déclarés "
                        "alias ET présents sur la liste noire. Trancher dans "
                        "config/lexique_qhse.yaml."
                    )
        return self


class GazetteerActeurs(BaseModel):
    """`config/gazetteer_acteurs.yaml` — équivalences entre rôles uniquement."""

    model_config = ConfigDict(extra="ignore")

    acteurs: list[GroupeActeurs] = Field(default_factory=list)


# --------------------------------------------------------------------------- chargement


@lru_cache(maxsize=1)
def charger_config_alias() -> ConfigAlias:
    return ConfigAlias.model_validate(reglages.charger_config("lexique_qhse"))


@lru_cache(maxsize=1)
def charger_gazetteer_acteurs() -> GazetteerActeurs:
    return GazetteerActeurs.model_validate(reglages.charger_config("gazetteer_acteurs"))


@lru_cache(maxsize=1)
def paires_lexicales() -> tuple[tuple[str, str], ...]:
    """Toutes les paires d'équivalence déclarées, lexique et gazetteer confondus.

    Les deux fichiers alimentent le même niveau 2 de la cascade : le pont ne distingue pas
    un synonyme d'objet d'un synonyme de rôle, seule la méthode enregistrée compte.
    """
    groupes: list[tuple[str, str]] = []
    for groupe in charger_config_alias().alias:
        groupes.extend(groupe.paires())
    for groupe in charger_gazetteer_acteurs().acteurs:
        groupes.extend(groupe.paires())
    return tuple(groupes)


@lru_cache(maxsize=1)
def couples_interdits() -> frozenset[frozenset[str]]:
    """La liste noire, normalisée et symétrique, prête pour un test d'appartenance."""
    return frozenset(
        frozenset((normaliser_libelle(a), normaliser_libelle(b)))
        for entree in charger_config_alias().liste_noire
        for a, b in (entree.paire,)
    )


def vider_caches() -> None:
    """Oublie les configurations mémorisées. Utile en test après un `monkeypatch`."""
    charger_config_alias.cache_clear()
    charger_gazetteer_acteurs.cache_clear()
    paires_lexicales.cache_clear()
    couples_interdits.cache_clear()
