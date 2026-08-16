"""A1 — conflit déontique et écart de force.

Positif : I04 (PERMISSION contre INTERDICTION, écart 3).
Négatif : N09 (énoncés équivalents, l'un négatif l'autre positif — la portée de
négation doit être gérée, sinon opposition de polarité illusoire).

architecture.md §7.1, corrigé en v2 :

    échelle :  interdiction 4 · obligation 3 · recommandation 2 · permission 1
    ecart = |force(A) − force(B)|   (après application de negation)

    ecart = 0  -> aucun conflit
    ecart = 1  -> DIVERGENCE_PERSPECTIVE, non ferme, escalade obligatoire vers B
    ecart >= 2 -> conflit fort
    polarité opposée -> conflit fort quel que soit l'écart

**La force est recalculée depuis la modalité, jamais reprise de `ClauseFrame.force`.**
`regles/deontique.py` inverse la modalité sous l'effet d'une négation sans toucher à la
force : un « ne doit pas » y devient INTERDICTION en gardant force 3. C'est la modalité qui
fait foi ; la force n'en est que la projection par `config/detection.yaml`.

Déclenchement : conditions non disjointes (§7.2) et un recouvrement d'objets suffisant —
la même discipline de preuve qu'A2, pour la même raison.
"""

from __future__ import annotations

from cohera.detection import config_detection
from cohera.detection.modeles import Motif, TypeVerdict, Verdict
from cohera.detection.portees import RelationPortees, relation_portees
from cohera.extraction.frames import ClauseFrame, Modalite
from cohera.graphe.conditions import Algebre

DETECTEUR = "A1"


def force_de(modalite: Modalite | None) -> int | None:
    """La force d'une modalité, lue dans `config/detection.yaml`.

    ``None`` pour CONSTAT et DEFINITION : une définition ne prescrit rien, elle ne peut pas
    entrer en conflit de force avec une obligation (D1 §3.2 contre D2 §3.2, qui relèvent
    d'A6 et non d'A1).
    """
    if modalite is None:
        return None
    return config_detection.echelle_deontique().get(modalite)


def _polarites_opposees(a: Modalite, b: Modalite) -> bool:
    return frozenset((a, b)) in config_detection.polarites_opposees()


def _aucune(frame_a, frame_b, motif: Motif, explication: str) -> Verdict:
    return Verdict(
        detecteur=DETECTEUR, type=TypeVerdict.AUCUNE, motif=motif,
        explication=explication, clause_a=frame_a.clause_id, clause_b=frame_b.clause_id,
    )


def a1(
    frame_a: ClauseFrame,
    frame_b: ClauseFrame,
    algebre: Algebre,
    *,
    objets_partages: int,
) -> Verdict:
    """Le verdict d'A1 sur une paire — toujours un verdict, fût-il ``AUCUNE``."""
    if frame_a.modalite is None or frame_b.modalite is None:
        return _aucune(
            frame_a, frame_b, Motif.MODALITE_ABSENTE,
            "au moins une des deux clauses n'a pas de modalité déontique",
        )

    force_a, force_b = force_de(frame_a.modalite), force_de(frame_b.modalite)
    if force_a is None or force_b is None:
        return _aucune(
            frame_a, frame_b, Motif.MODALITE_NON_PRESCRIPTIVE,
            f"modalité sans force sur l'échelle ({frame_a.modalite}, {frame_b.modalite})",
        )

    relation = relation_portees(frame_a, frame_b, algebre)
    if relation is RelationPortees.DISJOINTE:
        return _aucune(
            frame_a, frame_b, Motif.PORTEES_DISJOINTES,
            "les deux clauses ne s'appliquent jamais à la même situation",
        )

    ecart = abs(force_a - force_b)
    if ecart == 0:
        return _aucune(
            frame_a, frame_b, Motif.ECART_DE_FORCE_NUL,
            f"même force déontique des deux côtés ({frame_a.modalite}, force {force_a})",
        )

    opposees = _polarites_opposees(frame_a.modalite, frame_b.modalite)
    fort = opposees or ecart >= config_detection.ecart_conflit_fort()

    verdict = Verdict(
        detecteur=DETECTEUR,
        type=TypeVerdict.CONTRADICTION if fort else TypeVerdict.DIVERGENCE_PERSPECTIVE,
        motif=Motif.POLARITE_OPPOSEE if opposees else Motif.ECART_DE_FORCE,
        explication=(
            f"{frame_a.modalite} (force {force_a}) contre {frame_b.modalite} "
            f"(force {force_b}), écart {ecart}"
            + (", polarités opposées" if opposees else "")
        ),
        clause_a=frame_a.clause_id, clause_b=frame_b.clause_id,
        preuve_a=frame_a.modalite_surface, preuve_b=frame_b.modalite_surface,
        type_taxonomie="NEGATION" if opposees else "PERSPECTIVE",
        gravite="CRITIQUE" if opposees else "ELEVEE",
        confiance=0.92 if fort else 0.70,
        relation_portees=relation.value,
        # Un écart de 1 n'est jamais ferme : l'architecture exige l'escalade vers l'étage B.
        ferme=fort,
    )
    return _sceller(verdict, objets_partages)


def _sceller(verdict: Verdict, objets_partages: int) -> Verdict:
    """Garde de fermeté d'A1 : une escalade, jamais un rejet.

    **Une seule garde, là où A2 en a deux — et l'asymétrie est voulue.** A2 rétrograde
    aussi quand la relation des portées est INDÉTERMINÉE : comparer deux valeurs suppose de
    savoir si elles s'appliquent jamais au même cas. A1 non : architecture.md §7.1 ne lui
    demande que des conditions « non disjointes ». Une permission et une interdiction
    portant sur le même acte se contredisent dès que leurs périmètres *peuvent* se
    recouvrir ; exiger de le prouver reviendrait à ne rien conclure.

    Mesuré : I04 (D1 §7.4 « pour les interventions de moins de 30 minutes »,
    POPULATIONNEL, contre D2 §7.4 « sur l'ensemble du site », SPATIAL) est exactement ce
    cas. Aucune règle typée ne relie les deux types, la relation vaut INDÉTERMINÉE, et A1
    la perdrait si on lui appliquait la garde d'A2.
    """
    if not verdict.ferme:
        return verdict
    if objets_partages < config_detection.objets_partages_min():
        return verdict.model_copy(
            update={"ferme": False, "motif": Motif.OBJETS_SANS_RECOUVREMENT}
        )
    return verdict
