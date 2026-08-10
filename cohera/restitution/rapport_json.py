"""Schéma du rapport de sortie, et lecture / écriture de ``rapport.json``.

C'est le **contrat de la semaine** : tout ce que le pipeline produit passe par ici, et
c'est sur cette structure que le harnais d'évaluation calcule ses chiffres.

Deux partis pris qui expliquent la forme :

* **Tous les champs ont une valeur par défaut**, donc ``Rapport()`` est valide. C'est ce
  qui garantit mécaniquement qu'une évaluation sur rapport vide rend des zéros au lieu de
  lever une exception.
* **Chaque côté de constatation porte ``doc`` et ``ref``** (le numéro de paragraphe) en
  plus du ``clause_id`` interne. C'est ce qui permet d'apparier directement avec
  ``label.json`` sans fichier de correspondance intermédiaire.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class RefClause(BaseModel):
    """Désignation d'une clause : le couple ``(doc, ref)`` est la clé d'appariement."""

    doc: str = ""
    ref: str = ""
    clause_id: str | None = None

    def couple(self) -> tuple[str, str]:
        return (self.doc.strip(), self.ref.strip())

    def libelle(self) -> str:
        return f"{self.doc.strip()} §{self.ref.strip()}"


class CoteClause(RefClause):
    """Un côté de constatation, avec sa preuve littérale.

    Invariant du projet : ``preuve`` doit être une sous-chaîne **exacte** de
    ``texte_source``. La vérification se fait en Python, après l'appel qui l'a produite.
    """

    preuve: str = ""
    texte_source: str | None = None

    def preuve_est_litterale(self) -> bool:
        """La preuve est-elle bien extraite du texte, et non reformulée ?"""
        if self.texte_source is None:
            return True  # rien à vérifier contre
        return self.preuve in self.texte_source


class PaireCandidate(BaseModel):
    """Une paire retenue par le ciblage — le seul type de paire qui a droit à un calcul cher."""

    clause_a: RefClause = Field(default_factory=RefClause)
    clause_b: RefClause = Field(default_factory=RefClause)
    canaux: list[str] = Field(default_factory=list)
    score_fusion: float = 0.0


class Constatation(BaseModel):
    """Une incohérence constatée. ``clause_b`` vaut ``None`` pour une anomalie mono-clause."""

    id: str = ""
    type: str = ""
    sous_type: str | None = None
    clause_a: CoteClause = Field(default_factory=CoteClause)
    clause_b: CoteClause | None = None
    gravite: str = ""
    detecteur: str = ""
    etage: str = ""
    confiance: float = 0.0
    explication: str = ""


class Derogation(BaseModel):
    """Une dérogation en vigueur : déclarée, motivée, approuvée, non expirée.

    Rubrique distincte des constatations. Une paire couverte par une dérogation valide
    ressemble à un conflit sans en être un — elle doit être *listée*, pas *signalée*.
    """

    id: str = ""
    clause_a: CoteClause = Field(default_factory=CoteClause)
    clause_b: CoteClause | None = None
    cible: str = ""
    justification: str = ""
    approbateur: str = ""
    echeance: date | None = None


class DocumentResume(BaseModel):
    id: str = ""
    code: str = ""
    fichier: str = ""
    nb_clauses: int = 0


class Statistiques(BaseModel):
    paires_theoriques: int = 0
    paires_candidates: int = 0
    facteur_reduction: float = 0.0


class Rapport(BaseModel):
    """La sortie complète du pipeline. ``Rapport()`` est un rapport vide valide."""

    corpus: str = ""
    date_execution: date | None = None
    date_reference: date | None = None
    documents: list[DocumentResume] = Field(default_factory=list)
    statistiques: Statistiques = Field(default_factory=Statistiques)
    #: Toutes les clauses segmentées. Sert au facteur de réduction, et au rappel du
    #: ciblage des anomalies mono-clause, qui n'ont par nature aucune paire.
    clauses_analysees: list[RefClause] = Field(default_factory=list)
    paires_candidates: list[PaireCandidate] = Field(default_factory=list)
    constatations: list[Constatation] = Field(default_factory=list)
    derogations_en_vigueur: list[Derogation] = Field(default_factory=list)
    limites: list[str] = Field(default_factory=list)


def charger_rapport(chemin: Path | str) -> Rapport:
    """Lit ``rapport.json``. Un fichier absent rend un rapport **vide**, pas une erreur.

    C'est délibéré : au J0 le pipeline n'existe pas encore, et ``cohera evaluer`` doit
    quand même produire sa ligne de base à zéro.
    """
    chemin = Path(chemin)
    if not chemin.is_file():
        return Rapport()
    contenu = chemin.read_text(encoding="utf-8").strip()
    if not contenu:
        return Rapport()
    return Rapport.model_validate(json.loads(contenu))


def ecrire_rapport(rapport: Rapport, chemin: Path | str) -> Path:
    """Écrit le rapport en JSON lisible (UTF-8, accents conservés)."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(rapport.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chemin
