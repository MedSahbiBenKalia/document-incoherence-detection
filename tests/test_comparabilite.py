"""ciblage/comparabilite.py — le filtre qui décide si deux clauses peuvent se contredire.

Critère du J4 (docs/plan-1-semaine.md §J4) : « Le contre-exemple N3 (phrases de cadrage) est
rejeté par le filtre de comparabilité ». Le mot qui compte est *filtre* : le rejet doit
tomber **avant** tout modèle, donc dans une fonction qui ne connaît ni Neo4j, ni les
embeddings, ni le NLI. C'est ce que ces tests vérifient en construisant les contextes à la
main, sans serveur.

Cinq branches acceptent, une seule les refuse toutes : chaque branche a donc son test
positif, et le refus a les siens (`CLAUDE.md` : « un détecteur = un test positif ET un test
négatif »).
"""

from __future__ import annotations

from cohera.ciblage.comparabilite import Motif, comparable
from cohera.ciblage.modeles import ContexteClause
from cohera.extraction.frames import Modalite


def contexte(**champs) -> ContexteClause:
    """Un contexte minimal, que chaque test enrichit de ce qu'il veut éprouver."""
    champs.setdefault("clause_id", "D?::S0::C00")
    return ContexteClause(**champs)


# --------------------------------------------------------------- branche 1 : modalité


def test_deux_modalites_prescriptives_rendent_la_paire_comparable() -> None:
    """La forme de I04 : une PERMISSION contre une INTERDICTION sur le même objet."""
    verdict = comparable(
        contexte(modalite=Modalite.PERMISSION),
        contexte(modalite=Modalite.INTERDICTION),
    )
    assert verdict.comparable
    assert verdict.motif is Motif.MODALITE


def test_une_definition_et_un_constat_ne_sont_pas_comparables_par_la_modalite() -> None:
    """« Une définition et un seuil ne se contredisent pas » (architecture.md §6.6).

    DEFINITION et CONSTAT sont absents de `modalites_prescriptives` : c'est ce qui empêche
    la branche 1 d'accepter cette paire.
    """
    verdict = comparable(
        contexte(modalite=Modalite.DEFINITION),
        contexte(modalite=Modalite.CONSTAT),
    )
    assert not verdict.comparable


def test_une_seule_modalite_prescriptive_ne_suffit_pas() -> None:
    """La branche exige les DEUX côtés : une obligation face à une définition ne prescrit
    rien de comparable."""
    verdict = comparable(
        contexte(modalite=Modalite.OBLIGATION),
        contexte(modalite=Modalite.DEFINITION),
    )
    assert not verdict.comparable


# -------------------------------------------------------------- branche 2 : dimension


def test_une_grandeur_de_meme_dimension_et_meme_role_rend_comparable() -> None:
    """La forme de I12 : aucune modalité extraite de part et d'autre, mais un délai contre
    un délai."""
    verdict = comparable(
        contexte(dimensions_roles=[("TEMPS", "delai")]),
        contexte(dimensions_roles=[("TEMPS", "delai")]),
    )
    assert verdict.comparable
    assert verdict.motif is Motif.DIMENSION


def test_une_meme_dimension_avec_des_roles_differents_ne_suffit_pas() -> None:
    """Cas négatif de la branche : un délai et une durée de conservation sont tous deux en
    TEMPS, mais ne mesurent pas la même chose et leurs monotonies sont opposées
    (`config/registre_grandeurs.yaml`)."""
    verdict = comparable(
        contexte(dimensions_roles=[("TEMPS", "delai")]),
        contexte(dimensions_roles=[("TEMPS", "duree_conservation")]),
    )
    assert not verdict.comparable


# ----------------------------------------------------------------- branche 3 : renvoi


def test_un_renvoi_explicite_rend_la_paire_comparable() -> None:
    """Le renvoi est lu sur les `Reference` des Clause Frames : `chargeur.py` n'écrit pas
    d'arête `RENVOIE_A`."""
    verdict = comparable(
        contexte(doc_id="D1", ref="10.1", renvois=[("D2", "6.4")]),
        contexte(doc_id="D2", ref="6.4"),
    )
    assert verdict.comparable
    assert verdict.motif is Motif.RENVOI


def test_un_renvoi_vers_une_autre_clause_ne_rend_pas_comparable() -> None:
    """Cas négatif : le renvoi doit viser *cette* clause, pas une voisine."""
    verdict = comparable(
        contexte(doc_id="D1", ref="10.1", renvois=[("D2", "6.4")]),
        contexte(doc_id="D2", ref="6.5"),
    )
    assert not verdict.comparable


# ------------------------------------------------------------------ branche 4 : norme


def test_deux_referentiels_divergents_rendent_la_paire_comparable() -> None:
    """La forme de I08 : ISO 45001 d'un côté, OHSAS 18001 de l'autre.

    Les référentiels sont *différents*, et c'est justement l'incohérence. Exiger un
    référentiel commun écarterait le seul cas que cette branche existe pour attraper.
    """
    verdict = comparable(
        contexte(normes_citees=["ISO 45001"]),
        contexte(normes_citees=["OHSAS 18001"]),
    )
    assert verdict.comparable
    assert verdict.motif is Motif.NORME


def test_un_referentiel_d_un_seul_cote_ne_suffit_pas() -> None:
    verdict = comparable(contexte(normes_citees=["ISO 45001"]), contexte())
    assert not verdict.comparable


# ------------------------------------------------------------- branche 5 : conceptuelle


def test_deux_concepts_canoniques_partages_rendent_la_paire_comparable() -> None:
    """La forme de I11 : ni modalité, ni grandeur commune, mais « installation » et la
    classe « arrêter ~ arrêt » partagés.

    Le seuil est celui du canal 3 : une paire qui a franchi le canal conceptuel a déjà fait
    la preuve de sa comparabilité.
    """
    verdict = comparable(
        contexte(concepts_canoniques=["K_installation", "K_arreter"]),
        contexte(concepts_canoniques=["K_installation", "K_arreter", "K_referent"]),
    )
    assert verdict.comparable
    assert verdict.motif is Motif.CONCEPTS


def test_un_seul_concept_partage_ne_suffit_pas() -> None:
    """Cas négatif : un unique terme commun apparierait des dizaines de clauses sans
    rapport — c'est la raison d'être de `partages_min`."""
    verdict = comparable(
        contexte(concepts_canoniques=["K_zone"]),
        contexte(concepts_canoniques=["K_zone", "K_casque"]),
    )
    assert not verdict.comparable


# ------------------------------------------------------------------------ N03, le piège


def test_n03_est_rejete_par_le_filtre() -> None:
    """LE cas négatif du J4.

    N03 = D1 §1.1 contre D2 §2.1, « deux phrases de cadrage citant le même site, similarité
    élevée, aucune modalité prescriptive ni grandeur » (label.json). Mesuré sur le corpus :
    cosinus 0,797, modalités nulles des deux côtés, aucune grandeur, aucun référentiel,
    zéro concept partagé.

    La paire est donc rejetée sans qu'aucun modèle ne soit appelé : c'est la formulation
    exacte du critère du plan.
    """
    verdict = comparable(
        contexte(clause_id="D1::S1::C01", doc_id="D1", ref="1.1"),
        contexte(clause_id="D2::S2::C01", doc_id="D2", ref="2.1"),
    )
    assert not verdict.comparable
    assert verdict.motif is Motif.AUCUNE_BRANCHE


def test_un_rejet_porte_toujours_son_motif() -> None:
    """`.claude/rules/detection.md` : « Toute paire écartée par un filtre est journalisée
    avec son motif. » Un verdict négatif sans explication ne serait pas journalisable."""
    verdict = comparable(contexte(), contexte())
    assert verdict.explication


def test_le_verdict_se_lit_comme_un_booleen() -> None:
    """`if comparable(a, b):` doit fonctionner sans perdre le motif pour le journal."""
    assert bool(comparable(contexte(modalite=Modalite.OBLIGATION), contexte(modalite=Modalite.INTERDICTION)))
    assert not bool(comparable(contexte(), contexte()))
