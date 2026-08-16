"""ciblage/canaux/ — le Cypher des quatre canaux, et le classement qui les suit.

Convention du dépôt (`graphe/compat.py`, `graphe/schema.py`) : la logique est dans une
fonction **pure** qui rend du Cypher, et c'est elle qu'on teste. L'exécution contre un
serveur est vérifiée séparément, dans `test_ciblage.py`.

Deux choses se jouent ici et nulle part ailleurs :

* **l'échelle de similarité** — Neo4j rend ``(1 + cos) / 2``, le projet raisonne en cosinus
  brut. Une erreur de conversion fausserait silencieusement tous les seuils ;
* **l'absence de valeur métier dans le code** — chaque seuil doit rester un paramètre ``$``,
  jamais une constante interpolée (`CLAUDE.md`).
"""

from __future__ import annotations

import pytest

from cohera.ciblage import config_ciblage
from cohera.ciblage.canaux import classer, cle, conceptuel, dimension, vectoriel
from cohera.ciblage.modeles import Canal

REQUETES = {
    "CLE": cle.requete(),
    "CONCEPTUEL": conceptuel.requete(),
    "VECTORIEL": vectoriel.requete_clauses(),
    "DIMENSION": dimension.requete(),
}


# ------------------------------------------------------------------ échelle de cosinus


def test_le_score_de_neo4j_est_reconverti_en_cosinus_brut() -> None:
    """Neo4j normalise : ``score = (1 + cos) / 2``. Mesuré sur le corpus, I12 ressort à
    0,799 côté Neo4j pour un cosinus brut de 0,598."""
    assert vectoriel.cosinus_brut(0.7992) == pytest.approx(0.5984, abs=1e-4)


def test_la_conversion_couvre_les_bornes() -> None:
    """Un score de 1,0 est un cosinus de 1,0 ; un score de 0,5 est un cosinus nul."""
    assert vectoriel.cosinus_brut(1.0) == pytest.approx(1.0)
    assert vectoriel.cosinus_brut(0.5) == pytest.approx(0.0)
    assert vectoriel.cosinus_brut(0.0) == pytest.approx(-1.0)


def test_le_seuil_vectoriel_est_lu_sur_l_echelle_brute() -> None:
    """Cas négatif de l'échelle : un seuil pensé en cosinus brut doit rester dans [-1, 1] et
    bien en deçà des scores normalisés, sinon c'est qu'on compare deux échelles."""
    seuil = config_ciblage.seuil_vectoriel()
    assert -1.0 <= seuil <= 1.0
    assert seuil < vectoriel.cosinus_brut(1.0)


# ------------------------------------------------------- pas de valeur métier en dur


@pytest.mark.parametrize("nom", sorted(REQUETES))
def test_aucune_requete_n_interpole_de_seuil(nom: str) -> None:
    """`CLAUDE.md` : « Aucune valeur métier en dur dans le code. »

    Les seuils du ciblage doivent apparaître comme paramètres ``$``, jamais comme
    constantes : sinon changer `config/ciblage.yaml` ne changerait rien.
    """
    requete = REQUETES[nom]
    for valeur in (str(config_ciblage.idf_min()), str(config_ciblage.seuil_vectoriel())):
        assert valeur not in requete, f"{nom} interpole {valeur}"


def test_le_canal_conceptuel_parametre_ses_deux_seuils() -> None:
    requete = conceptuel.requete()
    assert "$idf_min" in requete
    assert "$partages_min" in requete


def test_le_canal_dimension_parametre_son_top_n() -> None:
    assert "$top_n" in dimension.requete()


# ------------------------------------------------------------------ formes attendues


def test_le_canal_cle_ecarte_les_cles_vides() -> None:
    """Garde-fou du cas dégénéré : deux clauses dont aucune position n'a pu être remplie
    auraient des clés « égales » et s'apparieraient sans rien partager."""
    assert "a.cle_comparaison <> ''" in cle.requete()


def test_le_canal_dimension_n_applique_aucun_seuil_de_similarite() -> None:
    """C'est toute la raison d'être du canal 5 : un seuil ici refarait le canal 4 et
    reperdrait exactement les paires que ce canal existe pour rattraper."""
    requete = dimension.requete()
    assert "score >=" not in requete
    assert "$seuil" not in requete


def test_le_canal_dimension_compare_les_deux_sens() -> None:
    """``<>`` et non ``<`` : le top-N doit être calculé par clause **des deux côtés**, sinon
    seules les clauses de D1 auraient droit à leurs meilleurs partenaires."""
    assert "a.doc_id <> b.doc_id" in dimension.requete()


def test_le_canal_dimension_ignore_les_grandeurs_sans_valeur() -> None:
    """Une grandeur AMBIGU (bimensuel/bimestriel) n'a pas de valeur tranchée : la comparer
    reviendrait à inventer un écart ou une égalité."""
    assert "qa.valeur_si IS NOT NULL" in dimension.requete()


def test_le_canal_conceptuel_traverse_le_pont_par_defaut() -> None:
    """C'est le saut par `ALIAS_DE` qui rend les concepts « canoniques » (architecture.md
    §6.3) : sans lui, « Responsable QSE » ne rencontre jamais « Référent sécurité »."""
    assert "ALIAS_DE" in conceptuel.requete(avec_pont=True)


def test_l_ablation_retire_le_saut_par_alias() -> None:
    """Le cas négatif du précédent, et le mécanisme même de l'ablation du J4."""
    assert "ALIAS_DE" not in conceptuel.requete(avec_pont=False)


# --------------------------------------------------------------------- le classement


def test_classer_ordonne_par_score_decroissant() -> None:
    appariements = classer([("A", "B", 0.5), ("C", "D", 0.9)], Canal.VECTORIEL)
    assert [a.rang for a in appariements] == [1, 2]
    assert appariements[0].clause_a == "C"


def test_classer_deduplique_sur_la_cle_non_ordonnee() -> None:
    """Le canal vectoriel voit chaque paire des deux côtés : il ne doit la proposer qu'une
    fois, avec son meilleur score."""
    appariements = classer([("A", "B", 0.5), ("B", "A", 0.9)], Canal.VECTORIEL)
    assert len(appariements) == 1
    assert appariements[0].score == pytest.approx(0.9)


def test_classer_normalise_l_ordre_des_clauses() -> None:
    """La clé est non ordonnée : ``clause_a`` est toujours le plus petit identifiant."""
    appariements = classer([("Z", "A", 0.5)], Canal.VECTORIEL)
    assert (appariements[0].clause_a, appariements[0].clause_b) == ("A", "Z")


def test_classer_est_deterministe_a_score_egal() -> None:
    """Sinon deux exécutions du même ciblage produiraient des rangs différents, donc des
    scores de fusion différents, donc des troncatures différentes."""
    entrees = [("B", "C", 0.5), ("A", "D", 0.5)]
    premier = [(a.clause_a, a.rang) for a in classer(entrees, Canal.VECTORIEL)]
    second = [(a.clause_a, a.rang) for a in classer(list(reversed(entrees)), Canal.VECTORIEL)]
    assert premier == second


def test_classer_sans_entree_rend_une_liste_vide() -> None:
    assert classer([], Canal.DIMENSION) == []


def test_le_rang_est_global_au_canal() -> None:
    """La fusion RRF consomme « le rang de la paire dans la liste ordonnée du canal ».

    Un canal qui rendrait des rangs par clause donnerait à toutes ses paires un poids quasi
    identique et écraserait le signal que la fusion cherche à exploiter.
    """
    appariements = classer([("A", "B", 0.9), ("A", "C", 0.8), ("D", "E", 0.7)], Canal.DIMENSION)
    assert [a.rang for a in appariements] == [1, 2, 3]
