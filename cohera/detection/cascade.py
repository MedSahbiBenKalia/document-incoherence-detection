"""Orchestration des étages A, B et C, et arrêt au premier verdict fermé.

L'étage A (J5) est ici, :func:`detecter` ; l'étage B (J8) est :func:`etage_b` ; l'étage C
vit dans `juge_llm.py`, appelé par la CLI juste après. La distinction entre ce qui est
**conclu** et ce qui est **escaladé**, posée dès le J5, est ce qui permet aux deux étages
suivants de savoir sur quoi travailler.

**L'ordre coûte de moins en moins cher, et il est strict** : trois détecteurs symboliques
d'abord, puis 47 ms d'inférence NLI, puis seulement un appel réseau. Chaque étage ne voit
que ce que le précédent n'a ni conclu ni fermé.

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

from typing import Sequence

from pydantic import BaseModel, Field

from cohera import reglages
from cohera.ciblage import Ciblage
from cohera.detection import config_detection
from cohera.detection.modeles import Motif, TypeVerdict, Verdict, verifier_preuves
from cohera.detection.nli import DETECTEUR as DETECTEUR_NLI
from cohera.detection.nli import Infereur, ResultatNLI, ZoneNLI, scorer
from cohera.detection.objets import objets_partages
from cohera.detection.symbolique.a1 import a1
from cohera.detection.symbolique.a2 import a2
from cohera.detection.symbolique.a5 import a5_normes_divergentes, a5_sur_une_clause
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.alias import Pont
from cohera.graphe.concepts import Vocabulaire
from cohera.graphe.conditions import Algebre, construire_algebre
from cohera.ingestion.modeles import Clause


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


# ------------------------------------------------------------------------ étage B (J8)


def etage_b(
    detection: Detection,
    paires: Sequence[tuple[str, str]],
    clauses: dict[str, Clause],
    *,
    inferer: Infereur | None = None,
) -> ResultatNLI:
    """Le NLI, entre l'étage A et le LLM juge. **Ne ferme que par le bas.**

    ``paires`` est la liste que `juge_llm.paires_a_juger` vient de rendre : l'étage B voit
    exactement ce que le juge verrait, ni plus ni moins. Il reçoit des couples
    d'identifiants plutôt que des `PaireAJuger` — `juge_llm` importe déjà ce module, et lui
    répondre en type l'y enfermerait dans un cycle.

    **Ce qui est écrit dans la `Detection`, et ce qui ne l'est pas.** Seuls les rejets
    produisent un verdict : `COHERENT` / `REJET_NLI`, rangé dans les muets, et la paire
    disparaît du périmètre du juge parce que `REJET_NLI` figure dans `juge.motifs_fermants`
    — aucune ligne neuve dans `paires_a_juger`.

    ⭐ **Les zones haute et grise n'écrivent rien.** Deux raisons, la seconde purement
    mécanique. D'une part l'étage B n'a pas de citation à produire (invariant #3), et la
    mesure du J8 montre que sa bande haute mêle vrais et faux. D'autre part un verdict de
    l'étage B rangé dans les escalades deviendrait `escalades[0]`, donc le `SIGNAL AMONT`
    du prompt, pour les 21 paires que l'étage A laisse sans donnée — dont I11. Leur clé de
    cache changerait, et les mesures des J6 et J7 cesseraient d'être comparables sans être
    intégralement repayées. Un test l'exige explicitement.
    """
    scores = scorer(paires, clauses, inferer=inferer)
    rejet, contradiction = config_detection.seuils_nli()
    resultat = ResultatNLI(
        modele=reglages.charger().nli.modele,
        seuil_rejet=rejet, seuil_contradiction=contradiction, scores=scores,
    )

    for score in scores:
        if score.zone is not ZoneNLI.REJET:
            continue
        ranger(detection, Verdict(
            detecteur=DETECTEUR_NLI, type=TypeVerdict.COHERENT, motif=Motif.REJET_NLI,
            clause_a=score.clause_a, clause_b=score.clause_b, etage="B",
            confiance=1.0 - score.p_contradiction,
            explication=(
                f"aucune contradiction dans l'un ni l'autre sens "
                f"(P max = {score.p_contradiction:.3f} <= {rejet}) — paire close avant le juge"
            ),
        ))
    return resultat


def ranger(detection: Detection, verdict: Verdict) -> None:
    """Range un verdict dans la seule rubrique qui lui revient.

    L'ordre des tests est significatif et n'a pas changé au J6 : ``AUCUNE`` gagne sur
    ``ferme``, et l'escalade sur le type. Les deux issues de l'étage C sont ajoutées
    **avant** le test de fermeté, parce qu'une abstention est fermée au sens où personne ne
    la reprendra, sans être pour autant une affirmation.

    L'etage B du J8 n'ajoute pas de branche : son rejet est un `COHERENT`, qui tombe
    donc dans les muets par le test existant.
    """
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
