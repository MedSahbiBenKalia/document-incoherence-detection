"""Ablations : mesurer ce que chaque composant apporte vraiment.

Canal 5 retiré, seuil d'alias abaissé à 0,65 (LIM01 serait détectée mais des
alias erronés apparaîtraient), embeddings CPU contre GPU, LLM local contre
distant.

Le J4 en produit une seule, exigée par le plan : **le rappel du ciblage avec et sans le pont
inter-documents**. Les autres viennent au J7, pilotées par des drapeaux de la CLI.

⚠️ **Ce que cette ablation ablate, et ce qu'elle n'ablate pas.** Le pont intervient à deux
moments, et un seul est réversible à la requête :

* *à la requête* — le canal conceptuel et le calcul des concepts canoniques traversent
  `ALIAS_DE`. C'est ce que `avec_pont=False` supprime.
* *au chargement* — `graphe/chargeur.py::cle_comparaison` remplace chaque terme par le
  représentant canonique de sa classe **avant** d'écrire la clé sur la clause. Rejouer le
  ciblage sans le pont ne défait pas ce calcul : le canal CLE continue de voir les clés
  canonicalisées du J3.

La mesure du canal CLE est donc **optimiste** dans la branche « sans pont ». Plutôt que de
recharger tout le graphe pour la corriger — ce qui rendrait l'ablation lente et destructrice
—, :func:`apport_du_pont_sur_la_cle` la chiffre directement en recalculant les clés en
mémoire, avec et sans pont. Les deux chiffres sont rendus ensemble.
"""

from __future__ import annotations

from typing import Any

from neo4j import Session
from pydantic import BaseModel, Field

from cohera.ciblage import Ciblage, cibler
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.alias import Pont
from cohera.graphe.chargeur import cle_comparaison
from cohera.graphe.concepts import Vocabulaire


class BrancheAblation(BaseModel):
    """Une branche de l'ablation : le ciblage obtenu dans une configuration donnée."""

    nom: str
    paires_candidates: int = 0
    facteur_reduction: float = 0.0
    appariements_par_canal: dict[str, int] = Field(default_factory=dict)
    rappel_ciblage: str = ""
    incoherences_manquees: list[str] = Field(default_factory=list)


class ResultatAblation(BaseModel):
    """Les deux branches, plus le chiffre que la branche « sans pont » ne peut pas voir."""

    avec: BrancheAblation
    sans: BrancheAblation
    #: Paires que le canal CLE ne doit qu'à la canonicalisation faite au chargement.
    paires_cle_dues_au_pont: int = 0
    #: Rappel perdu en retirant le pont, en nombre d'incohérences du périmètre.
    perte_de_rappel: int = 0


# ------------------------------------------------------- la part du pont dans la clé


def apport_du_pont_sur_la_cle(
    clause_ids_par_document: dict[str, list[str]],
    frames: dict[str, ClauseFrame],
    vocabulaire: Vocabulaire,
    pont: Pont,
) -> int:
    """Combien de paires du canal CLE disparaîtraient si la clé n'était pas canonicalisée.

    Recalcule les clés deux fois en mémoire — avec le pont, puis avec un pont vide — et
    compte les paires inter-documents que seule la première version apparie. Aucun accès au
    graphe : c'est une propriété de `cle_comparaison`, pas du chargement.
    """
    def paires(pont_utilise: Pont) -> set[tuple[str, str]]:
        cles = {
            doc_id: {
                clause_id: cle_comparaison(clause_id, frames, vocabulaire, pont_utilise)
                for clause_id in clause_ids
            }
            for doc_id, clause_ids in clause_ids_par_document.items()
        }
        documents = sorted(cles)
        trouvees: set[tuple[str, str]] = set()
        for indice, gauche in enumerate(documents):
            for droite in documents[indice + 1 :]:
                for id_a, cle_a in cles[gauche].items():
                    for id_b, cle_b in cles[droite].items():
                        if cle_a and cle_a == cle_b:
                            trouvees.add((id_a, id_b))
        return trouvees

    return len(paires(pont) - paires(Pont()))


# ---------------------------------------------------------------------- l'ablation


def ablation_pont(
    session: Session,
    frames: dict[str, ClauseFrame],
    verite: dict[str, Any],
    correspondance: dict[tuple[str, str], str],
    vocabulaire: Vocabulaire | None = None,
    pont: Pont | None = None,
) -> ResultatAblation:
    """Rejoue le ciblage avec et sans le pont inter-documents.

    ``correspondance`` traduit un couple ``(doc, ref)`` de `label.json` en ``clause_id`` :
    c'est la même correspondance que produit `cohera corpus verifier`.
    """
    branches = {}
    manquees_par_branche = {}
    for nom, avec_pont in (("avec", True), ("sans", False)):
        ciblage = cibler(session, frames, avec_pont=avec_pont)
        atteintes, manquees = _rappel_ciblage(ciblage, verite, correspondance)
        branches[nom] = BrancheAblation(
            nom=f"{'avec' if avec_pont else 'sans'} pont inter-documents",
            paires_candidates=len(ciblage.candidates),
            facteur_reduction=ciblage.facteur_reduction,
            appariements_par_canal={
                canal: len(liste) for canal, liste in sorted(ciblage.par_canal.items())
            },
            rappel_ciblage=f"{len(atteintes)}/{len(atteintes) + len(manquees)}",
            incoherences_manquees=manquees,
        )
        manquees_par_branche[nom] = manquees

    dues = 0
    if vocabulaire is not None and pont is not None:
        par_document: dict[str, list[str]] = {}
        for (doc, _ref), clause_id in correspondance.items():
            par_document.setdefault(doc, []).append(clause_id)
        dues = apport_du_pont_sur_la_cle(par_document, frames, vocabulaire, pont)

    return ResultatAblation(
        avec=branches["avec"],
        sans=branches["sans"],
        paires_cle_dues_au_pont=dues,
        perte_de_rappel=len(manquees_par_branche["sans"]) - len(manquees_par_branche["avec"]),
    )


def _rappel_ciblage(
    ciblage: Ciblage,
    verite: dict[str, Any],
    correspondance: dict[tuple[str, str], str],
) -> tuple[list[str], list[str]]:
    """Les incohérences du périmètre 7 jours que le ciblage met à portée de la cascade.

    Une anomalie mono-clause (I09, I10) n'a aucune paire à cibler : la question devient « la
    clause a-t-elle été analysée », et la réponse est oui dès qu'elle a un contexte. Sans
    cette distinction, la cible 12/12 serait inatteignable par construction.
    """
    atteintes: list[str] = []
    manquees: list[str] = []

    for entree in verite.get("incoherences", []):
        if not entree.get("dans_perimetre_7j"):
            continue
        a = entree.get("clause_a") or {}
        b = entree.get("clause_b")
        identifiant = entree.get("id", "?")

        id_a = correspondance.get((a.get("doc", ""), a.get("ref", "")))
        if b is None:
            ok = id_a is not None and id_a in ciblage.contextes
        else:
            id_b = correspondance.get((b.get("doc", ""), b.get("ref", "")))
            ok = bool(id_a and id_b and ciblage.est_candidate(id_a, id_b))

        (atteintes if ok else manquees).append(identifiant)

    return atteintes, manquees


# ═══════════════════════════════════════════════ J7 — les trois ablations du plan


class BrancheJ7(BaseModel):
    """Une branche des ablations du J7, mesurée de bout en bout à étage A constant."""

    nom: str
    drapeau: str = ""
    paires_candidates: int = 0
    appariements_par_canal: dict[str, int] = Field(default_factory=dict)
    rappel_ciblage: str = ""
    non_ciblees: list[str] = Field(default_factory=list)
    constatations: int = 0
    vrais_positifs: int = 0
    faux_positifs: int = 0
    rappel: str = ""
    precision: float = 0.0
    manquees: list[str] = Field(default_factory=list)
    duree_s: float = 0.0


class AblationsJ7(BaseModel):
    reference: BrancheJ7
    branches: list[BrancheJ7] = Field(default_factory=list)
    #: Paires que le canal CLE ne doit qu'à la canonicalisation faite au CHARGEMENT, et que
    #: la branche « sans alias » ne peut donc pas retirer. Chiffré à part, jamais masqué.
    paires_cle_dues_au_pont: int = 0


def _mesurer_une_branche(
    session,
    nom: str,
    drapeau: str,
    frames,
    segmentations,
    vocabulaire,
    pont,
    verite,
    *,
    avec_pont: bool = True,
    canaux_desactives=None,
) -> BrancheJ7:
    """Rejoue ciblage + étage A dans une configuration, et confronte le tout à la vérité terrain.

    ⚠️ **L'étage C ne tourne dans aucune branche, et c'est délibéré.** Changer le ciblage
    change l'ensemble des paires soumises au juge, donc toutes les clés de cache : chaque
    branche coûterait une cinquantaine d'appels réseau neufs, et le tableau mêlerait l'effet
    du canal à celui du modèle. À étage A constant, l'ablation mesure ce qu'elle prétend
    mesurer — l'apport du composant retiré, et lui seul.
    """
    import time

    from cohera.consolidation.constatations import regrouper
    from cohera.detection.cascade import detecter
    from cohera.detection.objets import objets_canoniques  # noqa: F401  (contrat de `detecter`)
    from cohera.evaluation import metriques
    from cohera.graphe.alias import Pont as PontVide
    from cohera.graphe.conditions import construire_algebre
    from cohera.restitution.rapport_json import (
        Constatation,
        CoteClause,
        PaireCandidate,
        Rapport,
        RefClause,
        Statistiques,
    )

    depart = time.perf_counter()
    pont_utilise = pont if avec_pont else PontVide()

    ciblage = cibler(
        session, frames, avec_pont=avec_pont, canaux_desactives=canaux_desactives
    )

    clauses = {c.clause_id: c for s in segmentations.values() for c in s.clauses}
    textes = {cid: c.texte_source for cid, c in clauses.items()}
    detection = detecter(
        ciblage, frames, textes, vocabulaire, pont_utilise, construire_algebre(frames)
    )

    def reference_de(clause_id):
        clause = clauses.get(clause_id)
        return RefClause(
            doc=clause.doc_id if clause else "",
            ref=clause.ref if clause else "",
            clause_id=clause_id,
        )

    def cote(clause_id, preuve):
        if clause_id is None:
            return None
        clause = clauses.get(clause_id)
        return CoteClause(
            doc=clause.doc_id if clause else "",
            ref=clause.ref if clause else "",
            clause_id=clause_id,
            preuve=preuve or "",
            texte_source=clause.texte_source if clause else None,
        )

    rapport = Rapport(
        statistiques=Statistiques(
            paires_theoriques=ciblage.paires_theoriques,
            paires_candidates=len(ciblage.candidates),
        ),
        clauses_analysees=[reference_de(cid) for cid in sorted(ciblage.contextes)],
        paires_candidates=[
            PaireCandidate(
                clause_a=reference_de(p.clause_a), clause_b=reference_de(p.clause_b)
            )
            for p in ciblage.candidates
        ],
        constatations=regrouper(
            [
                Constatation(
                    id=f"{v.detecteur}-{i:03d}",
                    type=v.type_taxonomie or v.type.value,
                    clause_a=cote(v.clause_a, v.preuve_a),
                    clause_b=cote(v.clause_b, v.preuve_b),
                    gravite=v.gravite,
                    detecteur=v.detecteur,
                    etage=v.etage,
                    confiance=v.confiance,
                )
                for i, v in enumerate(detection.constatations, start=1)
            ]
        ),
    )

    resultat = metriques.evaluer(rapport, verite)
    bareme = resultat.perimetre_7j

    return BrancheJ7(
        nom=nom,
        drapeau=drapeau,
        paires_candidates=len(ciblage.candidates),
        appariements_par_canal={c: len(v) for c, v in sorted(ciblage.par_canal.items())},
        rappel_ciblage=f"{round(bareme.rappel_ciblage * 12):d}/12",
        non_ciblees=bareme.ciblage_manquants,
        constatations=len(rapport.constatations),
        vrais_positifs=len(bareme.vrais_positifs),
        faux_positifs=len(bareme.faux_positifs),
        rappel=f"{len(bareme.vrais_positifs)}/{bareme.attendues}",
        precision=round(bareme.precision, 4),
        manquees=bareme.faux_negatifs,
        duree_s=round(time.perf_counter() - depart, 2),
    )


def ablations_du_j7(
    session, frames, segmentations, vocabulaire, pont, verite, correspondance
) -> AblationsJ7:
    """Les trois ablations que le plan §J7 exige, plus la référence qui leur donne un sens.

    `--sans-etage-c` n'apparaît pas comme une branche à part : **toutes** les branches
    tournent à étage A seul, si bien que la référence de ce tableau *est* le système sans
    étage C. L'apport de l'étage C se lit en comparant cette référence au rapport complet,
    et il a été mesuré au J6 comme au J7.
    """
    from cohera.ciblage.modeles import Canal

    reference = _mesurer_une_branche(
        session, "référence (étage A)", "—",
        frames, segmentations, vocabulaire, pont, verite,
    )
    sans_alias = _mesurer_une_branche(
        session, "sans le pont d'alias", "--sans-alias",
        frames, segmentations, vocabulaire, pont, verite, avec_pont=False,
    )
    sans_canal5 = _mesurer_une_branche(
        session, "sans le canal DIMENSION", "--sans-canal5",
        frames, segmentations, vocabulaire, pont, verite,
        canaux_desactives=frozenset({Canal.DIMENSION}),
    )

    par_document: dict[str, list[str]] = {}
    for (doc, _ref), clause_id in correspondance.items():
        par_document.setdefault(doc, []).append(clause_id)

    return AblationsJ7(
        reference=reference,
        branches=[sans_alias, sans_canal5],
        paires_cle_dues_au_pont=apport_du_pont_sur_la_cle(
            par_document, frames, vocabulaire, pont
        ),
    )


def formater_ablations_j7(resultat: AblationsJ7, couleur: bool = True) -> str:
    """Le tableau chiffré que le critère d'acceptation du J7 réclame."""
    gras, fin = ("\033[1m", "\033[0m") if couleur else ("", "")
    toutes = [resultat.reference] + resultat.branches

    lignes = [
        f"{gras}Ablations du J7 — ce que chaque brique apporte, mesuré{fin}",
        "",
        f"{'branche':<24} {'drapeau':<15} {'cand.':>6} {'ciblage':>8} {'const.':>7} "
        f"{'VP':>3} {'FP':>3} {'rappel':>7} {'préc.':>6} {'durée':>7}",
        "-" * 104,
    ]
    for branche in toutes:
        lignes.append(
            f"{branche.nom:<24} {branche.drapeau:<15} {branche.paires_candidates:>6} "
            f"{branche.rappel_ciblage:>8} {branche.constatations:>7} "
            f"{branche.vrais_positifs:>3} {branche.faux_positifs:>3} "
            f"{branche.rappel:>7} {branche.precision:>6.2f} {branche.duree_s:>6.1f}s"
        )

    lignes += ["", f"{gras}Écart à la référence{fin}"]
    for branche in resultat.branches:
        perte = resultat.reference.vrais_positifs - branche.vrais_positifs
        perdues = sorted(set(branche.manquees) - set(resultat.reference.manquees))
        lignes.append(
            f"  {branche.drapeau:<15} {branche.paires_candidates - resultat.reference.paires_candidates:+d} paires "
            f"· {-perte:+d} vrai(s) positif(s)"
            + (f" · perdues : {', '.join(perdues)}" if perdues else " · aucune incohérence perdue")
        )

    lignes += ["", "Détail par canal :"]
    canaux = sorted({c for b in toutes for c in b.appariements_par_canal})
    entete = "  " + f"{'canal':<12}" + "".join(f"{b.drapeau or 'référence':>16}" for b in toutes)
    lignes.append(entete)
    for canal in canaux:
        ligne = f"  {canal:<12}"
        for branche in toutes:
            ligne += f"{branche.appariements_par_canal.get(canal, 0):>16}"
        lignes.append(ligne)

    lignes += [
        "",
        "⚠️ La branche « sans alias » SURESTIME le canal CLE : sa clé est canonicalisée au",
        "   CHARGEMENT du graphe, que le ciblage traverse ALIAS_DE ou non. Rejouer le ciblage",
        f"   ne défait pas ce calcul. Paires du canal CLE réellement dues au pont : "
        f"{resultat.paires_cle_dues_au_pont}.",
        "",
        "⚠️ Toutes les branches tournent à ÉTAGE A CONSTANT, sans le juge LLM. Changer le",
        "   ciblage change les paires soumises, donc toutes les clés de cache : mesurer avec",
        "   l'étage C mêlerait l'effet du canal à celui du modèle, pour ~50 appels par branche.",
    ]
    return "\n".join(lignes)


def formater_ablation(resultat: ResultatAblation, couleur: bool = True) -> str:
    """Rend l'ablation en tableau lisible — c'est le chiffre que le J4 doit produire."""
    gras, fin = ("\033[1m", "\033[0m") if couleur else ("", "")
    lignes = [
        f"{gras}Ablation — apport du pont inter-documents{fin}",
        "",
        f"{'branche':<28} {'candidates':>11} {'facteur':>8} {'rappel':>8}  manquées",
        "-" * 78,
    ]
    for branche in (resultat.avec, resultat.sans):
        lignes.append(
            f"{branche.nom:<28} {branche.paires_candidates:>11} "
            f"{branche.facteur_reduction:>8.4f} {branche.rappel_ciblage:>8}  "
            + (", ".join(branche.incoherences_manquees) or "—")
        )
    lignes += [
        "",
        f"Perte de rappel en retirant le pont : {resultat.perte_de_rappel} incohérence(s) "
        "du périmètre 7 jours.",
        "",
        "Détail par canal :",
    ]
    canaux = sorted(set(resultat.avec.appariements_par_canal) | set(resultat.sans.appariements_par_canal))
    for canal in canaux:
        avec = resultat.avec.appariements_par_canal.get(canal, 0)
        sans = resultat.sans.appariements_par_canal.get(canal, 0)
        lignes.append(f"  {canal:<12} {avec:>4} -> {sans:>4}")
    lignes += [
        "",
        f"⚠️ Le canal CLE est mesuré de façon optimiste dans la branche « sans pont » : sa clé",
        f"   est canonicalisée au CHARGEMENT, que le ciblage traverse ALIAS_DE ou non.",
        f"   Paires du canal CLE qui disparaîtraient sans cette canonicalisation : "
        f"{resultat.paires_cle_dues_au_pont}.",
    ]
    return "\n".join(lignes)
