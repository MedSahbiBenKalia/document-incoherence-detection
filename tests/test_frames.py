"""Forme de la Clause Frame (cohera/extraction/frames.py) : construction, défauts,
énumérations fermées."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cohera.extraction.frames import (
    ClauseFrame,
    Condition,
    Derogation,
    Dimension,
    Grandeur,
    Modalite,
    Monotonie,
    Operateur,
    RegistreGrandeurs,
    RoleGrandeur,
    StatutGrandeur,
    TypeCondition,
)


def test_une_clause_frame_minimale_ne_pose_que_l_identifiant() -> None:
    frame = ClauseFrame(clause_id="D1::S5::C01")
    assert frame.modalite is None
    assert frame.quantites == []
    assert frame.conditions == []
    assert frame.references == []
    assert frame.derogation is None
    assert frame.confiance_extraction == 1.0
    assert frame.source_extraction == {}


def test_une_grandeur_porte_bien_role_dimension_valeur_si_et_monotonie() -> None:
    grandeur = Grandeur(
        role="delai",
        dimension=Dimension.TEMPS,
        valeur=48,
        unite="heures",
        valeur_si=172800,
        surface="sous 48 heures",
        monotonie=Monotonie.PLUS_PETIT,
    )
    assert grandeur.statut is StatutGrandeur.NORMAL
    assert grandeur.operateur is Operateur.EGAL


def test_une_grandeur_ambigue_peut_porter_une_valeur_si_nulle() -> None:
    grandeur = Grandeur(
        role="periodicite",
        dimension=Dimension.TEMPS_PERIODE,
        valeur=0,
        unite="",
        valeur_si=None,
        surface="bimestriel",
        monotonie=Monotonie.PLUS_PETIT,
        statut=StatutGrandeur.AMBIGU,
    )
    assert grandeur.valeur_si is None


def test_une_condition_seuil_porte_une_valeur_numerique_optionnelle() -> None:
    condition = Condition(
        surface="dépasse 50 km/h", type=TypeCondition.SEUIL, operateur=">", valeur=50
    )
    assert condition.valeur == 50


def test_une_derogation_complete_porte_tous_ses_champs() -> None:
    from datetime import date

    derogation = Derogation(
        cible="§ 6.4 de la politique POL-SEC-01",
        cible_document="D2",
        cible_resolue=True,
        justification="motivée par la nature répétitive des opérations",
        approbateur="Directeur de site",
        date_approbation=date(2026, 2, 12),
        echeance=date(2026, 12, 31),
    )
    assert derogation.cible_resolue is True


def test_une_derogation_orpheline_n_a_que_la_cible_non_resolue() -> None:
    derogation = Derogation(cible="§ 3.1 de PR-QSE-02", cible_resolue=False)
    assert derogation.cible_document is None
    assert derogation.justification is None


def test_modalite_est_une_enumeration_fermee() -> None:
    with pytest.raises(ValueError):
        Modalite("PEUT_ETRE")


def test_une_grandeur_sans_monotonie_fait_echouer_la_validation_du_registre() -> None:
    """.claude/rules/extraction.md : la contrainte porte sur le CHARGEMENT de la
    configuration, pas seulement sur l'extraction d'une clause."""
    with pytest.raises(ValidationError):
        RegistreGrandeurs.model_validate({"grandeurs": {"delai": {"dimension": "TEMPS"}}})


def test_un_role_avec_monotonie_valide_normalement() -> None:
    registre = RegistreGrandeurs.model_validate(
        {"grandeurs": {"delai": {"dimension": "TEMPS", "monotonie": "PLUS_PETIT"}}}
    )
    assert registre.grandeurs["delai"].monotonie is Monotonie.PLUS_PETIT


def test_un_role_a_dimension_nulle_est_accepte_selon_grandeur() -> None:
    role = RoleGrandeur.model_validate({"monotonie": "PLUS_GRAND"})
    assert role.dimension is None
