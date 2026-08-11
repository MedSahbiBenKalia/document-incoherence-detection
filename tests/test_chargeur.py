"""graphe/chargeur.py — chargement idempotent dans Neo4j.

Critère du J3 (docs/plan-1-semaine.md §J3) : « Deux chargements successifs donnent le même
nombre de nœuds et d'arêtes ». C'est la traduction opérationnelle de l'invariant de
`CLAUDE.md` : « Neo4j : MERGE, jamais CREATE ».

**Pourquoi ces tests exigent un serveur.** La convention du dépôt est d'isoler la fonction
pure et de tester hors ligne (`compat.py` / `test_compat.py`), et elle est respectée partout
ailleurs — `cle_comparaison` et `condition_id` sont testés ici sans connexion. Mais
l'idempotence *est* un comportement de Neo4j : la simuler ne prouverait rien. D'où le
marqueur `neo4j` et le saut explicite quand le conteneur n'est pas là.

⚠️ Un test sauté n'est pas un test vert. Le bilan de fin de journée compte les skips.
"""

from __future__ import annotations

import pytest

from cohera.graphe.chargeur import (
    JOKER_ACTEUR,
    charger,
    cle_comparaison,
    compter,
    condition_id,
    vider,
)


def _neo4j_joignable() -> bool:
    try:
        from cohera.graphe.connexion import verifier_connectivite

        verifier_connectivite()
        return True
    except Exception:
        return False


besoin_neo4j = pytest.mark.skipif(
    not _neo4j_joignable(),
    reason="Neo4j injoignable — démarrer le conteneur : docker compose up -d",
)


# ------------------------------------------------------ sans serveur : identités pures


def test_l_identite_d_une_condition_ne_depend_pas_de_la_clause() -> None:
    """Les conditions se dédupliquent à travers tout le corpus (architecture.md §5.7).

    C'est ce qui permet de calculer le recouvrement une fois par paire de conditions au lieu
    d'une fois par paire de clauses.
    """
    assert condition_id("en zone A", "SPATIAL") == condition_id("En zone A", "SPATIAL")


def test_deux_conditions_distinctes_ont_des_identites_distinctes() -> None:
    assert condition_id("en zone A", "SPATIAL") != condition_id("en zone B", "SPATIAL")


def test_le_type_entre_dans_l_identite_d_une_condition() -> None:
    """Même surface, type différent : deux conditions, pas une."""
    assert condition_id("avant chaque prise de poste", "TEMPOREL") != condition_id(
        "avant chaque prise de poste", "SPATIAL"
    )


def test_l_identite_d_une_condition_est_stable_entre_deux_appels() -> None:
    assert condition_id("en cas d'incident grave", "CIRCONSTANCIEL") == condition_id(
        "en cas d'incident grave", "CIRCONSTANCIEL"
    )


# ------------------------------------------------------------------ clé de comparaison


def test_la_cle_de_comparaison_a_cinq_positions(d1, frames, vocabulaire, pont) -> None:
    cle = cle_comparaison(d1.clause("4.2").clause_id, frames, vocabulaire, pont)
    assert len(cle.split("|")) == 5


def test_la_cle_de_comparaison_utilise_les_canoniques(d1, d2, frames, vocabulaire, pont) -> None:
    """D1 §4.2 (« Responsable QSE ») et D2 §4.2 (« Référent sécurité ») doivent partager
    leur position d'acteur : c'est tout l'objet du pont.

    Sans les canoniques, ces deux clauses resteraient dans deux composantes disjointes et
    I01 serait invisible.
    """
    cle_a = cle_comparaison(d1.clause("4.2").clause_id, frames, vocabulaire, pont)
    cle_b = cle_comparaison(d2.clause("4.2").clause_id, frames, vocabulaire, pont)
    assert cle_a.split("|")[0] == cle_b.split("|")[0]


def test_une_clause_sans_acteur_recoit_le_joker(frames, vocabulaire, pont, d2) -> None:
    """Le `*` des tournures passives (architecture.md §5.8)."""
    cles = [
        cle_comparaison(clause.clause_id, frames, vocabulaire, pont)
        for clause in d2.clauses
    ]
    assert any(cle.startswith(f"{JOKER_ACTEUR}|") for cle in cles)


def test_la_cle_de_comparaison_est_stable(d1, frames, vocabulaire, pont) -> None:
    """Deux calculs donnent la même clé — sinon le second chargement réécrirait toutes les
    clauses et l'idempotence ne serait qu'apparente."""
    clause_id = d1.clause("5.1").clause_id
    assert cle_comparaison(clause_id, frames, vocabulaire, pont) == cle_comparaison(
        clause_id, frames, vocabulaire, pont
    )


def test_deux_clauses_sans_rapport_ont_des_cles_differentes(d1, frames, vocabulaire, pont) -> None:
    """Le cas négatif : la clé doit discriminer, sinon le canal 2 apparierait tout."""
    cle_delai = cle_comparaison(d1.clause("4.2").clause_id, frames, vocabulaire, pont)
    cle_hauteur = cle_comparaison(d1.clause("7.1").clause_id, frames, vocabulaire, pont)
    assert cle_delai != cle_hauteur


# ------------------------------------------------------- avec serveur : l'idempotence


@pytest.fixture
def session_neo4j():
    from cohera.graphe.connexion import session

    with session() as sess:
        yield sess


@pytest.fixture
def graphe_vierge(session_neo4j):
    """Base vidée avant ET après : un test d'idempotence qui partirait d'un graphe déjà
    peuplé ne prouverait rien."""
    vider(session_neo4j)
    yield session_neo4j
    vider(session_neo4j)


@besoin_neo4j
@pytest.mark.neo4j
def test_deux_chargements_donnent_le_meme_graphe(
    graphe_vierge, jeu, frames, vocabulaire, pont
) -> None:
    """LE critère du J3.

    Comparaison **par label et par type de relation**, pas en total : deux erreurs qui se
    compensent — un `Concept` perdu, une `Condition` dupliquée — laisseraient le total
    inchangé et le test passerait au vert à tort.

    `avec_embeddings=False` : les vecteurs sont déjà couverts par `test_embeddings.py`, et
    les écrire ici ferait de ce test une affaire de minutes sans rien prouver de plus sur
    l'idempotence.
    """
    premier = charger(jeu, frames, vocabulaire, pont, graphe_vierge, avec_embeddings=False)
    second = charger(jeu, frames, vocabulaire, pont, graphe_vierge, avec_embeddings=False)

    assert premier.noeuds == second.noeuds, (
        f"nœuds dupliqués : {premier.noeuds} puis {second.noeuds}"
    )
    assert premier.aretes == second.aretes, (
        f"arêtes dupliquées : {premier.aretes} puis {second.aretes}"
    )


@besoin_neo4j
@pytest.mark.neo4j
def test_le_chargement_produit_les_clauses_attendues(
    graphe_vierge, jeu, frames, vocabulaire, pont
) -> None:
    """41 + 37 clauses, le compte du J1, doit se retrouver dans le graphe."""
    bilan = charger(jeu, frames, vocabulaire, pont, graphe_vierge, avec_embeddings=False)
    assert bilan.noeuds.get("Clause") == 78
    assert bilan.noeuds.get("Document") == 2


@besoin_neo4j
@pytest.mark.neo4j
def test_les_conditions_sont_dedupliquees(graphe_vierge, jeu, frames, vocabulaire, pont) -> None:
    """Il doit y avoir moins de nœuds `Condition` que de relations `SOUS_CONDITION`.

    Si les deux comptes étaient égaux, chaque clause aurait sa propre copie et le rendement
    de la réification (architecture.md §5.7) serait perdu.
    """
    bilan = charger(jeu, frames, vocabulaire, pont, graphe_vierge, avec_embeddings=False)
    conditions = bilan.noeuds.get("Condition", 0)
    sous_condition = bilan.aretes.get("SOUS_CONDITION", 0)
    assert conditions > 0
    assert conditions < sous_condition, "aucune condition n'a été mutualisée"


@besoin_neo4j
@pytest.mark.neo4j
def test_le_sous_label_acteur_est_pose(graphe_vierge, jeu, frames, vocabulaire, pont) -> None:
    """Les rôles du gazetteer portent `:Concept:Acteur` (architecture.md §5.1)."""
    bilan = charger(jeu, frames, vocabulaire, pont, graphe_vierge, avec_embeddings=False)
    assert bilan.noeuds.get("Acteur", 0) > 0
    assert bilan.noeuds["Acteur"] < bilan.noeuds["Concept"]


@besoin_neo4j
@pytest.mark.neo4j
def test_le_graphe_vide_se_compte_sans_lever(graphe_vierge) -> None:
    """Cas négatif du comptage : une base vierge donne des dictionnaires vides, pas une
    exception."""
    bilan = compter(graphe_vierge)
    assert bilan.total_noeuds == 0
    assert bilan.total_aretes == 0
