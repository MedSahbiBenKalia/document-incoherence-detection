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

from cohera.ingestion.normalisation import normaliser


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


class ReponseBrute(BaseModel):
    """Ce que le juge a répondu, avant que la normalisation ou un garde-fou n'y touche.

    Conservée sur l'**abstention** qui en résulte, et rangée à part de ``preuve_a`` /
    ``preuve_b`` : une citation que le filtre contraint vient d'annuler n'est pas une
    preuve, et rien dans le dépôt ne doit pouvoir la confondre avec une preuve littérale.

    Sans elle, une abstention ne dit que ce qu'elle a refusé de faire ; avec elle, le
    rapport peut montrer **ce que le garde-fou a arrêté** — le verdict que le modèle
    tenait pour acquis, la confiance qu'il s'accordait, et la citation qu'il a fabriquée.
    C'est la démonstration que le garde-fou travaille, et elle ne coûte aucun appel : la
    réponse est déjà là, il suffisait de ne pas la jeter.
    """

    #: Le mot rendu par le modèle, tel quel — y compris hors du vocabulaire fermé.
    verdict: str = ""
    #: La confiance que le modèle s'accordait. Ce qu'il affirmait, pas ce qu'on en retient.
    confiance: float = 0.0
    #: Les deux citations produites. Littérales ou inventées : c'est l'appelant qui tranche.
    citation_a: str = ""
    citation_b: str = ""


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

    #: Étage C — la réponse du modèle telle qu'elle est arrivée, conservée pour que le
    #: rapport puisse dire *ce qui a été refusé* et non seulement *qu'on a refusé*.
    #: `None` partout ailleurs : un détecteur symbolique n'a pas de brut, son verdict
    #: **est** sa sortie.
    brut: ReponseBrute | None = None

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


def citation_litterale(preuve: str | None, *textes: str | None) -> bool:
    """La citation est-elle une sous-chaîne littérale de **l'un** de ces textes ?

    Deux tolérances, et deux seulement — toutes deux mesurées sur les verdicts annulés du
    J8, dont **3 sur 7** ne l'étaient pas pour une hallucination :

    1. **`texte_autonome` compte autant que `texte_source`.** Le prompt de l'étage C montre
       au modèle `texte_autonome` (`juge_llm._bloc_clause`) : lui reprocher de ne pas citer
       un texte qu'il n'a jamais vu n'est pas un garde-fou, c'est un piège. Deux citations
       du J8 recopiaient fidèlement le texte affiché, dont celle d'I03.
    2. **La normalisation d'entrée s'applique des deux côtés.** `texte_source` est tranché
       dans le texte d'origine, apostrophes typographiques comprises, là où `texte_autonome`
       est normalisé : une citation ne doit pas tomber sur un « ’ » contre un « ' ».
       :func:`normaliser` est **strictement conservatrice en longueur** et s'applique
       caractère par caractère, donc elle ne peut qu'accepter davantage, jamais rejeter ce
       qui passait déjà.

    Ce qu'elle continue de rejeter, et c'est tout l'objet du garde-fou : une citation
    reformulée, une citation empruntée à l'**autre** clause de la paire, et une citation
    recopiée de l'**en-tête du prompt** plutôt que du texte. Les 4 verdicts restants du J8
    (6 citations) relèvent de ces trois cas.
    """
    if not preuve:
        return False
    cible = normaliser(preuve)
    return any(texte is not None and cible in normaliser(texte) for texte in textes)


def verifier_preuves(
    verdict: Verdict,
    textes: dict[str, str],
    textes_autonomes: dict[str, str] | None = None,
) -> bool:
    """`preuve_a` et `preuve_b` sont-elles des sous-chaînes littérales de leur clause ?

    Invariant #3 de `CLAUDE.md` : aucun verdict sans preuve littérale, vérifiée **en
    Python** après coup. Une preuve absente n'est pas une erreur de programmation — c'est
    le cas d'une modalité qui n'apparaît que dans `texte_autonome` (liste à chapeau, CAP02)
    — mais elle interdit le verdict ferme, et c'est l'appelant qui en tire la conséquence.

    ``textes_autonomes`` est le second texte recevable, celui que le prompt de l'étage C
    montre effectivement au modèle. Omis, la vérification porte sur `texte_source` seul :
    c'est le cas des détecteurs symboliques, qui citent ce qu'ils ont lu.
    """
    autonomes = textes_autonomes or {}
    for clause_id, preuve in ((verdict.clause_a, verdict.preuve_a),
                              (verdict.clause_b, verdict.preuve_b)):
        if preuve is None:
            continue
        if clause_id is None:
            return False
        if not citation_litterale(
            preuve, textes.get(clause_id, ""), autonomes.get(clause_id)
        ):
            return False
    return True
