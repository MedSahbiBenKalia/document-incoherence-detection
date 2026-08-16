"""ciblage/fusion_rrf.py — fusion par rang et budgets de paires.

Module pur, donc testé sans serveur : c'est la convention du dépôt (`graphe/compat.py`,
`graphe/schema.py`). Le calcul RRF est vérifié **à la main**, pas contre lui-même — un test
qui rappellerait la fonction pour comparer ne prouverait rien.

Le second bloc porte sur les budgets, où le critère du J4 se joue vraiment : c'est le
plafond par clause qui décide si I12 survit jusqu'aux `PAIRE_CANDIDATE`.
"""

from __future__ import annotations

import pytest

from cohera.ciblage.fusion_rrf import (
    appliquer_budget,
    budget_global,
    fusionner,
)
from cohera.ciblage.modeles import Appariement, Canal


def appariement(a: str, b: str, canal: Canal, rang: int, score: float = 1.0) -> Appariement:
    return Appariement(clause_a=a, clause_b=b, canal=canal, score=score, rang=rang)


POIDS = {Canal.CLE: 3.0, Canal.CONCEPTUEL: 1.5, Canal.VECTORIEL: 1.0, Canal.DIMENSION: 1.2}


# ---------------------------------------------------------------------------- fusion


def test_le_score_rrf_est_la_somme_des_poids_sur_les_rangs() -> None:
    """RRF(a,b) = Σ poids_c / (k + rang_c), calculé à la main.

    Une paire vue au rang 1 par le canal CLE (poids 3,0) et au rang 3 par le canal
    vectoriel (poids 1,0), avec k = 60 : 3,0/61 + 1,0/63.
    """
    paires = fusionner(
        [
            appariement("A", "B", Canal.CLE, rang=1),
            appariement("A", "B", Canal.VECTORIEL, rang=3),
        ],
        poids=POIDS,
        k=60,
    )
    assert len(paires) == 1
    assert paires[0].score_rrf == pytest.approx(3.0 / 61 + 1.0 / 63)


def test_un_canal_lourd_classe_devant_un_canal_leger_a_rang_egal() -> None:
    """C'est tout l'objet des poids : au même rang, CLE doit primer sur VECTORIEL."""
    paires = fusionner(
        [
            appariement("A", "B", Canal.VECTORIEL, rang=1),
            appariement("C", "D", Canal.CLE, rang=1),
        ],
        poids=POIDS,
        k=60,
    )
    assert (paires[0].clause_a, paires[0].clause_b) == ("C", "D")


def test_une_paire_vue_par_deux_canaux_passe_devant_une_paire_vue_par_un_seul() -> None:
    """Le cumul est le mécanisme central de RRF : l'accord entre canaux vaut mieux qu'un
    bon rang dans un seul."""
    paires = fusionner(
        [
            appariement("A", "B", Canal.CONCEPTUEL, rang=2),
            appariement("A", "B", Canal.DIMENSION, rang=2),
            appariement("C", "D", Canal.CONCEPTUEL, rang=1),
        ],
        poids=POIDS,
        k=60,
    )
    assert (paires[0].clause_a, paires[0].clause_b) == ("A", "B")


def test_la_paire_est_non_ordonnee() -> None:
    """Le canal vectoriel interroge l'index clause par clause et voit chaque paire des deux
    côtés. Sans clé normalisée, la fusion compterait deux paires là où il n'y en a qu'une,
    et le budget serait faussé."""
    paires = fusionner(
        [
            appariement("A", "B", Canal.VECTORIEL, rang=1),
            appariement("B", "A", Canal.VECTORIEL, rang=4),
        ],
        poids=POIDS,
        k=60,
    )
    assert len(paires) == 1


def test_une_paire_vue_deux_fois_par_le_meme_canal_garde_le_meilleur_rang() -> None:
    """Et ne compte qu'une fois : additionner les deux propositions gonflerait le score
    d'une paire sans qu'aucun canal supplémentaire ne l'ait vue."""
    paires = fusionner(
        [
            appariement("A", "B", Canal.VECTORIEL, rang=1),
            appariement("B", "A", Canal.VECTORIEL, rang=4),
        ],
        poids=POIDS,
        k=60,
    )
    assert paires[0].score_rrf == pytest.approx(1.0 / 61)
    assert paires[0].rangs == {"VECTORIEL": 1}


def test_les_canaux_sont_traces_sur_la_paire() -> None:
    """« On peut expliquer *pourquoi* une paire a été examinée » (architecture.md §6.6)."""
    paires = fusionner(
        [
            appariement("A", "B", Canal.DIMENSION, rang=3),
            appariement("A", "B", Canal.CLE, rang=1),
        ],
        poids=POIDS,
        k=60,
    )
    assert paires[0].canaux == [Canal.CLE, Canal.DIMENSION]
    assert paires[0].rangs == {"CLE": 1, "DIMENSION": 3}


def test_l_ordre_est_deterministe_a_score_egal() -> None:
    """Deux exécutions du même ciblage doivent tronquer les mêmes paires, sinon le rappel
    du ciblage varierait d'un lancement à l'autre."""
    entrees = [
        appariement("A", "Z", Canal.VECTORIEL, rang=1),
        appariement("A", "B", Canal.VECTORIEL, rang=1),
        appariement("A", "M", Canal.VECTORIEL, rang=1),
    ]
    premier = [p.cle for p in fusionner(entrees, poids=POIDS, k=60)]
    second = [p.cle for p in fusionner(list(reversed(entrees)), poids=POIDS, k=60)]
    assert premier == second


def test_fusionner_sans_appariement_rend_une_liste_vide() -> None:
    """Cas dégénéré : un corpus sans paire ne doit pas lever."""
    assert fusionner([], poids=POIDS, k=60) == []


# ---------------------------------------------------------------------------- budget


def _serie(n: int, canal: Canal = Canal.VECTORIEL) -> list[Appariement]:
    """``n`` paires partageant la clause « A », de la mieux classée à la moins bien."""
    return [appariement("A", f"B{indice:02d}", canal, rang=indice + 1) for indice in range(n)]


def test_le_plafond_par_clause_coupe_les_paires_en_trop() -> None:
    """`top-k = 8` (architecture.md §6.6) : douze candidates pour une clause, huit retenues."""
    paires = fusionner(_serie(12), poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset())
    assert len(resultat.retenues) == 8


def test_le_plafond_garde_les_mieux_classees() -> None:
    """Tronquer par le bas, pas au hasard."""
    paires = fusionner(_serie(12), poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset())
    gardees = {p.clause_b for p in resultat.retenues}
    assert "B00" in gardees
    assert "B11" not in gardees


def test_un_canal_exempte_echappe_au_plafond() -> None:
    """Les canaux 1 et 2 sont « trop précis pour être coupés » (architecture.md §6.6).

    Neuf paires sur la même clause dont une seule par le canal CLE, si mal classée que même
    son poids de 3,0 ne la ramène pas dans les huit meilleures (3,0/260 < 1,0/68) : elle
    doit survivre malgré tout.
    """
    entrees = _serie(8) + [appariement("A", "PRECISE", Canal.CLE, rang=200)]
    paires = fusionner(entrees, poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset({Canal.CLE}))
    assert "PRECISE" in {p.clause_b for p in resultat.retenues}


def test_sans_exemption_la_meme_paire_serait_coupee() -> None:
    """Le cas négatif du test précédent : c'est bien l'exemption qui la sauve, pas son
    score."""
    entrees = _serie(8) + [appariement("A", "PRECISE", Canal.CLE, rang=200)]
    paires = fusionner(entrees, poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset())
    assert "PRECISE" not in {p.clause_b for p in resultat.retenues}


def test_le_plafond_se_lit_en_intersection_des_deux_clauses() -> None:
    """Une paire n'est retenue que si elle figure dans les top-k de CHACUNE de ses clauses.

    « A » est déjà saturée par huit paires mieux classées, et « SEULE » n'a pourtant que ce
    partenaire-là : la paire tombe quand même. C'est le prix assumé de la seule lecture qui
    fasse de `top_k` un budget — voir le test suivant.
    """
    entrees = _serie(8) + [appariement("A", "SEULE", Canal.VECTORIEL, rang=50)]
    paires = fusionner(entrees, poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset())
    assert "SEULE" not in {p.clause_b for p in resultat.retenues}


def test_aucune_clause_ne_depasse_le_plafond() -> None:
    """La propriété que l'intersection garantit et que l'union ne garantit pas.

    En union, « A » ressortirait ici avec ses douze partenaires — chacun des « B » ayant de
    la place — et `top_k` ne budgéterait plus rien.
    """
    paires = fusionner(_serie(12), poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset())
    degres: dict[str, int] = {}
    for paire in resultat.retenues:
        for clause in (paire.clause_a, paire.clause_b):
            degres[clause] = degres.get(clause, 0) + 1
    assert max(degres.values()) <= 8


def test_toute_paire_ecartee_est_journalisee_avec_son_motif() -> None:
    """`.claude/rules/detection.md`. Une troncature silencieuse rendrait un ciblage dégradé
    indiscernable d'un ciblage qui n'a rien trouvé."""
    paires = fusionner(_serie(12), poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset())
    assert resultat.troncatures
    assert all(t.motif for t in resultat.troncatures)


def test_le_budget_global_tronque_et_journalise() -> None:
    """Le second plafond, global celui-là (architecture.md §6.6)."""
    paires = fusionner(
        [appariement(f"A{i:02d}", f"B{i:02d}", Canal.VECTORIEL, rang=i + 1) for i in range(20)],
        poids=POIDS,
        k=60,
    )
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset(), budget_global=5)
    assert len(resultat.retenues) == 5
    assert any("budget global" in t.motif for t in resultat.troncatures)


def test_aucune_troncature_quand_tout_tient_dans_le_budget() -> None:
    """Cas négatif des budgets : en dessous des plafonds, rien n'est écarté."""
    paires = fusionner(_serie(3), poids=POIDS, k=60)
    resultat = appliquer_budget(paires, top_k=8, exemptes=frozenset(), budget_global=100)
    assert len(resultat.retenues) == 3
    assert resultat.troncatures == []


def test_le_budget_global_vaut_le_facteur_fois_le_plus_grand_document() -> None:
    """``B = 4 × max(n₁, n₂)`` : 4 × 41 = 164 sur les fixtures."""
    assert budget_global({"D1": 41, "D2": 37}) == 164


def test_le_budget_global_d_un_corpus_vide_ne_leve_pas() -> None:
    assert budget_global({}) == 0
