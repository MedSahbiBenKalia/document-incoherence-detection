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
    """Désignation d'une clause : le couple ``(doc, ref)`` est la clé d'appariement.

    ``texte_source`` et ``texte_autonome`` sont portés **ici** et non sur le seul
    :class:`CoteClause` : le rapport HTML doit pouvoir afficher le contenu de n'importe
    quelle clause qu'il cite, y compris dans les zones non couvertes et les hypothèses
    d'alignement, où il n'y a pas de preuve. Un lecteur qui n'a pas les documents sous les
    yeux ne peut rien faire de « D1 §6.5 ».
    """

    doc: str = ""
    ref: str = ""
    clause_id: str | None = None

    #: Le texte tel qu'il figure dans le document — c'est lui que citent les preuves.
    texte_source: str | None = None
    #: Le texte de travail : chapeau de liste redistribué, anaphore résolue. C'est celui
    #: que le prompt de l'étage C affiche, donc celui que le juge a pu citer.
    texte_autonome: str | None = None

    def couple(self) -> tuple[str, str]:
        return (self.doc.strip(), self.ref.strip())

    def libelle(self) -> str:
        return f"{self.doc.strip()} §{self.ref.strip()}"

    def texte(self) -> str:
        """Ce qu'on affiche du contenu de la clause. Jamais tronqué."""
        return self.texte_source or self.texte_autonome or ""


class CoteClause(RefClause):
    """Un côté de constatation, avec sa preuve littérale.

    Invariant du projet : ``preuve`` doit être une sous-chaîne **exacte** du texte de la
    clause. La vérification se fait en Python, après l'appel qui l'a produite.
    """

    preuve: str = ""

    @property
    def cite_le_texte_autonome(self) -> bool:
        """La citation ne se trouve-t-elle que dans la forme autonome de la clause ?

        Le prompt de l'étage C affiche `texte_autonome` : le juge peut donc citer « L'Animateur
        QSE doit informer… » là où `texte_source` ne porte que « informer… ». La citation est
        littérale — le garde-fou l'a vérifiée —, mais elle ne se surlignerait dans aucun des
        deux textes si le rapport affichait l'autre.
        """
        from cohera.detection.modeles import citation_litterale

        if not self.preuve:
            return False
        return citation_litterale(self.preuve, self.texte_autonome) and not citation_litterale(
            self.preuve, self.texte_source
        )

    @property
    def texte_affiche(self) -> str:
        """Le texte à montrer : celui qui **contient réellement** la citation.

        Sans cela, une citation parfaitement littérale s'afficherait sous un texte où elle
        ne figure pas — le lecteur croirait le garde-fou en défaut alors qu'il a travaillé.
        """
        return self.texte_autonome or "" if self.cite_le_texte_autonome else self.texte()

    def preuve_est_litterale(self) -> bool:
        """La preuve est-elle bien extraite du texte, et non reformulée ?

        Les deux textes de la clause sont recevables, et la comparaison passe par la
        normalisation d'entrée du projet : voir
        :func:`cohera.detection.modeles.citation_litterale`, qui porte la règle et son
        motif. Les deux vérifications du dépôt — celle de la cascade et celle du rapport —
        appliquent le **même** critère ; en appliquer deux différents ferait publier un
        rapport que la cascade avait refusé, ou l'inverse.
        """
        if not self.preuve:
            return True  # rien d'affirmé, donc rien de reformulé
        if self.texte_source is None and self.texte_autonome is None:
            return True  # rien à vérifier contre
        from cohera.detection.modeles import citation_litterale

        return citation_litterale(self.preuve, self.texte_source, self.texte_autonome)


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


class CitationInvalide(BaseModel):
    """Une citation du juge, mise en regard du texte réel de la clause.

    C'est la **preuve visuelle que le garde-fou n°1 travaille** : le rapport montre côte à
    côte ce que le modèle a écrit et ce que la clause dit réellement. Il expose la citation
    annulée, jamais le verdict qu'elle portait — celui-ci reste écarté.

    **Les deux côtés de la paire sont rendus, pas seulement celui qui a fauté**, et
    `litterale` dit lequel tient. Sans la moitié juste à côté de la moitié inventée, on ne
    verrait qu'une citation absente, sans savoir si le modèle savait citer du tout — or
    c'est précisément ce que le lecteur doit pouvoir juger.
    """

    #: « A » ou « B » — quel côté de la paire cette citation prétendait couvrir.
    cote: str = ""
    #: « D1 §9.2 », jamais un `clause_id` interne : le rapport se lit sans le dépôt.
    clause: str = ""
    #: Ce que le juge a écrit, recopié tel quel.
    citation: str = ""
    #: Cette citation existe-t-elle dans `texte_source` ? `False` = elle a été fabriquée.
    litterale: bool = False
    #: Ce que la clause dit réellement — le texte contre lequel la vérification a échoué.
    texte_source: str = ""


class Abstention(BaseModel):
    """Une paire que le juge n'a pas tranchée — et qui doit rester **visible**.

    Quatre chemins y mènent, tous nommés par `motif` : abstention explicite du modèle,
    preuve inventée (verdict annulé), plafond de budget atteint, service injoignable.
    Aucun n'est un rejet. « Un système d'audit qui abstient 8 % est infiniment plus utile
    qu'un système qui tranche à tort 8 % » (architecture.md §7.4).

    Les trois derniers champs disent **ce qui a été écarté**, et non seulement qu'on a
    écarté quelque chose. Ils sont relus de la réponse déjà mémorisée par le cache disque :
    les exposer ne coûte aucun appel réseau.
    """

    clause_a: RefClause = Field(default_factory=RefClause)
    clause_b: RefClause | None = None
    motif: str = ""
    explication: str = ""
    etage: str = "C"

    #: Le verdict que le juge avait rendu avant qu'il ne soit annulé ou écarté : COHERENT,
    #: INCOHERENCE, SPECIALISATION, INDECIDABLE — ou le mot hors vocabulaire qu'il a
    #: inventé. Vide quand aucune réponse exploitable n'est parvenue (budget, panne, JSON
    #: irréparable) : « pas de réponse » et « une réponse refusée » ne se confondent pas.
    verdict_brut: str = ""
    #: La confiance que le juge s'accordait sur ce verdict. Lue telle quelle : c'est ce
    #: qu'il affirmait, pas ce que le système en retient.
    confiance: float = 0.0
    #: Réservé aux `PREUVE_INVENTEE` : ce que le juge a cité, en regard du texte réel. Vide
    #: pour les autres motifs, où aucune citation n'est en cause — ranger sous ce nom une
    #: citation parfaitement littérale, écartée pour manque de confiance, serait un
    #: contresens.
    preuve_invalide: list[CitationInvalide] = Field(default_factory=list)


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

    #: Les clauses qui emploient chacun des deux termes, **avec leur texte**. Sans elles,
    #: la rubrique demande au lecteur de croire qu'« anomalie » et « écart » désignent la
    #: même chose sans jamais lui montrer les phrases où les deux mots sont employés — or
    #: c'est exactement ce qu'on lui demande de réviser.
    clauses_a: list[RefClause] = Field(default_factory=list)
    clauses_b: list[RefClause] = Field(default_factory=list)

    def clauses(self) -> list[RefClause]:
        return self.clauses_a + self.clauses_b


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


class StatistiquesNLI(BaseModel):
    """Ce que l'étage B a vu, et la seule chose qu'il a faite : fermer des paires.

    `paires_fermees` est le gain du J8, et il se lit **en paires soustraites au juge**, pas
    en appels réseau économisés : sur un cache complet, l'étage C ne passe déjà aucun
    appel. `paires_instables` compte les paires dont les deux sens de l'inférence tombent
    dans des zones différentes — c'est la mesure de ce que le maximum de §7.3 recouvre.
    """

    modele: str = ""
    seuil_rejet: float = 0.0
    seuil_contradiction: float = 0.0
    paires_soumises: int = 0
    paires_fermees: int = 0
    contradictions_fermes: int = 0
    zone_grise: int = 0
    paires_instables: int = 0


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
    #: J8 — `None` quand l'étage B n'a pas tourné (`--sans-etage-b`), pour la même raison
    #: que `statistiques_llm` : « zéro paire fermée » et « étage désactivé » ne se
    #: confondent pas dans une ablation.
    statistiques_nli: StatistiquesNLI | None = None
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
