"""regles/validite.py — CAP09 (dates de début/fin de validité) et CAP10 (dérogations).

Toutes les dates du corpus sont en toutes lettres françaises (« 31 décembre 2026 »,
« 1er janvier 2024 ») : aucun format de segmentation.yaml (%d/%m/%Y) ne les couvre, d'où
un analyseur de date dédié (`_date_longue`), sans dépendance nouvelle.
"""

from __future__ import annotations

from datetime import date

from cohera.extraction.regles.validite import extraire_derogation, extraire_validite
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


# ---------------------------------------------------------------------------- CAP09


def test_jusquau_31_decembre_2026_est_une_fin_de_validite(d1) -> None:
    resultat = extraire_validite(d1.clause("8.3"))
    assert resultat["validite"].fin == date(2026, 12, 31)


def test_jusquau_en_debut_de_phrase_est_aussi_une_fin_de_validite(d1) -> None:
    resultat = extraire_validite(d1.clause("8.4"))
    assert resultat["validite"].fin == date(2024, 12, 31)


def test_depuis_le_est_un_debut_de_validite(d2) -> None:
    resultat = extraire_validite(d2.clause("8.3"))
    assert resultat["validite"].debut == date(2025, 1, 1)


def test_a_compter_du_en_debut_de_phrase_est_aussi_un_debut_de_validite(d2) -> None:
    resultat = extraire_validite(d2.clause("8.4"))
    assert resultat["validite"].debut == date(2025, 1, 1)


def test_valable_jusquau_dans_une_derogation_est_aussi_une_fin_de_validite(d1) -> None:
    """D1 §10.1 : la même échéance alimente à la fois `derogation.echeance` et
    `validite.fin` — deux vues d'un seul fait."""
    resultat = extraire_validite(d1.clause("10.1"))
    assert resultat["validite"].fin == date(2026, 12, 31)


def test_une_date_nue_sans_marqueur_ne_produit_aucune_validite() -> None:
    """« le 12 février 2026 » seul, sans jusqu'au/depuis/à compter du, n'est pas une
    borne de validité."""
    assert extraire_validite(_clause("Le document a été signé le 12 février 2026.")) == {}


def test_avant_le_ne_declenche_pas_un_debut_de_validite(d1) -> None:
    """D1 §8.3 : « avant le 1er janvier 2024 » qualifie une population d'autorisations,
    pas une période de validité de LA clause — seul `jusqu'au` doit être retenu."""
    resultat = extraire_validite(d1.clause("8.3"))
    assert resultat["validite"].debut is None


# ---------------------------------------------------------------------------- CAP10


def test_d1_10_1_derogation_complete(d1, jeu) -> None:
    derogation = extraire_derogation(d1.clause("10.1"), "D1", jeu)
    assert derogation is not None
    assert "6.4" in derogation.cible
    assert derogation.cible_document == "D2"
    assert derogation.cible_resolue is True
    assert derogation.justification is not None and "répétitive" in derogation.justification
    assert derogation.approbateur is not None and "Directeur de site" in derogation.approbateur
    assert derogation.date_approbation == date(2026, 2, 12)
    assert derogation.echeance == date(2026, 12, 31)


def test_d1_10_2_derogation_orpheline_sans_justification_ni_approbateur(d1, jeu) -> None:
    derogation = extraire_derogation(d1.clause("10.2"), "D1", jeu)
    assert derogation is not None
    assert "3.1" in derogation.cible
    assert derogation.cible_document is None
    assert derogation.cible_resolue is False
    assert derogation.justification is None
    assert derogation.approbateur is None
    assert derogation.echeance is None


def test_d1_10_3_derogation_resolue_mais_expiree(d1, jeu) -> None:
    derogation = extraire_derogation(d1.clause("10.3"), "D1", jeu)
    assert derogation is not None
    assert "5.1" in derogation.cible
    assert derogation.cible_document == "D1"
    assert derogation.cible_resolue is True
    assert derogation.echeance == date(2024, 12, 31)


def test_une_condition_ordinaire_n_est_pas_une_derogation(d1, jeu) -> None:
    """D1 §6.4 : « peut poursuivre... lorsque l'anomalie est qualifiée de mineure » a une
    condition, pas une dérogation — les deux ne doivent pas se confondre."""
    assert extraire_derogation(d1.clause("6.4"), "D1", jeu) is None


def test_aucune_clause_de_d2_ne_porte_de_derogation(d2, jeu) -> None:
    assert all(extraire_derogation(c, "D2", jeu) is None for c in d2.clauses)
