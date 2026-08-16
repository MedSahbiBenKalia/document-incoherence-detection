"""A5 — références cassées et référentiels obsolètes.

I09 (renvoi vers un § inexistant), I10 (renvoi inter-documents non résolvable),
I08 (OHSAS 18001 retirée face à ISO 45001). I09 et I10 sont des anomalies
mono-clause : détectées sans aucune comparaison de paire.

**Source : les Clause Frames, jamais le graphe.** `chargeur.py` n'écrit pas d'arête
`RENVOIE_A` — décision actée au J4 — et `Reference.resolu` est de toute façon calculé dès
le J2 par `regles/references.py`, contre les `Segmentation` en mémoire. Passer par Neo4j
n'apporterait rien et ferait dépendre d'un serveur une détection qui n'en a pas besoin.

**Deux passes, deux natures.** :func:`a5_sur_une_clause` ne regarde qu'une clause et ne
coûte donc rien au ciblage — c'est le contre-exemple parfait à « il faut une paire pour
détecter une incohérence ». :func:`a5_normes_divergentes` compare deux clauses, et n'est
appelée que sur les paires candidates.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import BaseModel

from cohera import reglages
from cohera.detection.modeles import Motif, TypeVerdict, Verdict
from cohera.extraction.frames import ClauseFrame, TypeReference

DETECTEUR = "A5"

STATUT_RETIREE = "RETIREE"


class NormeExterne(BaseModel):
    """Une entrée de `config/registre_normes.yaml`."""

    intitule: str = ""
    statut: str = "EN_VIGUEUR"
    versions: list[str] = []
    date_retrait: date | None = None
    remplacee_par: str | None = None
    note: str = ""

    @property
    def obsolete(self) -> bool:
        """Retirée, ou remplacée par une autre — les deux cas d'architecture.md §7.1."""
        return self.statut == STATUT_RETIREE or self.remplacee_par is not None


@lru_cache(maxsize=1)
def charger_registre_normes() -> dict[str, NormeExterne]:
    """Le registre des référentiels, par code — la clé est celle que produit
    `regles/references.py` (« ISO 45001 », « OHSAS 18001 »), version exclue."""
    brut = reglages.charger_config("registre_normes").get("normes", {}) or {}
    return {code: NormeExterne.model_validate(entree or {}) for code, entree in brut.items()}


def vider_caches() -> None:
    charger_registre_normes.cache_clear()


def _normes_citees(frame: ClauseFrame) -> list:
    return [r for r in frame.references if r.type is TypeReference.NORME]


# ------------------------------------------------------------ anomalies mono-clause


def a5_sur_une_clause(frame: ClauseFrame) -> list[Verdict]:
    """Les anomalies qu'une clause porte à elle seule, sans aucune comparaison.

    Deux cas : un renvoi interne que la résolution du J2 n'a pas trouvé, et la citation
    d'un référentiel obsolète. Une clause peut en porter plusieurs, d'où une liste.
    """
    verdicts: list[Verdict] = []

    for reference in frame.references:
        if reference.type is TypeReference.INTERNE and reference.resolu is False:
            verdicts.append(
                Verdict(
                    detecteur=DETECTEUR, type=TypeVerdict.CONTRADICTION,
                    motif=Motif.REFERENCE_CASSEE,
                    explication=f"renvoi vers {reference.cible} — cible introuvable"
                                + (f" dans {reference.document_cible}"
                                   if reference.document_cible else ""),
                    clause_a=frame.clause_id, preuve_a=reference.surface,
                    type_taxonomie="FACTUEL", gravite="MOYENNE", confiance=0.98,
                    ferme=True,
                )
            )

    registre = charger_registre_normes()
    for reference in _normes_citees(frame):
        norme = registre.get(reference.cible)
        if norme is None or not norme.obsolete:
            continue
        remplacement = (
            f", remplacée par {norme.remplacee_par}" if norme.remplacee_par else ""
        )
        retrait = f" le {norme.date_retrait.isoformat()}" if norme.date_retrait else ""
        verdicts.append(
            Verdict(
                detecteur=DETECTEUR, type=TypeVerdict.CONTRADICTION,
                motif=Motif.REFERENTIEL_OBSOLETE,
                explication=f"{reference.cible} a été retirée{retrait}{remplacement}",
                clause_a=frame.clause_id, preuve_a=reference.surface,
                type_taxonomie="FACTUEL", gravite="ELEVEE", confiance=0.97,
                ferme=True,
            )
        )

    return verdicts


# ------------------------------------------------------------ divergence de paire


def a5_normes_divergentes(frame_a: ClauseFrame, frame_b: ClauseFrame) -> Verdict:
    """Deux clauses invoquant des référentiels externes différents.

    ``plus_permissive`` désigne ici la clause **fautive** : celle qui cite le référentiel
    obsolète, quand le registre permet de trancher. Sans registre, la divergence reste un
    constat symétrique et le champ vaut ``None`` — on dit que deux documents divergent, pas
    lequel a tort, ce qui serait une affirmation sans fondement.
    """
    normes_a = _normes_citees(frame_a)
    normes_b = _normes_citees(frame_b)

    aucune = Verdict(
        detecteur=DETECTEUR, type=TypeVerdict.AUCUNE, motif=Motif.REFERENTIEL_DIVERGENT,
        clause_a=frame_a.clause_id, clause_b=frame_b.clause_id,
    )
    if not normes_a or not normes_b:
        return aucune.model_copy(
            update={"explication": "au moins une des deux clauses ne cite aucun référentiel"}
        )

    codes_a = {r.cible for r in normes_a}
    codes_b = {r.cible for r in normes_b}
    if codes_a & codes_b:
        return aucune.model_copy(
            update={"explication": f"référentiel commun : {sorted(codes_a & codes_b)[0]}"}
        )

    registre = charger_registre_normes()
    reference_a, reference_b = normes_a[0], normes_b[0]
    fautive = None
    if (norme := registre.get(reference_b.cible)) is not None and norme.obsolete:
        fautive = "B"
    elif (norme := registre.get(reference_a.cible)) is not None and norme.obsolete:
        fautive = "A"

    detail = (
        f" — {reference_b.cible if fautive == 'B' else reference_a.cible} est obsolète"
        if fautive
        else ""
    )
    return Verdict(
        detecteur=DETECTEUR, type=TypeVerdict.CONTRADICTION,
        motif=Motif.REFERENTIEL_DIVERGENT,
        explication=f"référentiels divergents : {reference_a.cible} contre "
                    f"{reference_b.cible}{detail}",
        clause_a=frame_a.clause_id, clause_b=frame_b.clause_id,
        preuve_a=reference_a.surface, preuve_b=reference_b.surface,
        type_taxonomie="FACTUEL", gravite="ELEVEE", confiance=0.95,
        plus_permissive=fautive, ferme=True,
    )
