"""Tests du harnais d'évaluation.

Le harnais est l'instrument de mesure de toute la semaine : s'il ment, tous les chiffres
des six jours suivants mentent avec lui. D'où ces tests avant toute logique métier.

Les rapports de test sont fabriqués **à partir de** ``label.json``, avec deux précautions
qui les empêchent d'être des tautologies :

* les côtés a et b sont **inversés** par rapport à la vérité terrain, ce qui prouve que
  l'appariement est bien insensible à l'ordre ;
* le ``type`` et le ``detecteur`` sont délibérément faux, ce qui prouve que l'appariement
  ne repose que sur le couple ``(doc, ref)``.
"""

from __future__ import annotations

import pytest

from cohera.evaluation import metriques
from cohera.restitution.rapport_json import Constatation, CoteClause, Rapport


@pytest.fixture(scope="module")
def verite() -> dict:
    return metriques.charger_verite("fixtures")


# ------------------------------------------------------------------- fabrication


def _cote(brut: dict | None) -> CoteClause | None:
    if brut is None:
        return None
    return CoteClause(
        doc=brut.get("doc", ""),
        ref=brut.get("ref", ""),
        preuve=brut.get("extrait", ""),
    )


def constatation_inversee(entree: dict) -> Constatation:
    """Constatation correspondant à une entrée de la vérité terrain, côtés a/b permutés."""
    cote_a = _cote(entree.get("clause_a"))
    cote_b = _cote(entree.get("clause_b"))

    if cote_b is None:
        premier, second = cote_a, None  # anomalie mono-clause : rien à permuter
    else:
        premier, second = cote_b, cote_a

    return Constatation(
        id=f"C-{entree.get('id', '?')}",
        type="TYPE_VOLONTAIREMENT_FAUX",
        detecteur="detecteur_volontairement_faux",
        etage="A",
        gravite="MOYENNE",
        confiance=0.5,
        explication="Fabriquée par le test.",
        clause_a=premier,
        clause_b=second,
    )


def rapport_des_bonnes_reponses(verite: dict, extra: list[dict] | None = None) -> Rapport:
    entrees = list(verite["incoherences"]) + list(extra or [])
    return Rapport(
        corpus=verite.get("corpus", ""),
        constatations=[constatation_inversee(e) for e in entrees],
    )


def _entree(verite: dict, rubrique: str, identifiant: str) -> dict:
    for entree in verite[rubrique]:
        if entree.get("id") == identifiant:
            return entree
    raise AssertionError(f"{identifiant} absent de {rubrique} dans label.json")


# ------------------------------------------------------------------------- tests


def test_rapport_vide_donne_zeros(verite: dict) -> None:
    """Un rapport vide doit rendre des zéros, pas une division par zéro.

    C'est la ligne de base du J0 : le pipeline n'existe pas encore, et `cohera evaluer`
    doit quand même produire un chiffre à faire bouger.
    """
    resultat = metriques.evaluer(Rapport(), verite)

    for bareme in (resultat.globale, resultat.perimetre_7j):
        assert bareme.precision == 0.0
        assert bareme.rappel == 0.0
        assert bareme.f1 == 0.0
        assert bareme.rappel_ciblage == 0.0
        assert bareme.vrais_positifs == []
        assert bareme.faux_positifs == []

    # Rien de détecté, donc tout est manqué.
    assert len(resultat.globale.faux_negatifs) == verite["recapitulatif"]["incoherences_totales"]
    assert (
        len(resultat.perimetre_7j.faux_negatifs)
        == verite["recapitulatif"]["incoherences_dans_perimetre_7_jours"]
    )


def test_dix_neuf_bonnes_reponses_donnent_precision_1(verite: dict) -> None:
    """Les 19 bonnes réponses, et rien d'autre : précision et rappel parfaits."""
    resultat = metriques.evaluer(rapport_des_bonnes_reponses(verite), verite)

    assert resultat.globale.precision == 1.0
    assert resultat.globale.rappel == 1.0
    assert resultat.globale.f1 == 1.0
    assert resultat.globale.faux_positifs == []
    assert resultat.globale.faux_negatifs == []
    assert len(resultat.globale.vrais_positifs) == 19

    # Le barème restreint ne retient que les 12 du périmètre, sans pénaliser les 7 autres :
    # trouver mieux que demandé ne doit pas coûter de points.
    assert resultat.perimetre_7j.rappel == 1.0
    assert resultat.perimetre_7j.faux_positifs == []
    assert resultat.perimetre_7j.attendues == 12


def test_le_piege_n01_apparait_nommement(verite: dict) -> None:
    """Les 19 bonnes réponses plus le piège N01 : le faux positif doit être nommé.

    N01 est une spécialisation compatible — même clé de comparaison, valeur plus stricte
    sur une portée incluse. Un harnais qui se contenterait de compter « 1 faux positif »
    ne dirait pas *lequel* des neuf pièges a fonctionné, et donc pas quoi corriger.
    """
    piege = _entree(verite, "contre_exemples", "N01")
    resultat = metriques.evaluer(rapport_des_bonnes_reponses(verite, extra=[piege]), verite)

    assert "N01" in resultat.globale.ids_faux_positifs
    assert len(resultat.globale.faux_positifs) == 1
    assert resultat.globale.precision == pytest.approx(19 / 20)
    assert resultat.globale.rappel == 1.0

    # Le faux positif porte la raison de la vérité terrain, pas seulement un identifiant.
    faux_positif = resultat.globale.faux_positifs[0]
    assert "SPECIALISATION" in piege["attendu"]
    assert faux_positif.raison
    assert sorted(faux_positif.clauses) == ["D1 §4.2", "D2 §4.6"]

    # N01 est dans le périmètre 7 jours : le critère « 0 faux positif » doit virer au rouge.
    assert "N01" in resultat.perimetre_7j.ids_faux_positifs
    critere = next(c for c in resultat.cibles if c.nom.startswith("Faux positifs"))
    assert critere.atteint is False


# --------------------------------------------------- garde-fous du harnais lui-même


def test_les_cles_de_la_verite_terrain_sont_uniques(verite: dict) -> None:
    """Deux entrées ne doivent jamais partager une clé d'appariement.

    Si c'était le cas, un vrai positif et un faux positif deviendraient indiscernables et
    toutes les métriques mentiraient en silence.
    """
    assert metriques.cles_en_collision(verite) == []


def test_une_constatation_hors_perimetre_ne_compte_pas_comme_faux_positif(verite: dict) -> None:
    """I06 est une vraie incohérence, hors périmètre 7 jours : ni crédit, ni pénalité."""
    hors_perimetre = _entree(verite, "incoherences", "I06")
    assert hors_perimetre["dans_perimetre_7j"] is False

    rapport = Rapport(constatations=[constatation_inversee(hors_perimetre)])
    resultat = metriques.evaluer(rapport, verite)

    assert resultat.globale.vrais_positifs == ["I06"]
    assert resultat.perimetre_7j.vrais_positifs == []
    assert resultat.perimetre_7j.faux_positifs == []


def test_un_doublon_ne_gonfle_ni_le_rappel_ni_les_faux_positifs(verite: dict) -> None:
    """Deux constatations sur la même incohérence : signalées, mais comptées une fois."""
    entree = _entree(verite, "incoherences", "I04")
    rapport = Rapport(
        constatations=[constatation_inversee(entree), constatation_inversee(entree)]
    )
    resultat = metriques.evaluer(rapport, verite)

    assert resultat.globale.vrais_positifs == ["I04"]
    assert resultat.globale.faux_positifs == []
    assert resultat.doublons == ["I04"]


def test_le_ciblage_couvre_les_anomalies_mono_clause(verite: dict) -> None:
    """I09 n'a pas de clause_b : elle est ciblée dès lors que sa clause a été analysée.

    Sans cette règle, la cible « rappel du ciblage 12/12 » de label.json serait
    inatteignable par construction, puisque deux des douze incohérences du périmètre sont
    des anomalies mono-clause.
    """
    from cohera.restitution.rapport_json import RefClause

    mono = _entree(verite, "incoherences", "I09")
    assert mono["clause_b"] is None

    reference = RefClause(doc=mono["clause_a"]["doc"], ref=mono["clause_a"]["ref"])
    resultat = metriques.evaluer(Rapport(clauses_analysees=[reference]), verite)

    assert "I09" not in resultat.perimetre_7j.ciblage_manquants
    assert resultat.perimetre_7j.rappel_ciblage > 0.0
