"""A2 — divergence de valeurs, sous réserve du recouvrement des portées.

Positif : I01, I02, I03, I13, I14, I15.
Négatif : N01 (spécialisation), N04 (conditions disjointes), N06 (12 mois = 1 an
après normalisation), N08 (même dimension, objets sans rapport).

**L'ordre des gardes compte** (architecture.md §7.1) :

1. un couple ``(dimension, role)`` commun, sinon il n'y a rien à comparer ;
2. la relation des portées — DISJOINTE arrête tout, avant même de regarder les valeurs ;
3. les valeurs elles-mêmes, comparées en entiers SI ;
4. sous inclusion, la monotonie du rôle décide : plus stricte = spécialisation légitime,
   plus permissive = contradiction.

Puis, sur un verdict positif, trois gardes de **fermeté**. Aucune ne rejette : elles
transforment une affirmation en escalade vers les étages B et C du J6
(`.claude/rules/detection.md`).

* **portée indéterminée** — comparer deux valeurs suppose de savoir si elles s'appliquent
  jamais au même cas.
* **objets partagés** — le ciblage dit qu'une paire mérite examen, pas qu'elle porte sur le
  même objet. Sans cette garde, A2 rend 4 constatations fausses sur ce corpus et la
  précision tombe à 0,75 ; avec elle, 0 faux positif. Distribution mesurée et cas
  concernés : `config/detection.yaml`, section `preuve`.
* **grandeur imprécise** — « dans la semaine » porte une valeur nominale (CAP04), pas une
  mesure ; elle ne fonde pas une affirmation.

Plus une quatrième, appliquée en aval par `cascade.sceller_preuves` pour tous les
détecteurs à la fois : la **preuve littérale** (invariant #3).

I12 tombe sous la garde des objets — zéro objet canonique partagé, `anomalie`/`écart` étant
sous le seuil d'alias depuis le J3 — et escalade, là où `label.json` l'attend à l'étage A.
C'est le critère rouge du J5, consigné au Journal et figé par un test.
"""

from __future__ import annotations

from cohera.detection import config_detection
from cohera.detection.modeles import Motif, TypeVerdict, Verdict
from cohera.detection.portees import RelationPortees, plus_permissive, relation_portees
from cohera.extraction.frames import ClauseFrame, Grandeur, StatutGrandeur
from cohera.graphe.conditions import Algebre

DETECTEUR = "A2"

#: Sous inclusion, quelle clause porte la contrainte restreinte.
_RESTREINTE = {
    RelationPortees.INCLUSION_A_DANS_B: "A",
    RelationPortees.INCLUSION_B_DANS_A: "B",
}


def _couples_comparables(
    frame_a: ClauseFrame, frame_b: ClauseFrame
) -> list[tuple[Grandeur, Grandeur]]:
    return [
        (qa, qb)
        for qa in frame_a.quantites
        for qb in frame_b.quantites
        if (qa.dimension, qa.role) == (qb.dimension, qb.role)
    ]


def _aucune(frame_a, frame_b, motif: Motif, explication: str) -> Verdict:
    return Verdict(
        detecteur=DETECTEUR, type=TypeVerdict.AUCUNE, motif=motif,
        explication=explication, clause_a=frame_a.clause_id, clause_b=frame_b.clause_id,
    )


def a2(
    frame_a: ClauseFrame,
    frame_b: ClauseFrame,
    algebre: Algebre,
    *,
    objets_partages: int,
) -> Verdict:
    """Le verdict d'A2 sur une paire — toujours un verdict, fût-il ``AUCUNE``.

    ``objets_partages`` est le nombre de concepts canoniques de type OBJET communs aux deux
    clauses (`detection/objets.py`). Sans valeur par défaut, volontairement : un appelant
    qui l'oublierait obtiendrait des verdicts fermes qu'aucune preuve d'objet ne soutient,
    et le test qui l'aurait laissé passer serait vert pour rien.
    """
    couples = _couples_comparables(frame_a, frame_b)
    if not couples:
        return _aucune(
            frame_a, frame_b, Motif.PAS_DE_GRANDEUR_COMPARABLE,
            "aucun couple (dimension, rôle) commun aux deux clauses",
        )

    relation = relation_portees(frame_a, frame_b, algebre)
    if relation is RelationPortees.DISJOINTE:
        return _aucune(
            frame_a, frame_b, Motif.PORTEES_DISJOINTES,
            "les deux clauses ne s'appliquent jamais à la même situation",
        )

    divergent = [
        (qa, qb)
        for qa, qb in couples
        if qa.valeur_si is not None and qb.valeur_si is not None
        and qa.valeur_si != qb.valeur_si
    ]
    if not divergent:
        return _verdict_sans_divergence(frame_a, frame_b, couples)

    qa, qb = divergent[0]
    verdict = _verdict_de_divergence(frame_a, frame_b, qa, qb, relation)
    return _sceller(verdict, qa, qb, relation, objets_partages)


# --------------------------------------------------------------- valeurs identiques


def _verdict_sans_divergence(frame_a, frame_b, couples) -> Verdict:
    """Valeurs égales — sauf si les qualificateurs, eux, divergent.

    « 5 jours ouvrés » et « 5 jours calendaires » portent la même `valeur_si` nominale et
    ne recouvrent pourtant pas la même durée réelle. Le constat est faible et jamais ferme.
    """
    for qa, qb in couples:
        if qa.qualificateurs and qb.qualificateurs and qa.qualificateurs != qb.qualificateurs:
            return Verdict(
                detecteur=DETECTEUR, type=TypeVerdict.CONTRADICTION,
                motif=Motif.QUALIFICATEURS_DIVERGENTS,
                explication=f"même valeur, qualificateurs différents : "
                            f"{qa.qualificateurs} contre {qb.qualificateurs}",
                clause_a=frame_a.clause_id, clause_b=frame_b.clause_id,
                preuve_a=qa.surface, preuve_b=qb.surface,
                type_taxonomie="NUMERIQUE", gravite="FAIBLE", confiance=0.60,
                ferme=False,
            )
    return _aucune(
        frame_a, frame_b, Motif.VALEURS_EGALES,
        "valeurs identiques après normalisation en unités SI",
    )


# ------------------------------------------------------------------- la divergence


def _verdict_de_divergence(
    frame_a, frame_b, qa: Grandeur, qb: Grandeur, relation: RelationPortees
) -> Verdict:
    permissive = plus_permissive(qa, qb, qa.monotonie)
    ecart = abs(qa.valeur_si - qb.valeur_si) / max(qa.valeur_si, qb.valeur_si)

    commun = dict(
        detecteur=DETECTEUR, clause_a=frame_a.clause_id, clause_b=frame_b.clause_id,
        preuve_a=qa.surface, preuve_b=qb.surface, type_taxonomie="NUMERIQUE",
        relation_portees=relation.value, plus_permissive=permissive,
        gravite=config_detection.gravite_par_ecart(ecart),
    )

    restreinte = _RESTREINTE.get(relation)
    if restreinte is not None:
        if permissive != restreinte:
            # La clause au périmètre le plus étroit est aussi la plus stricte : c'est une
            # déclinaison légitime, pas une divergence (architecture.md §7.2, correction v2).
            return Verdict(
                type=TypeVerdict.SPECIALISATION, motif=Motif.INCLUSION_PLUS_STRICTE,
                explication=f"la clause {restreinte}, de portée plus étroite, est aussi la "
                            f"plus stricte ({qa.surface} contre {qb.surface})",
                confiance=0.90, ferme=True, **commun,
            )
        return Verdict(
            type=TypeVerdict.CONTRADICTION, motif=Motif.INCLUSION_PLUS_PERMISSIVE,
            explication=f"la clause {restreinte}, de portée plus étroite, est PLUS "
                        f"PERMISSIVE que la règle générale ({qa.surface} contre {qb.surface})",
            confiance=0.93, ferme=True, **commun,
        )

    return Verdict(
        type=TypeVerdict.CONTRADICTION, motif=Motif.VALEURS_DIVERGENTES,
        explication=f"même grandeur, même périmètre, valeurs différentes : "
                    f"{qa.surface} contre {qb.surface} (écart {ecart:.0%})",
        confiance=0.95, ferme=True, **commun,
    )


# ---------------------------------------------------------------- gardes de fermeté


def _sceller(
    verdict: Verdict,
    qa: Grandeur,
    qb: Grandeur,
    relation: RelationPortees,
    objets_partages: int,
) -> Verdict:
    """Rétrograde un verdict en escalade quand la preuve ne le porte pas.

    Jamais un rejet : le verdict reste, avec son type et son explication, et le J6 le
    reprendra à l'étage B ou C.
    """
    if not verdict.ferme:
        return verdict

    if relation is RelationPortees.INDETERMINEE:
        return verdict.model_copy(
            update={"ferme": False, "motif": Motif.PORTEE_INDETERMINEE}
        )

    if objets_partages < config_detection.objets_partages_min():
        return verdict.model_copy(
            update={"ferme": False, "motif": Motif.OBJETS_SANS_RECOUVREMENT}
        )

    if any(q.statut is not StatutGrandeur.NORMAL for q in (qa, qb)):
        return verdict.model_copy(
            update={"ferme": False, "motif": Motif.GRANDEUR_IMPRECISE}
        )

    return verdict
