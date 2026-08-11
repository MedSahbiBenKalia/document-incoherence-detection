"""Chargement typé des configurations du J2 (cohera/extraction/config.py), contre les
vrais fichiers `config/registre_grandeurs.yaml` et `config/lexique_qhse.yaml`."""

from __future__ import annotations

from cohera.extraction.config import charger_lexique_extraction, charger_registre_grandeurs
from cohera.extraction.frames import Monotonie


def test_le_registre_reel_charge_exactement_dix_roles() -> None:
    registre = charger_registre_grandeurs()
    assert len(registre.grandeurs) == 10


def test_chaque_role_du_registre_reel_porte_une_monotonie() -> None:
    registre = charger_registre_grandeurs()
    assert all(role.monotonie is not None for role in registre.grandeurs.values())


def test_tolerance_est_desormais_un_pourcentage() -> None:
    """Coquille corrigée dans architecture.md §4.3 : ±5 % est un pourcentage, pas
    SANS_UNITE."""
    registre = charger_registre_grandeurs()
    assert registre.grandeurs["tolerance"].dimension.value == "POURCENTAGE"


def test_seuil_declenchement_est_plus_grand_est_plus_strict() -> None:
    registre = charger_registre_grandeurs()
    assert registre.grandeurs["seuil_declenchement"].monotonie is Monotonie.PLUS_GRAND


def test_le_lexique_reel_charge_sans_lever() -> None:
    lexique = charger_lexique_extraction()
    assert len(lexique.qualification.marqueurs_deontiques) >= 30
    assert "Responsable QSE" in lexique.gazetteer_roles
    assert len(lexique.grandeurs.periodicites) >= 7
    assert lexique.grandeurs.periodicites["bimestriel"].ambigu is True
    assert lexique.grandeurs.periodicites["trimestriel"].ambigu is False


def test_le_lexique_ignore_les_sections_j3_non_typees() -> None:
    """`alias`/`liste_noire`/`seuils` restent dans le YAML (J3) : la validation ne doit
    pas s'en formaliser (extra="ignore")."""
    lexique = charger_lexique_extraction()
    assert not hasattr(lexique, "alias")
