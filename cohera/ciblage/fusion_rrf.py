"""Fusion des canaux par Reciprocal Rank Fusion, et budget de paires.

Cible : 80 à 140 paires candidates sur les 1517 théoriques, soit un facteur de
réduction >= 0,91 avec un rappel de ciblage >= 0,95.

**Pourquoi par rang et non par score.** Les scores de canaux différents ne sont pas
comparables : le canal vectoriel rend un cosinus dans [0,64 ; 0,96], le canal conceptuel une
somme de poids IDF sans borne supérieure, le canal CLE un 1.0 constant. Les additionner
reviendrait à déclarer qu'un cosinus de 0,83 « vaut » un poids IDF de 0,83. On ne garde donc
de chaque canal que **l'ordre** dans lequel il a classé ses paires (architecture.md §6.6) :

    RRF(a,b) = Σ_canaux  poids_c / (k + rang_c(a,b))

**Le budget est une décision de qualité, pas d'implémentation.** Toute paire écartée l'est
avec son motif (`.claude/rules/detection.md`) : une troncature silencieuse rendrait un
rappel de ciblage dégradé indiscernable d'un ciblage qui n'a rien trouvé.

Module **pur** : aucune connexion, tout se teste hors ligne.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from cohera.ciblage import config_ciblage
from cohera.ciblage.modeles import Appariement, Canal, ClePaire


class PaireFusionnee(BaseModel):
    """Une paire vue par un ou plusieurs canaux, avec son score de fusion."""

    clause_a: str
    clause_b: str
    score_rrf: float
    #: Les canaux qui ont proposé la paire, triés — c'est ce qui rend le ciblage auditable.
    canaux: list[Canal] = Field(default_factory=list)
    #: Rang obtenu dans chaque canal, pour pouvoir refaire le calcul à la main.
    rangs: dict[str, int] = Field(default_factory=dict)

    @property
    def cle(self) -> ClePaire:
        return (self.clause_a, self.clause_b)


class Troncature(BaseModel):
    """Une paire écartée par un budget, avec le motif qui l'explique."""

    clause_a: str
    clause_b: str
    score_rrf: float
    motif: str


class ResultatBudget(BaseModel):
    retenues: list[PaireFusionnee] = Field(default_factory=list)
    troncatures: list[Troncature] = Field(default_factory=list)


# ------------------------------------------------------------------------------ fusion


def fusionner(
    appariements: list[Appariement],
    poids: dict[Canal, float] | None = None,
    k: int | None = None,
) -> list[PaireFusionnee]:
    """Fusionne les propositions de tous les canaux, triées du meilleur score au moins bon.

    Un même canal peut proposer la même paire deux fois — le canal vectoriel interroge
    l'index clause par clause et voit donc chaque paire des deux côtés. On ne retient alors
    que **le meilleur rang** : compter deux fois la même proposition gonflerait le score
    d'une paire sans qu'aucun canal supplémentaire ne l'ait vue.
    """
    poids = poids if poids is not None else config_ciblage.poids_des_canaux()
    k = k if k is not None else config_ciblage.constante_rrf()

    meilleurs: dict[ClePaire, dict[Canal, int]] = defaultdict(dict)
    for appariement in appariements:
        rangs = meilleurs[appariement.cle]
        precedent = rangs.get(appariement.canal)
        if precedent is None or appariement.rang < precedent:
            rangs[appariement.canal] = appariement.rang

    paires = [
        PaireFusionnee(
            clause_a=cle[0],
            clause_b=cle[1],
            score_rrf=sum(poids.get(canal, 0.0) / (k + rang) for canal, rang in rangs.items()),
            canaux=sorted(rangs, key=lambda c: c.value),
            rangs={canal.value: rang for canal, rang in sorted(rangs.items(), key=lambda kv: kv[0].value)},
        )
        for cle, rangs in meilleurs.items()
    ]
    # Tri secondaire sur la clé : à score égal, l'ordre doit être déterministe, sinon deux
    # exécutions du même ciblage tronqueraient des paires différentes.
    paires.sort(key=lambda p: (-p.score_rrf, p.clause_a, p.clause_b))
    return paires


# ------------------------------------------------------------------------------ budget


def appliquer_budget(
    paires: list[PaireFusionnee],
    top_k: int | None = None,
    exemptes: frozenset[Canal] | None = None,
    budget_global: int | None = None,
) -> ResultatBudget:
    """Applique le plafond par clause puis le budget global (architecture.md §6.6).

    ``paires`` est supposée déjà triée par score décroissant — c'est ce que rend
    :func:`fusionner`.

    **Le plafond se lit en intersection : une paire n'est retenue que si elle figure dans
    les ``top_k`` meilleures de *chacune* de ses deux clauses.** C'est la seule lecture qui
    fait de ``top_k`` un budget : elle garantit qu'aucune clause ne ressort avec plus de
    ``top_k`` partenaires. En union — retenir dès qu'une des deux clauses a de la place —
    une clause peut dépasser le plafond autant de fois qu'elle rencontre des partenaires
    encore inutilisés, et le budget devient décoratif.

    Le prix est assumé et mesurable : une paire classée au-delà du rang ``top_k`` pour l'une
    de ses clauses est écartée même si elle est l'unique partenaire de l'autre. C'est
    précisément ce que le test de rappel du ciblage sur les fixtures doit surveiller — si
    une des 12 incohérences du périmètre tombe ici, c'est le plafond qu'il faut discuter,
    pas le résultat qu'il faut arrondir.
    """
    top_k = top_k if top_k is not None else config_ciblage.top_k()
    exemptes = exemptes if exemptes is not None else config_ciblage.canaux_exemptes()

    # Les `paires` étant déjà triées, la liste de chaque clause l'est aussi : ses `top_k`
    # premières sont ses `top_k` meilleures.
    par_clause: dict[str, list[ClePaire]] = defaultdict(list)
    for paire in paires:
        par_clause[paire.clause_a].append(paire.cle)
        par_clause[paire.clause_b].append(paire.cle)
    admises = {clause: set(cles[:top_k]) for clause, cles in par_clause.items()}

    retenues: list[PaireFusionnee] = []
    troncatures: list[Troncature] = []

    for paire in paires:
        exempte = any(canal in exemptes for canal in paire.canaux)
        place_a = paire.cle in admises[paire.clause_a]
        place_b = paire.cle in admises[paire.clause_b]

        if exempte or (place_a and place_b):
            retenues.append(paire)
        else:
            manquante = paire.clause_a if not place_a else paire.clause_b
            troncatures.append(
                Troncature(
                    clause_a=paire.clause_a,
                    clause_b=paire.clause_b,
                    score_rrf=paire.score_rrf,
                    motif=f"hors des {top_k} meilleures de {manquante}",
                )
            )

    if budget_global is not None and len(retenues) > budget_global:
        for paire in retenues[budget_global:]:
            troncatures.append(
                Troncature(
                    clause_a=paire.clause_a,
                    clause_b=paire.clause_b,
                    score_rrf=paire.score_rrf,
                    motif=f"budget global atteint (B={budget_global})",
                )
            )
        retenues = retenues[:budget_global]

    return ResultatBudget(retenues=retenues, troncatures=troncatures)


def budget_global(nb_clauses_par_document: dict[str, int]) -> int:
    """``B = facteur × max(n₁, n₂)`` (architecture.md §6.6)."""
    return config_ciblage.facteur_budget_global() * max(
        nb_clauses_par_document.values(), default=0
    )
