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
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, computed_field


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


class StatutConstatation(StrEnum):
    """Cycle de vie d'une constatation (architecture.md §8.1).

    Une exécution fraîche ne produit que des ``A_VALIDER``. ``RESOLUE`` ne s'obtient qu'en
    **comparant deux exécutions** : c'est le scénario incrémental du J7 qui l'attribue, à
    une constatation présente dans le rapport de référence et absente du suivant.
    """

    A_VALIDER = "A_VALIDER"
    CONFIRMEE = "CONFIRMEE"
    REJETEE_UTILISATEUR = "REJETEE_UTILISATEUR"
    RESOLUE = "RESOLUE"


class Occurrence(BaseModel):
    """Une manifestation d'une constatation regroupée (architecture.md §8.2).

    Le regroupement ne **supprime** jamais une manifestation : il la range sous le constat
    de fond qui la porte. Sans cela, le rapport perdrait la trace de ce qui a été détecté,
    et l'auditeur ne pourrait pas remonter à la clause qui l'a déclenché.
    """

    id: str = ""
    detecteur: str = ""
    etage: str = ""
    clause_a: CoteClause = Field(default_factory=CoteClause)
    clause_b: CoteClause | None = None
    explication: str = ""


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

    #: J7, architecture.md §8.1.
    statut: StatutConstatation = StatutConstatation.A_VALIDER

    #: J7 — la clé de comparaison partagée par les deux clauses (§5.8), quand elles en ont
    #: une commune. Vide sinon : c'est le second terme de la clé de regroupement de §8.2,
    #: et une clé partielle ne doit **jamais** regrouper (voir `consolidation/constatations.py`).
    cle_comparaison: str = ""

    #: J7, §8.2 — toutes les manifestations de ce constat de fond, la représentante
    #: comprise. Vide tant que le regroupement n'a pas tourné.
    occurrences: list[Occurrence] = Field(default_factory=list)

    #: J7 — la criticité d'architecture.md §8.3, qui donne l'ordre de lecture du rapport.
    criticite: float = 0.0
    #: J7, §8.3 — « D1 §5.1 » : la clause désignée fautive, ou `ARBITRAGE_REQUIS` quand les
    #: deux documents sont de même niveau. Vide quand la monotonie ne désigne personne —
    #: ce qui est en soi une information, pas un trou.
    clause_fautive: str = ""

    #: « A » ou « B » — laquelle des deux clauses est la plus permissive, lue dans la
    #: monotonie du rôle par A2. C'est ce qui, croisé au niveau hiérarchique, permet de
    #: dire QUI a tort et pas seulement que deux clauses divergent.
    plus_permissive: str = ""
    #: L'une des deux clauses cite-t-elle un référentiel externe ? Déclenche le
    #: multiplicateur « exigence externe » de §8.3 (I08).
    cite_norme_externe: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def nb_occurrences(self) -> int:
        """Combien de fois ce constat de fond se manifeste dans le corpus.

        Calculé, jamais stocké : un compteur stocké dérive du jour où l'on ajoute une
        occurrence sans penser à l'incrémenter.
        """
        return max(1, len(self.occurrences))


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


class Abstention(BaseModel):
    """Une paire que le juge n'a pas tranchée — et qui doit rester **visible**.

    Quatre chemins y mènent, tous nommés par `motif` : abstention explicite du modèle,
    preuve inventée (verdict annulé), plafond de budget atteint, service injoignable.
    Aucun n'est un rejet. « Un système d'audit qui abstient 8 % est infiniment plus utile
    qu'un système qui tranche à tort 8 % » (architecture.md §7.4).
    """

    clause_a: RefClause = Field(default_factory=RefClause)
    clause_b: RefClause | None = None
    motif: str = ""
    explication: str = ""
    etage: str = "C"


class HypotheseAlias(BaseModel):
    """Un alias arbitré par le LLM — une **hypothèse d'alignement**, pas un fait.

    Exposée dans le rapport parce qu'elle est révisable : `architecture.md` §13 (R1) pose
    que les alias sont « exposés et révisables, jamais suffisants seuls pour un verdict
    ferme ». Le J7 en fait une rubrique du rapport HTML.
    """

    libelle_a: str = ""
    libelle_b: str = ""
    methode: str = "LLM"
    score_vectoriel: float = 0.0
    retenu: bool = False
    confiance: float = 0.0
    justification: str = ""


class StatistiquesLLM(BaseModel):
    """Ce que l'étage C a coûté, et ce qu'il a refusé d'affirmer.

    `taux_annulation` est la mesure directe de la crédibilité du juge : la part de ses
    réponses dont la preuve n'existait pas dans le texte. Un taux élevé disqualifie le
    profil bien avant que le rappel ne le montre.
    """

    profil: str = ""
    modele: str = ""
    appels_reseau: int = 0
    servis_par_cache: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    reparations: int = 0
    budget_max: int = 0

    paires_soumises: int = 0
    verdicts_annules: int = 0
    taux_annulation: float = 0.0
    non_verifiees_budget: int = 0
    non_verifiees_service: int = 0
    echecs_transport: int = 0
    coupe_circuit: bool = False


class DocumentResume(BaseModel):
    id: str = ""
    code: str = ""
    fichier: str = ""
    nb_clauses: int = 0
    #: J7 — 1 pour une politique, 3 pour une procédure. C'est ce niveau qui décide, croisé
    #: à `plus_permissive`, s'il y a **inversion hiérarchique** (architecture.md §8.3).
    niveau_hierarchique: int | None = None


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
    #: J6 — ce que le juge n'a pas tranché, nommé plutôt que compté.
    abstentions: list[Abstention] = Field(default_factory=list)
    #: J6 — les alias arbitrés par le LLM, révisables (architecture.md §13, R1).
    hypotheses_alias: list[HypotheseAlias] = Field(default_factory=list)
    #: J6 — `None` quand l'étage C n'a pas tourné (`--sans-etage-c`), ce qui distingue
    #: « zéro appel parce qu'on a désactivé » de « zéro appel parce que tout était en cache ».
    statistiques_llm: StatistiquesLLM | None = None
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
