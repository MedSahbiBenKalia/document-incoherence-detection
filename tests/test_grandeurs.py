"""regles/grandeurs.py — CAP04 (délais imprécis), CAP05 (équivalence de périodicité),
CAP06 (jours ouvrés vs calendaires), CAP07 (opérateurs de seuil).

Critère chiffré (docs/plan-1-semaine.md §J2) : ≥ 35/40 grandeurs correctes sur un jeu
annoté à la main. Le jeu ci-dessous combine les empans réels du corpus (positifs) et des
cas d'exclusion (négatifs) — voir docs/plan-1-semaine.md et le plan de la journée pour le
détail du catalogue.
"""

from __future__ import annotations

import pytest

from cohera.extraction.frames import Operateur, StatutGrandeur
from cohera.extraction.regles.grandeurs import _detecter_operateur, extraire_grandeurs
from cohera.ingestion.modeles import Clause


def _clause(texte: str) -> Clause:
    return Clause(
        clause_id="TEST::S0::C01",
        doc_id="TEST",
        ref="0.1",
        ordre=1,
        texte_source=texte,
        texte_autonome=texte,
        offset=(0, len(texte)),
    )


def _item(clauses: list[Clause], motif: str) -> Clause:
    return next(c for c in clauses if motif in c.texte_source)


def _seule(grandeurs: list) -> object:
    assert len(grandeurs) == 1, grandeurs
    return grandeurs[0]


# ------------------------------------------------------------- 31 empans réels positifs


@pytest.mark.parametrize(
    "doc_fixture,ref,role,valeur_si",
    [
        ("d1", "4.2", "delai", 172800),  # sous 48 heures
        ("d1", "5.1", "periodicite", 7884000),  # tous les trimestres
        ("d1", "5.3", "periodicite", 31536000),  # tous les 12 mois (contrôle, pas habilitation)
        ("d1", "5.5", "seuil_exposition", 85),  # au-delà de 85 dB(A)
        ("d1", "5.6", "delai", 432000),  # sous 5 jours ouvrés
        ("d1", "6.2", "delai", 86400),  # sous 24 heures
        ("d1", "6.3", "delai", 1296000),  # dans un délai de 15 jours ouvrés
        ("d1", "6.5", "periodicite", 2628000),  # revue mensuelle
        ("d1", "7.1", "seuil_declenchement", 3),  # à plus de 3 mètres
        ("d1", "8.1", "duree_formation", 50400),  # au minimum 14 heures
        ("d1", "8.2", "validite_habilitation", 94608000),  # habilitation recyclée tous les 3 ans
        ("d1", "8.4", "effectif_minimum", 1),  # fixé à un
        ("d1", "9.2", "duree_conservation", 94608000),  # archivé pendant 3 ans
        ("d1", "10.2", "delai", 1296000),  # délai... porté à 15 jours
        ("d1", "10.3", "periodicite", 15768000),  # périodicité... est semestrielle
        ("d2", "4.2", "delai", 432000),  # dans un délai de 5 jours ouvrés
        ("d2", "4.5", "delai", 864000),  # sous 10 jours ouvrés
        ("d2", "4.6", "delai", 86400),  # sous 24 heures
        ("d2", "5.1", "periodicite", 15768000),  # deux fois par an
        ("d2", "5.2", "periodicite", 604800),  # une fois par semaine
        ("d2", "5.3", "periodicite", 31536000),  # vérification annuelle
        ("d2", "5.5", "seuil_exposition", 80),  # dépasse 80 dB(A)
        ("d2", "6.5", "periodicite", 7884000),  # chaque trimestre
        ("d2", "7.1", "seuil_declenchement", 2),  # à plus de 2 mètres
        ("d2", "8.2", "validite_habilitation", 63072000),  # recyclage... tous les 2 ans
        ("d2", "8.4", "effectif_minimum", 2),  # au minimum deux
        ("d2", "9.1", "duree_conservation", 157680000),  # conservés pendant 5 ans
    ],
)
def test_une_grandeur_reelle_du_corpus_est_correctement_extraite(
    doc_fixture: str, ref: str, role: str, valeur_si: int, request: pytest.FixtureRequest
) -> None:
    segmentation = request.getfixturevalue(doc_fixture)
    grandeur = _seule(extraire_grandeurs(segmentation.clause(ref)))
    assert grandeur.role == role
    assert grandeur.valeur_si == valeur_si


def test_l_item_c_de_la_liste_4_4_porte_un_delai_de_cinq_jours(d1) -> None:
    """« informer le chef d'atelier de tout retard supérieur à cinq jours » — nombre en
    toutes lettres, marqueur « retard »."""
    item = _item(d1.par_ref("4.4"), "retard")
    grandeur = _seule(extraire_grandeurs(item))
    assert grandeur.role == "delai"
    assert grandeur.valeur_si == 432000
    assert grandeur.operateur is Operateur.SUPERIEUR


# ------------------------------------------------------- 8 cas négatifs / d'exclusion


def test_une_norme_datee_ne_produit_aucune_grandeur(d1) -> None:
    assert extraire_grandeurs(d1.clause("2.1")) == []  # ISO 45001:2018


def test_une_reference_de_paragraphe_ne_produit_aucune_grandeur(d1) -> None:
    assert extraire_grandeurs(d1.clause("7.5")) == []  # § 12.3


def test_un_numero_de_version_seul_ne_produit_aucune_grandeur() -> None:
    assert extraire_grandeurs(_clause("La version 3 de ce document a été approuvée.")) == []


def test_un_adjectif_vague_sans_unite_ne_produit_aucune_grandeur(d1) -> None:
    item = _item(d1.par_ref("4.4"), "planifier")  # "contrôles périodiques", pas de chiffre
    assert extraire_grandeurs(item) == []


def test_une_vitesse_de_vent_ne_correspond_a_aucun_role_enregistre(d1, d2) -> None:
    """D1§7.3/D2§7.3 : le km/h ne correspond à aucun des 10 rôles du registre — reste une
    Condition(SEUIL), voir test_conditions.py."""
    assert extraire_grandeurs(d1.clause("7.3")) == []
    assert extraire_grandeurs(d2.clause("7.3")) == []


def test_une_duree_d_intervention_sans_marqueur_de_delai_ne_produit_pas_de_grandeur(d1) -> None:
    """D1§7.4 : « de moins de 30 minutes » qualifie la portée de l'autorisation, ce n'est
    pas un délai de réponse (pas de « sous »/« délai »/« retard »)."""
    assert extraire_grandeurs(d1.clause("7.4")) == []


def test_la_duree_de_portee_d_une_derogation_ne_produit_pas_de_grandeur(d1) -> None:
    """D1§10.1 : « durée inférieure à deux heures » borne la dérogation, ce n'est ni un
    délai ni une durée de conservation/formation/habilitation."""
    assert extraire_grandeurs(d1.clause("10.1")) == []


# ---------------------------------------------------------------------------- CAP05


def test_trimestriel_egale_tous_les_3_mois_egale_4_fois_par_an() -> None:
    a = _seule(extraire_grandeurs(_clause("Le contrôle est trimestriel.")))
    b = _seule(extraire_grandeurs(_clause("Le contrôle a lieu tous les 3 mois.")))
    c = _seule(extraire_grandeurs(_clause("Le contrôle a lieu 4 fois par an.")))
    assert a.valeur_si == b.valeur_si == c.valeur_si == 7884000


def test_douze_mois_egale_annuelle() -> None:
    a = _seule(extraire_grandeurs(_clause("Le contrôle a lieu tous les 12 mois.")))
    b = _seule(extraire_grandeurs(_clause("Le contrôle est annuel.")))
    assert a.valeur_si == b.valeur_si == 31536000


def test_bimestriel_produit_ambigu_jamais_une_valeur_tranchee_en_silence() -> None:
    grandeur = _seule(extraire_grandeurs(_clause("Le contrôle est bimestriel.")))
    assert grandeur.statut is StatutGrandeur.AMBIGU
    assert grandeur.valeur_si is None


def test_bimensuel_produit_aussi_ambigu() -> None:
    grandeur = _seule(extraire_grandeurs(_clause("Le contrôle est bimensuel.")))
    assert grandeur.statut is StatutGrandeur.AMBIGU


# ---------------------------------------------------------------------------- CAP06


def test_jours_ouvres_porte_la_valeur_nominale_et_calendaire(d1) -> None:
    grandeur = _seule(extraire_grandeurs(d1.clause("5.6")))
    assert grandeur.valeur_si == 432000
    assert grandeur.valeur_si_calendaire == 604800
    assert grandeur.qualificateurs["calendrier"] == "ouvre"


def test_des_jours_simples_sans_ouvres_n_ont_pas_de_valeur_calendaire() -> None:
    grandeur = _seule(extraire_grandeurs(_clause("La commande est livrée sous 10 jours.")))
    assert grandeur.valeur_si == 864000
    assert grandeur.valeur_si_calendaire is None
    assert grandeur.qualificateurs["calendrier"] == "calendaire"


# ---------------------------------------------------------------------------- CAP07


@pytest.mark.parametrize(
    "texte",
    ["au-delà de 2 m", "dépasse 80 dB(A)", "à plus de 3 mètres", "supérieure à 50 km/h"],
)
def test_les_quatre_marqueurs_de_seuil_produisent_l_operateur_superieur(texte: str) -> None:
    assert _detecter_operateur(texte) is Operateur.SUPERIEUR


def test_une_phrase_sans_marqueur_de_seuil_garde_l_operateur_egal_par_defaut() -> None:
    assert _detecter_operateur("Le contrôle a lieu tous les trimestres.") is Operateur.EGAL


# ---------------------------------------------------------------------------- CAP04


def test_dans_la_semaine_produit_un_delai_imprecis_non_nul(d2) -> None:
    grandeur = _seule(extraire_grandeurs(d2.clause("6.2")))
    assert grandeur.role == "delai"
    assert grandeur.statut is StatutGrandeur.IMPRECIS
    assert grandeur.valeur_si == 604800


def test_sous_48_heures_reste_un_delai_normal_non_imprecis(d1) -> None:
    grandeur = _seule(extraire_grandeurs(d1.clause("4.2")))
    assert grandeur.statut is StatutGrandeur.NORMAL
