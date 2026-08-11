"""Schéma pydantic de la Clause Frame et fusion règles/LLM.

Invariant : la fusion se fait ICI, côté Python. Le LLM ne remplit que les
champs laissés `null` par les règles — jamais par consigne au modèle.

Aligné sur `docs/architecture.md` §4.1. Quatre énumérations y sont déclarées fermées pour
le futur garde-fou LLM (§4.4) : `Modalite`, `Dimension`, `TypeCondition`, `RaciType`. Les
autres (`TypeEnonce`, `TypeReference`, `TypePerimetre`, `Quantificateur`, `Monotonie`,
`StatutGrandeur`, `Operateur`) ne sont pas formellement fermées par l'architecture mais
partagent le même statut : un vocabulaire structurel du schéma, pas une valeur métier —
au même titre que `OrigineClause` dans `ingestion/modeles.py`. `Grandeur.role` reste en
revanche une chaîne libre : architecture.md §4.3 le dit explicitement, « une table de
configuration, pas du code » — validé au runtime contre `config/registre_grandeurs.yaml`,
jamais contre une liste Python.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

# --------------------------------------------------------------------- énumérations


class Modalite(StrEnum):
    OBLIGATION = "OBLIGATION"
    INTERDICTION = "INTERDICTION"
    PERMISSION = "PERMISSION"
    RECOMMANDATION = "RECOMMANDATION"
    CONSTAT = "CONSTAT"
    DEFINITION = "DEFINITION"


class TypeEnonce(StrEnum):
    PRESCRIPTION = "PRESCRIPTION"
    DEFINITION = "DEFINITION"
    CONSTAT = "CONSTAT"
    RENVOI = "RENVOI"
    DEROGATION = "DEROGATION"


class Dimension(StrEnum):
    TEMPS = "TEMPS"
    TEMPS_PERIODE = "TEMPS_PERIODE"
    LONGUEUR = "LONGUEUR"
    MASSE = "MASSE"
    TEMPERATURE = "TEMPERATURE"
    PRESSION_ACOUSTIQUE = "PRESSION_ACOUSTIQUE"
    POURCENTAGE = "POURCENTAGE"
    EFFECTIF = "EFFECTIF"
    MONETAIRE = "MONETAIRE"
    SANS_UNITE = "SANS_UNITE"


class Operateur(StrEnum):
    EGAL = "="
    INFERIEUR = "<"
    INFERIEUR_OU_EGAL = "≤"
    SUPERIEUR = ">"
    SUPERIEUR_OU_EGAL = "≥"


class TypeCondition(StrEnum):
    SPATIAL = "SPATIAL"
    TEMPOREL = "TEMPOREL"
    ORGANISATIONNEL = "ORGANISATIONNEL"
    CIRCONSTANCIEL = "CIRCONSTANCIEL"
    POPULATIONNEL = "POPULATIONNEL"
    SEUIL = "SEUIL"
    ACTIVITE = "ACTIVITE"


class TypeReference(StrEnum):
    INTERNE = "INTERNE"
    NORME = "NORME"
    EXIGENCE = "EXIGENCE"


class RaciType(StrEnum):
    R = "R"
    A = "A"
    C = "C"
    I = "I"


class TypePerimetre(StrEnum):
    SITE = "SITE"
    ATELIER = "ATELIER"
    ACTIVITE = "ACTIVITE"
    POPULATION = "POPULATION"
    ENTITE = "ENTITE"


class Quantificateur(StrEnum):
    UNIVERSEL = "UNIVERSEL"
    EXISTENTIEL = "EXISTENTIEL"


class Monotonie(StrEnum):
    """Le sens de « plus strict » pour un rôle de grandeur (architecture.md §4.3).

    Distingue une spécialisation légitime (N01 : 24 h < 48 h) d'une contradiction
    (I13/I14/I15 : inversion hiérarchique) — voir `config/registre_grandeurs.yaml`.
    """

    PLUS_PETIT = "PLUS_PETIT"
    PLUS_GRAND = "PLUS_GRAND"


class StatutGrandeur(StrEnum):
    """`.claude/rules/extraction.md` : une expression vague produit IMPRECIS, jamais
    `null` ; bimensuel/bimestriel produisent AMBIGU, jamais une valeur tranchée en
    silence."""

    NORMAL = "NORMAL"
    IMPRECIS = "IMPRECIS"
    AMBIGU = "AMBIGU"


# ------------------------------------------------------------- registre des grandeurs


class RoleGrandeur(BaseModel):
    """Une entrée de `config/registre_grandeurs.yaml`."""

    dimension: Dimension | None = None  # None = "selon grandeur" (seuil_exposition, seuil_declenchement)
    monotonie: Monotonie  # pas de défaut : model_validate lève si un rôle l'omet
    exemple: str = ""


class RegistreGrandeurs(BaseModel):
    grandeurs: dict[str, RoleGrandeur] = Field(default_factory=dict)


# --------------------------------------------------------------- sous-modèles de frame


class Grandeur(BaseModel):
    role: str
    dimension: Dimension
    valeur: float
    unite: str
    # None seulement si statut=AMBIGU (bimensuel/bimestriel) ; jamais None si IMPRECIS.
    valeur_si: int | None
    valeur_si_calendaire: int | None = None
    operateur: Operateur = Operateur.EGAL
    surface: str  # sous-chaîne littérale de texte_source
    monotonie: Monotonie  # dénormalisée depuis le registre au moment de l'extraction
    statut: StatutGrandeur = StatutGrandeur.NORMAL
    qualificateurs: dict[str, str] = Field(default_factory=dict)


class Condition(BaseModel):
    surface: str
    type: TypeCondition
    concept_cible: str | None = None
    operateur: str | None = None  # ex. "APPARTIENT" ; pas formellement fermé par architecture.md
    # Porte le nombre d'un SEUIL non comparable inter-documents (vitesse du vent, durée
    # d'une intervention) : ces grandeurs n'ont pas de rôle dans le registre des 10, donc
    # ne peuvent pas devenir une Grandeur — voir cohera/extraction/regles/conditions.py.
    valeur: float | None = None


class Reference(BaseModel):
    type: TypeReference
    cible: str  # renvoi interne, code de norme ou d'article, selon `type`
    surface: str
    version: str | None = None
    source: str | None = None
    document_cible: str | None = None
    # None pour NORME/EXIGENCE : J2 ne tente aucune résolution contre registre_normes.yaml
    # (rempli au J4) — False impliquerait à tort qu'une vérification a été faite et a
    # échoué. bool pour INTERNE, où la résolution est faite localement (voir references.py).
    resolu: bool | None = None


class Validite(BaseModel):
    debut: date | None = None
    fin: date | None = None


class Derogation(BaseModel):
    """Absent de l'exemple JSON d'architecture.md §4.1 (qui ne montre que `null`) — déduit
    par analogie avec les propriétés de l'arête de graphe `DEROGE_A` (§5.3) :
    justification, approuvee_par, echeance."""

    cible: str  # surface littérale, ex. "§ 6.4 de la politique POL-SEC-01"
    cible_document: str | None = None
    cible_resolue: bool
    justification: str | None = None
    approbateur: str | None = None
    date_approbation: date | None = None  # "approuvée ... le 12 février 2026"
    echeance: date | None = None


class Acteur(BaseModel):
    surface: str
    concept_id: str | None = None
    raci: RaciType | None = None


class Action(BaseModel):
    surface: str
    lemme: str


class Objet(BaseModel):
    surface: str
    concept_id: str | None = None


class Perimetre(BaseModel):
    surface: str
    type: TypePerimetre


class Portee(BaseModel):
    quantificateur: Quantificateur
    surface: str


# --------------------------------------------------------------------------- la frame


class ClauseFrame(BaseModel):
    """La Clause Frame d'une clause (architecture.md §4.1), remplie ici par les règles du
    J2 seules. `acteur`/`action`/`objet`/`perimetre`/`portee`/`risques_maitrises` sont
    déclarés pour que le schéma accueille un futur remplissage LLM champ par champ
    (invariant #1), mais aucun extracteur J2 ne les peuple — c'est `regles/raci.py` (hors
    périmètre J2) et l'étage LLM du J6."""

    clause_id: str
    type_enonce: TypeEnonce | None = None
    modalite: Modalite | None = None
    force: int | None = None
    negation: bool = False
    # Texte du marqueur déontique trouvé, seulement s'il vérifie aussi comme sous-chaîne
    # de texte_source (voir regles/deontique.py, qui lit texte_autonome) ; sinon None.
    modalite_surface: str | None = None

    acteur: Acteur | None = None
    action: Action | None = None
    objet: Objet | None = None

    quantites: list[Grandeur] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    perimetre: Perimetre | None = None
    portee: Portee | None = None
    validite: Validite | None = None
    references: list[Reference] = Field(default_factory=list)
    derogation: Derogation | None = None
    risques_maitrises: list[str] = Field(default_factory=list)

    confiance_extraction: float = 1.0
    # Provenance par champ ("REGLE" ou "LLM") — seulement les clés effectivement remplies
    # par une règle. Absence de clé = champ jamais touché, distinct de "rempli mais null".
    source_extraction: dict[str, str] = Field(default_factory=dict)
