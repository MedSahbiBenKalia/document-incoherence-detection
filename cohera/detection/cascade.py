"""Orchestration des étages A, B et C, et arrêt au premier verdict fermé.

Au J5, seul l'étage A existe : trois détecteurs symboliques, aucun modèle. Les étages B
(NLI) et C (LLM juge) sont le J6 ; ce module leur prépare le terrain en distinguant, dès
maintenant, ce qui est **conclu** de ce qui est **escaladé**.

**Invariant #2 — rien de cher avant le ciblage.** La passe par paire ne voit que les
`PAIRE_CANDIDATE` du J4. La passe mono-clause d'A5, elle, ne compare rien : elle est
gratuite et s'applique à toutes les clauses.

**Invariant #4 — le détecteur le moins cher traite le cas.** A2 avant A1 : une comparaison
d'entiers avant une comparaison de modalités et une lecture de configuration. On s'arrête
au premier verdict **ferme** ; les verdicts non fermes sont tous conservés, parce que c'est
sur eux que le J6 travaillera.

**Invariant #3 — aucun verdict sans preuve littérale.** :func:`sceller_preuves` le vérifie
en Python, une fois, pour tous les détecteurs : un verdict ferme doit porter une preuve de
chaque côté, et chacune doit être une sous-chaîne exacte de `texte_source`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cohera.ciblage import Ciblage
from cohera.detection.modeles import Motif, Verdict, verifier_preuves
from cohera.detection.objets import objets_partages
from cohera.detection.symbolique.a1 import a1
from cohera.detection.symbolique.a2 import a2
from cohera.detection.symbolique.a5 import a5_normes_divergentes, a5_sur_une_clause
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.alias import Pont
from cohera.graphe.concepts import Vocabulaire
from cohera.graphe.conditions import Algebre, construire_algebre


class Detection(BaseModel):
    """Le résultat de la cascade — auditable, comme le :class:`~cohera.ciblage.Ciblage`.

    On garde les constatations *et* les escalades *et* les verdicts muets : c'est ce qui
    permet de répondre à « pourquoi cette paire n'a-t-elle rien donné ? » aussi bien qu'à
    « pourquoi celle-là a-t-elle été retenue ? ».
    """

    #: Verdicts fermes qui affirment quelque chose — le numérateur de la précision.
    constatations: list[Verdict] = Field(default_factory=list)
    #: Verdicts fermes de type SPECIALISATION : compatibles, donc listés à part (N01).
    specialisations: list[Verdict] = Field(default_factory=list)
    #: Verdicts non fermes — la matière des étages B et C du J6.
    escalades: list[Verdict] = Field(default_factory=list)
    #: Verdicts `AUCUNE`, conservés avec leur motif : un rejet est journalisé, pas silencieux.
    muets: list[Verdict] = Field(default_factory=list)
    #: J6 — le juge n'a pas tranché : abstention, preuve inventée, budget, panne.
    #: Rubrique distincte des `muets` : ici personne n'a conclu, alors qu'un `muet` porte
    #: une raison positive de se taire.
    abstentions: list[Verdict] = Field(default_factory=list)

    paires_examinees: int = 0
    clauses_examinees: int = 0

    @property
    def rubriques(self) -> tuple[list[Verdict], ...]:
        return (
            self.constatations, self.specialisations,
            self.escalades, self.muets, self.abstentions,
        )

    def verdicts_de(self, clause_a: str, clause_b: str | None = None) -> list[Verdict]:
        """Tous les verdicts portant sur une paire — dans n'importe quelle rubrique."""
        cible = frozenset((clause_a, clause_b))
        return [
            v
            for rubrique in self.rubriques
            for v in rubrique
            if frozenset((v.clause_a, v.clause_b)) == cible
        ]

    def constatation_sur(self, clause_a: str, clause_b: str | None = None) -> Verdict | None:
        cible = frozenset((clause_a, clause_b))
        for verdict in self.constatations:
            if frozenset((verdict.clause_a, verdict.clause_b)) == cible:
                return verdict
        return None


# ------------------------------------------------------------------ preuve littérale


def sceller_preuves(verdict: Verdict, textes: dict[str, str]) -> Verdict:
    """Rétrograde un verdict ferme dont la preuve littérale ne tient pas.

    Deux causes possibles, toutes deux légitimes et aucune fatale : une preuve absente —
    `modalite_surface` vaut `None` quand le marqueur déontique n'apparaît que dans
    `texte_autonome`, cas d'une liste à chapeau (CAP02) — ou une preuve qui ne se vérifie
    pas comme sous-chaîne de `texte_source`.

    Dans les deux cas le verdict escalade au lieu d'affirmer : c'est l'invariant #3 de
    `CLAUDE.md` appliqué en Python après l'appel, et non confié au détecteur.
    """
    if not verdict.ferme:
        return verdict

    attendues = [verdict.preuve_a] + ([verdict.preuve_b] if verdict.clause_b else [])
    if any(preuve is None for preuve in attendues) or not verifier_preuves(verdict, textes):
        return verdict.model_copy(
            update={"ferme": False, "motif": Motif.PREUVE_LITTERALE_ABSENTE}
        )
    return verdict


# ------------------------------------------------------------------------ la cascade


def detecter(
    ciblage: Ciblage,
    frames: dict[str, ClauseFrame],
    textes: dict[str, str],
    vocabulaire: Vocabulaire,
    pont: Pont,
    algebre: Algebre | None = None,
) -> Detection:
    """L'étage A sur tout le corpus : la passe mono-clause, puis les paires candidates.

    ``vocabulaire`` et ``pont`` servent au seul comptage des objets partagés
    (`detection/objets.py`), la garde de précision d'A1 et A2.
    """
    algebre = algebre if algebre is not None else construire_algebre(frames)
    detection = Detection(clauses_examinees=len(frames))

    for frame in frames.values():
        for verdict in a5_sur_une_clause(frame):
            ranger(detection, sceller_preuves(verdict, textes))

    for paire in ciblage.candidates:
        frame_a, frame_b = frames.get(paire.clause_a), frames.get(paire.clause_b)
        if frame_a is None or frame_b is None:
            continue
        detection.paires_examinees += 1
        partages = objets_partages(paire.clause_a, paire.clause_b, vocabulaire, pont)
        _juger_une_paire(detection, frame_a, frame_b, algebre, partages, textes)

    return detection


def _juger_une_paire(
    detection: Detection,
    frame_a: ClauseFrame,
    frame_b: ClauseFrame,
    algebre: Algebre,
    partages: int,
    textes: dict[str, str],
) -> None:
    """A2, puis A1, puis A5 — du moins cher au plus cher, arrêt au premier verdict ferme.

    Les verdicts non fermes ne closent pas la paire : un autre détecteur peut encore
    conclure là où le précédent a seulement escaladé.

    A5 est le seul à ne pas recevoir le compte d'objets partagés : une divergence de
    référentiel s'établit contre `registre_normes.yaml`, pas contre un recouvrement
    lexical. I08 partage zéro objet et reste pourtant une constatation fondée.
    """
    for detecteur in (a2, a1):
        verdict = detecteur(frame_a, frame_b, algebre, objets_partages=partages)
        verdict = sceller_preuves(verdict, textes)
        ranger(detection, verdict)
        if verdict.ferme:
            return

    verdict = sceller_preuves(a5_normes_divergentes(frame_a, frame_b), textes)
    ranger(detection, verdict)


def ranger(detection: Detection, verdict: Verdict) -> None:
    """Range un verdict dans la seule rubrique qui lui revient.

    L'ordre des tests est significatif et n'a pas changé au J6 : ``AUCUNE`` gagne sur
    ``ferme``, et l'escalade sur le type. Les deux issues de l'étage C sont ajoutées
    **avant** le test de fermeté, parce qu'une abstention est fermée au sens où personne ne
    la reprendra, sans être pour autant une affirmation.
    """
    from cohera.detection.modeles import TypeVerdict

    if verdict.type is TypeVerdict.AUCUNE:
        detection.muets.append(verdict)
    elif verdict.type is TypeVerdict.INDECIDABLE:
        detection.abstentions.append(verdict)
    elif verdict.type is TypeVerdict.COHERENT:
        detection.muets.append(verdict)
    elif not verdict.ferme:
        detection.escalades.append(verdict)
    elif verdict.type is TypeVerdict.SPECIALISATION:
        detection.specialisations.append(verdict)
    else:
        detection.constatations.append(verdict)
