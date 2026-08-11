"""Schémas et chargement des configurations métier du J2.

Distinct de `frames.py`, qui ne décrit que la forme d'une Clause Frame : ici vivent les
modèles pydantic qui valident la *forme du lexique* (`config/registre_grandeurs.yaml`,
`config/lexique_qhse.yaml`) et les fonctions qui les chargent, mises en cache comme
`reglages.charger()`. `.claude/rules/extraction.md` — « une grandeur sans monotonie fait
échouer le chargement de la configuration » — est appliqué ici : `RoleGrandeur.monotonie`
n'a pas de défaut, donc `RegistreGrandeurs.model_validate(...)` lève si un rôle l'omet.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from cohera import reglages
from cohera.extraction.frames import Modalite, Operateur, RegistreGrandeurs, TypeCondition

# ------------------------------------------------------------------------ qualification


class EntreeDeontique(BaseModel):
    marqueur: str
    modalite: Modalite
    force: int | None = None


class Qualification(BaseModel):
    marqueurs_deontiques: list[EntreeDeontique]
    verbes_definitionnels: list[str]
    motif_terme_defini: str
    motif_definition_copule: str
    motifs_reference: list[str]
    motifs_grandeur: list[str]


# ---------------------------------------------------------------------------- grandeurs


class OperateurSeuil(BaseModel):
    motif: str
    operateur: Operateur


class DelaiImprecis(BaseModel):
    motif: str
    valeur_si: int


class Periodicite(BaseModel):
    jours: int | None = None
    mois: int | None = None
    ambigu: bool = False


class ConfigGrandeurs(BaseModel):
    contextes_role: dict[str, list[str]]
    operateurs_seuil: list[OperateurSeuil]
    nombres_lettres: dict[str, int]
    constantes_temps: dict[str, int]
    periodicites: dict[str, Periodicite]
    delais_imprecis: list[DelaiImprecis]
    noms_periode: dict[str, str]


# --------------------------------------------------------------------------- conditions


class MarqueurCondition(BaseModel):
    motif: str
    type: TypeCondition


class ConfigConditions(BaseModel):
    marqueurs: list[MarqueurCondition]


# ----------------------------------------------------------------------------- négation


class Negation(BaseModel):
    particules: list[str]
    inversion: dict[str, str]


# ------------------------------------------------------------------- références croisées


class ReferencesCroisees(BaseModel):
    connecteurs_document: list[str]
    connecteurs_soi_meme: list[str]


# --------------------------------------------------------------------------------- dates


class ConfigDates(BaseModel):
    mois: dict[str, int]


class ConfigValidite(BaseModel):
    marqueurs_debut: list[str]
    marqueurs_fin: list[str]


class ConfigDerogation(BaseModel):
    marqueurs: list[str]
    marqueurs_justification: list[str]
    marqueurs_approbateur: list[str]
    marqueurs_echeance: list[str]


# ------------------------------------------------------------------------------ le tout


class LexiqueExtraction(BaseModel):
    """`config/lexique_qhse.yaml`, côté sections J2. `extra="ignore"` : le fichier porte
    aussi `alias`/`liste_noire`/`seuils`, non typés et réservés au J3."""

    model_config = ConfigDict(extra="ignore")

    qualification: Qualification
    gazetteer_roles: list[str]
    grandeurs: ConfigGrandeurs
    conditions: ConfigConditions
    negation: Negation
    references_croisees: ReferencesCroisees
    dates: ConfigDates
    validite: ConfigValidite
    derogation: ConfigDerogation


# -------------------------------------------------------------------------- chargement


@lru_cache(maxsize=1)
def charger_registre_grandeurs() -> RegistreGrandeurs:
    return RegistreGrandeurs.model_validate(reglages.charger_config("registre_grandeurs"))


@lru_cache(maxsize=1)
def charger_lexique_extraction() -> LexiqueExtraction:
    return LexiqueExtraction.model_validate(reglages.charger_config("lexique_qhse"))
