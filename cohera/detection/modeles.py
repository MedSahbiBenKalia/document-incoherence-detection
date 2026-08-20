"""Le verdict, partagé par les trois détecteurs symboliques du J5.

**Un détecteur ne rend jamais `None`.** Il rend toujours un :class:`Verdict`, fût-il
`AUCUNE` — avec son :class:`Motif`. C'est la règle « toute paire écartée par un filtre est
journalisée avec son motif » (`.claude/rules/detection.md`) appliquée aux détecteurs
eux-mêmes : sans elle, les tests négatifs ne peuvent pas distinguer « rejeté pour la bonne
raison » de « rejeté par accident », et c'est précisément le piège que tend N04.

**Ferme ou non.** ``ferme=False`` n'est pas un rejet : c'est une escalade vers les étages B
et C du J6. Un rejet est définitif et silencieux, une escalade reste visible.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class TypeVerdict(StrEnum):
    AUCUNE = "AUCUNE"
    CONTRADICTION = "CONTRADICTION"
    SPECIALISATION = "SPECIALISATION"
    DIVERGENCE_PERSPECTIVE = "DIVERGENCE_PERSPECTIVE"
    #: J6, étage C. Le contrat de sortie d'architecture.md §7.4 ajoute deux issues que
    #: l'étage A n'a pas : un « je constate la cohérence » explicite, et une abstention.
    COHERENT = "COHERENT"
    INDECIDABLE = "INDECIDABLE"


class Motif(StrEnum):
    """Pourquoi ce verdict — et surtout, pourquoi il n'y en a pas, ou pas de ferme."""

    # A2 — rien à dire
    PAS_DE_GRANDEUR_COMPARABLE = "PAS_DE_GRANDEUR_COMPARABLE"
    VALEURS_EGALES = "VALEURS_EGALES"
    PORTEES_DISJOINTES = "PORTEES_DISJOINTES"

    # A1 — rien à dire
    MODALITE_ABSENTE = "MODALITE_ABSENTE"
    MODALITE_NON_PRESCRIPTIVE = "MODALITE_NON_PRESCRIPTIVE"
    ECART_DE_FORCE_NUL = "ECART_DE_FORCE_NUL"

    # les verdicts positifs
    VALEURS_DIVERGENTES = "VALEURS_DIVERGENTES"
    QUALIFICATEURS_DIVERGENTS = "QUALIFICATEURS_DIVERGENTS"
    INCLUSION_PLUS_STRICTE = "INCLUSION_PLUS_STRICTE"
    INCLUSION_PLUS_PERMISSIVE = "INCLUSION_PLUS_PERMISSIVE"
    ECART_DE_FORCE = "ECART_DE_FORCE"
    POLARITE_OPPOSEE = "POLARITE_OPPOSEE"
    REFERENCE_CASSEE = "REFERENCE_CASSEE"
    REFERENTIEL_OBSOLETE = "REFERENTIEL_OBSOLETE"
    REFERENTIEL_DIVERGENT = "REFERENTIEL_DIVERGENT"

    # ce qui empêche un verdict d'être ferme
    OBJETS_SANS_RECOUVREMENT = "OBJETS_SANS_RECOUVREMENT"
    PORTEE_INDETERMINEE = "PORTEE_INDETERMINEE"
    PREUVE_LITTERALE_ABSENTE = "PREUVE_LITTERALE_ABSENTE"
    GRANDEUR_IMPRECISE = "GRANDEUR_IMPRECISE"

    # J8, étage B — la seule chose que le NLI a le droit de faire : fermer par le bas.
    #: Les deux sens de l'inférence s'accordent à ne voir aucune contradiction. La paire
    #: est close **avant** le LLM. Il n'existe volontairement pas de motif symétrique pour
    #: la bande haute : l'étage B n'affirme jamais, faute de preuve littérale à citer.
    REJET_NLI = "REJET_NLI"

    # J6, étage C — le verdict du juge, puis les cinq façons dont il peut ne pas conclure.
    #: Le juge a tranché, preuve littérale vérifiée et confiance au-dessus du plancher.
    VERDICT_DU_JUGE = "VERDICT_DU_JUGE"
    #: Garde-fou n°1 d'architecture.md §7.4 : la preuve citée n'existe pas dans le texte.
    #: **Annule** le verdict, là où les motifs ci-dessus se contentent de le rétrograder.
    PREUVE_INVENTEE = "PREUVE_INVENTEE"
    #: Garde-fou n°4 : le juge s'abstient, et c'est une réponse légitime.
    ABSTENTION_DU_JUGE = "ABSTENTION_DU_JUGE"
    #: Garde-fou n°5 : plafond atteint. La paire est nommée, jamais silencieusement rejetée.
    NON_VERIFIEE_BUDGET = "NON_VERIFIEE_BUDGET"
    #: Le service n'a pas répondu. Une panne se lit dans le rapport, elle n'avorte pas le run.
    LLM_INJOIGNABLE = "LLM_INJOIGNABLE"
    #: Ni l'appel ni sa réparation n'ont produit un JSON conforme (architecture.md §4.4).
    EXTRACTION_INCERTAINE = "EXTRACTION_INCERTAINE"


class Verdict(BaseModel):
    """Ce qu'un détecteur symbolique a conclu d'une paire — ou d'une clause seule.

    ``clause_b`` vaut ``None`` pour les anomalies mono-clause d'A5 (I09, I10), détectées
    sans aucune comparaison.
    """

    detecteur: str
    type: TypeVerdict
    motif: Motif
    explication: str = ""

    clause_a: str
    clause_b: str | None = None

    #: Invariant #3 — sous-chaînes **exactes** de `texte_source`, vérifiées en Python par
    #: `verifier_preuves`. Jamais un résumé, jamais une reformulation.
    preuve_a: str | None = None
    preuve_b: str | None = None

    #: Type de la taxonomie (`label.json`) : NUMERIQUE, NEGATION, FACTUEL, HIERARCHIQUE…
    type_taxonomie: str = ""
    gravite: str = ""
    confiance: float = 0.0

    relation_portees: str = ""
    #: « A » ou « B » — laquelle des deux clauses est la plus permissive, lue dans la
    #: monotonie du rôle. C'est ce qui permet de dire QUI a tort, et pas seulement que
    #: deux clauses divergent.
    plus_permissive: str | None = None

    #: `False` = escalade vers les étages B/C du J6, pas un rejet.
    ferme: bool = False

    #: Quel étage de la cascade a produit ce verdict : « A » symbolique, « B » NLI,
    #: « C » LLM juge. Le rapport en a besoin pour que l'ablation `--sans-etage-c` du J7
    #: puisse chiffrer ce que le LLM a réellement apporté.
    etage: str = "A"

    @property
    def est_constatation(self) -> bool:
        """Une constatation, c'est un verdict ferme qui affirme quelque chose.

        Ni `AUCUNE` (rien à dire), ni `SPECIALISATION` (compatible, N01), ni `COHERENT`
        (le juge conclut à la compatibilité), ni `INDECIDABLE` (abstention), ni un verdict
        non ferme (escalade). C'est ce compte, et lui seul, qui entre dans la précision.
        """
        return self.ferme and self.type in (
            TypeVerdict.CONTRADICTION,
            TypeVerdict.DIVERGENCE_PERSPECTIVE,
        )

    @property
    def est_abstention(self) -> bool:
        """Le juge n'a pas tranché — et le rapport doit le dire.

        Quatre chemins y mènent : l'abstention explicite du modèle, la preuve inventée qui
        annule le verdict, le plafond de budget, la panne de service. Aucun n'est un rejet :
        « un système d'audit qui abstient 8 % est infiniment plus utile qu'un système qui
        tranche à tort 8 % » (architecture.md §7.4).
        """
        return self.type is TypeVerdict.INDECIDABLE


def verifier_preuves(verdict: Verdict, textes: dict[str, str]) -> bool:
    """`preuve_a` et `preuve_b` sont-elles des sous-chaînes exactes de `texte_source` ?

    Invariant #3 de `CLAUDE.md` : aucun verdict sans preuve littérale, vérifiée **en
    Python** après coup. Une preuve absente n'est pas une erreur de programmation — c'est
    le cas d'une modalité qui n'apparaît que dans `texte_autonome` (liste à chapeau, CAP02)
    — mais elle interdit le verdict ferme, et c'est l'appelant qui en tire la conséquence.
    """
    for clause_id, preuve in ((verdict.clause_a, verdict.preuve_a),
                              (verdict.clause_b, verdict.preuve_b)):
        if preuve is None:
            continue
        if clause_id is None or preuve not in textes.get(clause_id, ""):
            return False
    return True
