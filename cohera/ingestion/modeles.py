"""Entités produites par L0 : `Document`, `Section`, `Clause`.

Aligné sur `docs/architecture.md` §3.4 (sortie de L0) et §5.2 (nœuds du graphe).
Le J2 enrichira la clause d'une Clause Frame complète — modalité, force, quantités,
conditions — dans `cohera/extraction/frames.py`. Ce module-ci ne connaît que la forme.

**La règle des deux textes.** Une clause porte deux chaînes, et les confondre serait
l'erreur la plus coûteuse du projet :

- `texte_source` est un empan **littéral** de `Document.texte_origine`. C'est lui qu'on
  cite en preuve, lui que vérifie `preuve_est_litterale()` au J7. L'invariant
  `texte_origine[debut:fin] == texte_source` tient par construction, parce que la
  normalisation en amont ne change jamais la longueur du texte.
- `texte_autonome` est le texte de **travail** : normalisé, chapeau redistribué, anaphore
  résolue. C'est lui qu'on plonge, qu'on envoie au NLI et au LLM. Il n'a pas d'offset,
  et il ne doit jamais servir de preuve.
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class OrigineClause(StrEnum):
    """D'où vient la clause dans la page (architecture.md §5.2).

    Le J2 en a besoin : une ligne de tableau n'a ni sujet ni verbe conjugué, l'extraction
    déontique doit le savoir avant de conclure à l'absence de modalité.
    """

    TEXTE = "TEXTE"
    LISTE = "LISTE"
    TABLEAU = "TABLEAU"


def empreinte(texte: str) -> str:
    """SHA-256 tronqué du texte source — la clé du mode incrémental (architecture.md §3.4)."""
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]


class Section(BaseModel):
    """Un nœud de structure : « 5. CONTRÔLE PÉRIODIQUE DES EPI »."""

    section_id: str
    doc_id: str
    numero: str
    titre: str
    niveau: int = 1


class Clause(BaseModel):
    """Un énoncé normatif atomique : prescription, seuil, responsabilité ou définition."""

    clause_id: str
    doc_id: str
    # Le numéro de paragraphe tel qu'il apparaît dans le fichier — « 4.2 », « 10.3 ».
    # C'est la clé sur laquelle le harnais d'évaluation apparie avec label.json ; trois
    # clauses issues d'une même liste partagent donc la même `ref`.
    ref: str
    section_path: list[str] = Field(default_factory=list)
    ordre: int

    texte_source: str
    texte_autonome: str
    offset: tuple[int, int]

    origine: OrigineClause = OrigineClause.TEXTE
    # Renseigné pour LISTE : le chapeau redistribué, conservé pour la traçabilité.
    chapeau: str | None = None
    # Renseigné pour TABLEAU : {« Réalisation » : « Animateur QSE », …}, clés = en-tête.
    attributs: dict[str, str] = Field(default_factory=dict)
    # Phrases voisines non qualifiées, rattachées faute de valoir une clause (CAP08).
    contexte: list[str] = Field(default_factory=list)
    autonomise: bool = False
    hash: str = ""

    @property
    def debut(self) -> int:
        return self.offset[0]

    @property
    def fin(self) -> int:
        return self.offset[1]

    @property
    def libelle(self) -> str:
        """« D1 §4.2 » — la forme utilisée par le rapport et les messages d'erreur."""
        return f"{self.doc_id} §{self.ref}"

    def model_post_init(self, _contexte: object) -> None:
        if not self.hash:
            self.hash = empreinte(self.texte_source)


class Document(BaseModel):
    """Un fichier `.txt` du corpus, avec son front-matter lu et son texte d'origine."""

    doc_id: str
    fichier: str
    code: str = ""
    titre: str = ""
    type: str = "INCONNU"
    niveau_hierarchique: int | None = None
    version: str = ""
    date_application: date | None = None
    date_revision: date | None = None
    redacteur: str = ""
    approbateur: str = ""
    site: str = ""
    statut: str = "EN_VIGUEUR"
    # Phrases libres du front-matter, hors paires « clé : valeur ». Le J3 y lira
    # « annule et remplace la version 2 » pour l'arête ANNULE_ET_REMPLACE ; au J1 elles
    # sont seulement mises de côté, surtout pas transformées en clauses.
    notes: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    # Le texte de référence de tous les offsets. Exclu des exports : il est volumineux et
    # se relit depuis le fichier.
    texte_origine: str = Field(default="", repr=False, exclude=True)


class Segmentation(BaseModel):
    """Le résultat de L0 pour un document : son en-tête lu et ses clauses."""

    document: Document
    clauses: list[Clause] = Field(default_factory=list)

    def par_ref(self, ref: str) -> list[Clause]:
        """Les clauses issues d'un paragraphe donné. Trois pour une liste, une en général."""
        return [c for c in self.clauses if c.ref == ref]

    def clause(self, ref: str) -> Clause:
        """La clause unique d'un paragraphe. Lève si le paragraphe en a produit zéro ou plusieurs."""
        trouvees = self.par_ref(ref)
        if len(trouvees) != 1:
            raise KeyError(
                f"{self.document.doc_id} §{ref} : {len(trouvees)} clause(s), une seule attendue."
            )
        return trouvees[0]

    def par_section(self, numero: str) -> list[Clause]:
        """Toutes les clauses d'une section, « 10 » donnant 10.1, 10.2, 10.3."""
        return [c for c in self.clauses if c.ref.split(".")[0] == numero]

    def ecarts_offsets(self) -> list[str]:
        """Les clauses dont l'empan ne retombe pas sur son texte source. Vide = seul résultat acceptable.

        C'est le test n°1 du plan : sans lui, toutes les preuves du rapport seraient
        décalées sans que rien ne le signale.
        """
        origine = self.document.texte_origine
        ecarts = []
        for clause in self.clauses:
            tranche = origine[clause.debut : clause.fin]
            if tranche != clause.texte_source:
                ecarts.append(
                    f"{clause.clause_id} ({clause.libelle}) : "
                    f"texte_origine[{clause.debut}:{clause.fin}] = {tranche!r} "
                    f"≠ texte_source = {clause.texte_source!r}"
                )
        return ecarts
