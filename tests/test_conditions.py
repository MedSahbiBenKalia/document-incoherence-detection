"""regles/conditions.py — conditions typées (SPATIAL/TEMPOREL/CIRCONSTANCIEL/SEUIL).

Frontière avec regles/grandeurs.py (voir docs du jour, §8) : un seuil dont le rôle est
enregistré dans registre_grandeurs.yaml (ex. seuil_declenchement pour « à plus de 3
mètres ») est une Grandeur, pas une Condition. Un seuil sans rôle enregistré (vitesse du
vent en km/h, durée d'une intervention) reste une Condition(SEUIL).
"""

from __future__ import annotations

from cohera.extraction.frames import TypeCondition
from cohera.extraction.regles.conditions import extraire_conditions
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


def _types(conditions) -> set:
    return {c.type for c in conditions}


# --------------------------------------------------------------------------- SPATIAL


def test_en_zone_a_produit_une_condition_spatiale(d1) -> None:
    conditions = extraire_conditions(d1.clause("5.2"))
    spatiales = [c for c in conditions if c.type is TypeCondition.SPATIAL]
    assert len(spatiales) == 1
    assert spatiales[0].concept_cible == "zone A"
    assert spatiales[0].operateur == "APPARTIENT"


def test_en_zone_de_stockage_est_une_zone_differente_de_zone_a(d2) -> None:
    """N04 : mêmes objets, zones DISJOINTES — le concept_cible doit distinguer les deux
    zones, pas les confondre."""
    conditions = extraire_conditions(d2.clause("5.2"))
    spatiales = [c for c in conditions if c.type is TypeCondition.SPATIAL]
    assert len(spatiales) == 1
    assert spatiales[0].concept_cible == "zone de stockage"


def test_le_site_5_2_zone_a_et_5_2_zone_de_stockage_sont_bien_distincts(d1, d2) -> None:
    a = next(c for c in extraire_conditions(d1.clause("5.2")) if c.type is TypeCondition.SPATIAL)
    b = next(c for c in extraire_conditions(d2.clause("5.2")) if c.type is TypeCondition.SPATIAL)
    assert a.concept_cible != b.concept_cible


# --------------------------------------------------------------- CIRCONSTANCIEL / TEMPOREL


def test_en_cas_d_incident_grave_est_circonstanciel(d1) -> None:
    conditions = extraire_conditions(d1.clause("6.1"))
    assert TypeCondition.CIRCONSTANCIEL in _types(conditions)


def test_lorsque_est_circonstanciel(d1) -> None:
    conditions = extraire_conditions(d1.clause("6.4"))
    assert TypeCondition.CIRCONSTANCIEL in _types(conditions)


def test_quelle_que_soit_est_circonstanciel(d2) -> None:
    conditions = extraire_conditions(d2.clause("6.4"))
    assert TypeCondition.CIRCONSTANCIEL in _types(conditions)


def test_avant_chaque_prise_de_poste_est_temporel(d1) -> None:
    conditions = extraire_conditions(d1.clause("5.2"))
    assert TypeCondition.TEMPOREL in _types(conditions)


def test_avant_sa_prise_de_poste_est_temporel(d2) -> None:
    conditions = extraire_conditions(d2.clause("8.1"))
    assert TypeCondition.TEMPOREL in _types(conditions)


# -------------------------------------------------------------------------------- SEUIL


def test_vitesse_du_vent_d1_est_un_seuil_sans_role_enregistre(d1) -> None:
    conditions = extraire_conditions(d1.clause("7.3"))
    seuils = [c for c in conditions if c.type is TypeCondition.SEUIL]
    assert len(seuils) == 1
    assert seuils[0].valeur == 50
    assert seuils[0].operateur == ">"


def test_vitesse_du_vent_d2_est_aussi_un_seuil(d2) -> None:
    seuils = [c for c in extraire_conditions(d2.clause("7.3")) if c.type is TypeCondition.SEUIL]
    assert len(seuils) == 1
    assert seuils[0].valeur == 50


def test_moins_de_30_minutes_est_un_seuil(d1) -> None:
    seuils = [c for c in extraire_conditions(d1.clause("7.4")) if c.type is TypeCondition.SEUIL]
    assert len(seuils) == 1
    assert seuils[0].valeur == 30
    assert seuils[0].operateur == "<"


def test_duree_inferieure_a_deux_heures_est_un_seuil_en_toutes_lettres(d1) -> None:
    seuils = [c for c in extraire_conditions(d1.clause("10.1")) if c.type is TypeCondition.SEUIL]
    assert len(seuils) == 1
    assert seuils[0].valeur == 2


# ---------------------------------------------------- négatif : pas de doublon avec grandeurs.py


def test_un_seuil_comparable_en_metres_ne_devient_pas_une_condition_seuil(d1, d2) -> None:
    """D1§7.1/D2§7.1 : « à plus de 3/2 mètres » est l'axe de comparaison d'I13 — capturé
    par regles/grandeurs.py (rôle seuil_declenchement), pas ici."""
    assert not any(c.type is TypeCondition.SEUIL for c in extraire_conditions(d1.clause("7.1")))
    assert not any(c.type is TypeCondition.SEUIL for c in extraire_conditions(d2.clause("7.1")))


def test_une_duree_de_formation_avec_contexte_ne_devient_pas_un_seuil(d1) -> None:
    """D1§8.1 : « au minimum 14 heures » est une Grandeur duree_formation ; le contexte
    « formation » l'exclut du repérage SEUIL générique."""
    assert not any(c.type is TypeCondition.SEUIL for c in extraire_conditions(d1.clause("8.1")))


def test_un_delai_encadre_ne_devient_pas_un_seuil(d1) -> None:
    """D1§4.2 : « sous 48 heures » est une Grandeur delai, pas une Condition SEUIL."""
    assert not any(c.type is TypeCondition.SEUIL for c in extraire_conditions(d1.clause("4.2")))


def test_une_zone_sans_axe_numerique_ne_produit_aucun_seuil(d2) -> None:
    assert extraire_conditions(d2.clause("5.2")) == [
        c for c in extraire_conditions(d2.clause("5.2")) if c.type is not TypeCondition.SEUIL
    ]
