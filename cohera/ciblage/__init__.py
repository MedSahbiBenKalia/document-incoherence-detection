"""L3 — le ciblage : filtres d'éligibilité, canaux, fusion.

Invariant : rien de cher avant le ciblage. Aucun appel NLI ou LLM sur une paire
qui n'est pas sortie du graphe comme PAIRE_CANDIDATE.

**L'ordre compte, et c'est celui de architecture.md §6.** Éligibilité, puis les canaux, puis
la fusion par rang, puis la comparabilité, puis les budgets, puis la matérialisation. Filtrer
avant de fusionner donnerait des rangs calculés sur des paires déjà mortes ; budgéter avant
de filtrer dépenserait le plafond par clause sur des paires qu'on s'apprête à jeter.

**La métrique qui compte n'est pas le facteur de réduction, c'est le rappel du ciblage.** Une
paire écartée ici ne sera jamais rattrapée au J5 : le rappel du ciblage plafonne le rappel du
système entier.
"""

from __future__ import annotations

from datetime import datetime, timezone

from neo4j import Session
from pydantic import BaseModel, Field

from cohera.ciblage import config_ciblage, eligibilite
from cohera.ciblage.canaux import cle, conceptuel, dimension, vectoriel
from cohera.ciblage.comparabilite import comparable
from cohera.ciblage.eligibilite import PaireEcartee
from cohera.ciblage.fusion_rrf import (
    PaireFusionnee,
    Troncature,
    appliquer_budget,
    budget_global,
    fusionner,
)
from cohera.ciblage.modeles import Appariement, Canal, ContexteClause
from cohera.extraction.frames import ClauseFrame, Modalite


class Ciblage(BaseModel):
    """Le résultat complet d'un ciblage — auditable de bout en bout.

    On garde les appariements par canal *et* les paires écartées : c'est ce qui permet de
    répondre à « pourquoi cette paire a-t-elle été examinée ? » comme à « pourquoi
    celle-là ne l'a-t-elle pas été ? ».
    """

    paires_theoriques: int = 0
    #: Les appariements bruts, canal par canal, avant toute fusion.
    par_canal: dict[str, list[Appariement]] = Field(default_factory=dict)
    fusionnees: list[PaireFusionnee] = Field(default_factory=list)
    candidates: list[PaireFusionnee] = Field(default_factory=list)
    ecartees: list[PaireEcartee] = Field(default_factory=list)
    troncatures: list[Troncature] = Field(default_factory=list)
    contextes: dict[str, ContexteClause] = Field(default_factory=dict)
    documents_eligibles: dict[str, bool] = Field(default_factory=dict)

    @property
    def facteur_reduction(self) -> float:
        if not self.paires_theoriques:
            return 0.0
        return 1.0 - len(self.candidates) / self.paires_theoriques

    def canaux_de(self, clause_a: str, clause_b: str) -> list[Canal]:
        """Les canaux ayant proposé une paire donnée, dans l'ordre alphabétique.

        Rend une liste vide si aucun canal ne l'a vue — c'est la question que posent les
        tests « I12 par le canal 5 et lui seul ».
        """
        cible = frozenset((clause_a, clause_b))
        for paire in self.fusionnees:
            if frozenset((paire.clause_a, paire.clause_b)) == cible:
                return paire.canaux
        return []

    def est_candidate(self, clause_a: str, clause_b: str) -> bool:
        cible = frozenset((clause_a, clause_b))
        return any(
            frozenset((p.clause_a, p.clause_b)) == cible for p in self.candidates
        )


# ------------------------------------------------------------------------ contextes


def requete_contextes(avec_pont: bool = True) -> str:
    """Le Cypher qui collecte de quoi juger la comparabilité de chaque clause.

    Fonction pure. Une seule requête pour toutes les clauses : interroger le graphe une fois
    par paire coûterait des milliers d'allers-retours pour une information qui ne dépend que
    de la clause.

    Le représentant canonique d'un concept est le plus petit `concept_id` de sa composante
    connexe par `ALIAS_DE` — le graphe ne portant pas de `canonique_id`, on le recalcule à la
    lecture. ``avec_pont=False`` réduit chaque composante à son concept, ce qui est
    exactement l'ablation demandée.
    """
    saut = (
        "OPTIONAL MATCH (k)-[:ALIAS_DE*1..3]-(m:Concept)\n"
        "WITH c, grandeurs, normes, k, collect(m.concept_id) + [k.concept_id] AS classe\n"
        if avec_pont
        else "WITH c, grandeurs, normes, k, [k.concept_id] AS classe\n"
    )
    return (
        "MATCH (c:Clause)\n"
        "OPTIONAL MATCH (c)-[:PORTE]->(q:Quantite)\n"
        "WITH c, collect(DISTINCT [q.dimension, q.role]) AS grandeurs\n"
        "OPTIONAL MATCH (c)-[:CITE_NORME]->(n:NormeExterne)\n"
        "WITH c, grandeurs, collect(DISTINCT n.code) AS normes\n"
        "OPTIONAL MATCH (c)-[:MENTIONNE]->(k:Concept) WHERE k.idf > $idf_min\n"
        + saut
        + "WITH c, grandeurs, normes, k,\n"
        "     reduce(mini = head(classe), x IN classe |\n"
        "            CASE WHEN x < mini THEN x ELSE mini END) AS canonique\n"
        "WITH c, grandeurs, normes, collect(DISTINCT canonique) AS concepts\n"
        "RETURN c.clause_id AS clause_id, c.doc_id AS doc_id, c.ref AS ref,\n"
        "       c.modalite AS modalite,\n"
        "       c.date_debut_validite AS debut, c.date_fin_validite AS fin,\n"
        "       grandeurs, normes, concepts"
    )


def collecter_contextes(
    session: Session,
    frames: dict[str, ClauseFrame] | None = None,
    *,
    avec_pont: bool = True,
) -> dict[str, ContexteClause]:
    """Un :class:`ContexteClause` par clause du graphe.

    ``frames`` alimente les renvois explicites, qui ne vivent pas dans le graphe :
    `chargeur.py` n'écrit pas d'arête `RENVOIE_A`. Sans frames, la branche RENVOI du filtre
    de comparabilité ne peut simplement jamais s'appliquer — aucune des 12 incohérences du
    périmètre n'en dépend, mais il faut le savoir plutôt que le découvrir.
    """
    renvois = _renvois_par_clause(frames or {})

    contextes: dict[str, ContexteClause] = {}
    for ligne in session.run(requete_contextes(avec_pont), idf_min=config_ciblage.idf_min()):
        clause_id = ligne["clause_id"]
        grandeurs = [
            (dimension_, role)
            for dimension_, role in ligne["grandeurs"]
            if dimension_ is not None and role is not None
        ]
        contextes[clause_id] = ContexteClause(
            clause_id=clause_id,
            doc_id=ligne["doc_id"] or "",
            ref=ligne["ref"] or "",
            modalite=Modalite(ligne["modalite"]) if ligne["modalite"] else None,
            date_debut_validite=ligne["debut"],
            date_fin_validite=ligne["fin"],
            dimensions_roles=grandeurs,
            normes_citees=[code for code in ligne["normes"] if code],
            concepts_canoniques=[cid for cid in ligne["concepts"] if cid],
            renvois=renvois.get(clause_id, []),
        )
    return contextes


def _renvois_par_clause(frames: dict[str, ClauseFrame]) -> dict[str, list[tuple[str, str]]]:
    """``clause_id -> [(doc_cible, ref_cible)]``, depuis les `Reference` des frames.

    Le numéro de paragraphe est nettoyé de son « § » pour coïncider avec le champ ``ref``
    des clauses, qui ne le porte pas.
    """
    par_clause: dict[str, list[tuple[str, str]]] = {}
    for clause_id, frame in frames.items():
        cibles = [
            (reference.document_cible, reference.cible.replace("§", "").strip())
            for reference in frame.references
            if reference.document_cible and reference.cible
        ]
        if cibles:
            par_clause[clause_id] = cibles
    return par_clause


# -------------------------------------------------------------------------- ciblage


def cibler(
    session: Session,
    frames: dict[str, ClauseFrame] | None = None,
    *,
    avec_pont: bool = True,
) -> Ciblage:
    """Le ciblage complet : éligibilité, canaux, fusion, comparabilité, budgets.

    Ne matérialise rien — c'est :func:`materialiser` qui écrit dans le graphe, pour que le
    ciblage soit mesurable et rejouable sans effet de bord (les ablations en dépendent).
    """
    documents = eligibilite.appliquer_f1(session)
    eligibles = {doc_id for doc_id, ok in documents.items() if ok}

    par_canal: dict[Canal, list[Appariement]] = {}
    if config_ciblage.canal_actif(Canal.CLE):
        par_canal[Canal.CLE] = cle.apparier(session)
    if config_ciblage.canal_actif(Canal.CONCEPTUEL):
        par_canal[Canal.CONCEPTUEL] = conceptuel.apparier(session, avec_pont=avec_pont)
    if config_ciblage.canal_actif(Canal.VECTORIEL):
        par_canal[Canal.VECTORIEL] = vectoriel.apparier(session)
    if config_ciblage.canal_actif(Canal.DIMENSION):
        par_canal[Canal.DIMENSION] = dimension.apparier(session)

    contextes = collecter_contextes(session, frames, avec_pont=avec_pont)
    fusionnees = fusionner([a for liste in par_canal.values() for a in liste])

    retenues: list[PaireFusionnee] = []
    ecartees: list[PaireEcartee] = []

    for paire in fusionnees:
        a = contextes.get(paire.clause_a)
        b = contextes.get(paire.clause_b)
        if a is None or b is None:
            continue

        if a.doc_id not in eligibles or b.doc_id not in eligibles:
            ecartees.append(_ecartee(paire, "F1", "document abrogé ou remplacé"))
            continue

        if eligibilite.periodes_disjointes(a, b):
            ecartees.append(_ecartee(paire, "F2", "périodes de validité disjointes"))
            continue

        verdict = comparable(a, b)
        if not verdict:
            ecartees.append(_ecartee(paire, "COMPARABILITE", verdict.explication))
            continue

        retenues.append(paire)

    budget = appliquer_budget(
        retenues, budget_global=budget_global(_clauses_par_document(contextes))
    )

    return Ciblage(
        paires_theoriques=_paires_theoriques(contextes),
        par_canal={canal.value: liste for canal, liste in par_canal.items()},
        fusionnees=fusionnees,
        candidates=budget.retenues,
        ecartees=ecartees,
        troncatures=budget.troncatures,
        contextes=contextes,
        documents_eligibles=documents,
    )


def _ecartee(paire: PaireFusionnee, filtre: str, motif: str) -> PaireEcartee:
    return PaireEcartee(
        clause_a=paire.clause_a, clause_b=paire.clause_b, filtre=filtre, motif=motif
    )


def _clauses_par_document(contextes: dict[str, ContexteClause]) -> dict[str, int]:
    comptes: dict[str, int] = {}
    for contexte in contextes.values():
        comptes[contexte.doc_id] = comptes.get(contexte.doc_id, 0) + 1
    return comptes


def _paires_theoriques(contextes: dict[str, ContexteClause]) -> int:
    """``n₁ × n₂`` — l'espace que le ciblage doit réduire.

    Le produit des tailles des documents pris deux à deux, et non ``C(n, 2)`` sur tout le
    corpus : COHERA ne compare pas une clause à celles de son propre document.
    """
    comptes = list(_clauses_par_document(contextes).values())
    return sum(
        gauche * droite
        for indice, gauche in enumerate(comptes)
        for droite in comptes[indice + 1 :]
    )


# ------------------------------------------------------------------ matérialisation


def materialiser(session: Session, ciblage: Ciblage, run_id: str) -> int:
    """Écrit les `PAIRE_CANDIDATE` dans le graphe. **MERGE, jamais CREATE.**

    Rend le système auditable et incrémental : on peut expliquer *pourquoi* une paire a été
    examinée, et rejouer la vérification sans refaire le ciblage (architecture.md §6.6).
    """
    lignes = [
        {
            "a": paire.clause_a,
            "b": paire.clause_b,
            "score": paire.score_rrf,
            "canaux": [canal.value for canal in paire.canaux],
            "rang": rang,
        }
        for rang, paire in enumerate(ciblage.candidates, start=1)
    ]
    session.run(
        "UNWIND $paires AS p\n"
        "MATCH (a:Clause {clause_id: p.a}), (b:Clause {clause_id: p.b})\n"
        "MERGE (a)-[r:PAIRE_CANDIDATE]->(b)\n"
        "SET r.score = p.score, r.canaux = p.canaux, r.rang = p.rang,\n"
        "    r.run_id = $run_id, r.horodatage = datetime()",
        paires=lignes,
        run_id=run_id,
    )
    return len(lignes)


def identifiant_execution() -> str:
    """Un `run_id` horodaté, en UTC — jamais un identifiant aléatoire."""
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
