"""regles/__init__.py — orchestration : fusion des cinq extracteurs, calcul de
`type_enonce`, provenance par champ."""

from __future__ import annotations

from cohera.extraction.frames import Modalite, TypeEnonce
from cohera.extraction.regles import extraire_frame, extraire_toutes


def test_extraire_toutes_couvre_les_78_clauses_du_corpus(jeu) -> None:
    frames = extraire_toutes(jeu)
    assert len(frames) == 41 + 37
    assert all(clause_id == frame.clause_id for clause_id, frame in frames.items())


def test_un_renvoi_seul_sans_marqueur_devient_renvoi(d1, jeu) -> None:
    frame = extraire_frame(d1.clause("7.5"), "D1", jeu)
    assert frame.modalite is None
    assert frame.type_enonce is TypeEnonce.RENVOI


def test_un_renvoi_croise_seul_devient_aussi_renvoi(d2, jeu) -> None:
    frame = extraire_frame(d2.clause("6.3"), "D2", jeu)
    assert frame.type_enonce is TypeEnonce.RENVOI


def test_une_clause_sans_rien_devient_constat(d1, jeu) -> None:
    frame = extraire_frame(d1.clause("9.3"), "D1", jeu)
    assert frame.modalite is None
    assert frame.quantites == []
    assert frame.references == []
    assert frame.type_enonce is TypeEnonce.CONSTAT


def test_une_derogation_l_emporte_sur_le_type_enonce_mais_pas_sur_la_modalite(d1, jeu) -> None:
    """D1 §10.1 : dérogation ET « sont dispensées » (PERMISSION) — les deux champs sont
    posés indépendamment."""
    frame = extraire_frame(d1.clause("10.1"), "D1", jeu)
    assert frame.type_enonce is TypeEnonce.DEROGATION
    assert frame.modalite is Modalite.PERMISSION
    assert frame.derogation is not None


def test_une_prescription_ordinaire_devient_prescription(d1, jeu) -> None:
    frame = extraire_frame(d1.clause("5.4"), "D1", jeu)
    assert frame.modalite is Modalite.OBLIGATION
    assert frame.type_enonce is TypeEnonce.PRESCRIPTION


def test_une_definition_devient_definition(d1, jeu) -> None:
    frame = extraire_frame(d1.clause("3.2"), "D1", jeu)
    assert frame.modalite is Modalite.DEFINITION
    assert frame.type_enonce is TypeEnonce.DEFINITION


# ------------------------------------------------------------------- source_extraction


def test_les_champs_non_touches_sont_absents_de_source_extraction(d1, jeu) -> None:
    """L'absence de clé signale « jamais examiné », distinct d'un champ REGLE à valeur
    None — acteur/action/objet/perimetre/portee restent hors périmètre J2."""
    frame = extraire_frame(d1.clause("5.1"), "D1", jeu)
    for champ in ("acteur", "action", "objet", "perimetre", "portee", "risques_maitrises"):
        assert champ not in frame.source_extraction


def test_une_grandeur_trouvee_est_tracee_comme_regle(d1, jeu) -> None:
    frame = extraire_frame(d1.clause("4.2"), "D1", jeu)
    assert frame.source_extraction["quantites"] == "REGLE"


def test_une_modalite_trouvee_est_tracee_comme_regle(d1, jeu) -> None:
    frame = extraire_frame(d1.clause("5.4"), "D1", jeu)
    assert frame.source_extraction["modalite"] == "REGLE"
    assert frame.source_extraction["force"] == "REGLE"
    assert frame.source_extraction["negation"] == "REGLE"


def test_confiance_extraction_par_defaut_est_maximale(d1, jeu) -> None:
    frame = extraire_frame(d1.clause("5.4"), "D1", jeu)
    assert frame.confiance_extraction == 1.0


def test_le_repli_gazetteer_abaisse_la_confiance_de_toute_la_frame(d2, jeu) -> None:
    frame = extraire_frame(d2.clause("4.3"), "D2", jeu)
    assert frame.modalite is Modalite.OBLIGATION
    assert frame.confiance_extraction == 0.78
    assert "confiance_extraction" not in frame.source_extraction
