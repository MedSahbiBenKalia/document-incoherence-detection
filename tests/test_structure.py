"""Détection de structure : numérotation, titres, front-matter.

Le point sensible est la désambiguïsation `10.` (titre de section) contre `10.1` (clause),
et le fait qu'aucun motif ne puisse se déclencher en milieu de ligne — « décrites au
§ 12.3 » et « l'article R.4321-1 » contiennent des séquences chiffre-point qui, sans
l'ancre `^`, couperaient une clause en deux.
"""

from __future__ import annotations

from datetime import date

import pytest

from cohera import reglages
from cohera.ingestion.normalisation import lire_texte_origine
from cohera.ingestion.structure import (
    debut_du_corps,
    lire_entete,
    reference_de_clause,
    titre_de_section,
)

FIXTURES = reglages.racine_projet() / "corpus" / "fixtures"


@pytest.fixture(scope="module")
def texte_d1() -> str:
    return lire_texte_origine(FIXTURES / "file-1.txt")


# ------------------------------------------------------- clause contre titre de section


@pytest.mark.parametrize(
    ("ligne", "ref"),
    [
        ("1.1 La présente procédure définit les modalités.", "1.1"),
        ("4.2 Le Responsable QSE valide chaque fiche.", "4.2"),
        ("10.1 Par dérogation au § 6.4 de la politique POL-SEC-01.", "10.1"),
        ("10.3 Par dérogation au § 5.1 de la présente procédure.", "10.3"),
    ],
)
def test_un_paragraphe_numerote_est_reconnu(ligne: str, ref: str) -> None:
    trouve = reference_de_clause(ligne)
    assert trouve is not None
    assert trouve[0] == ref
    # Le second membre est le décalage du corps dans la ligne : le numéro n'entre pas
    # dans texte_source.
    assert ligne[trouve[1]].isupper() or ligne[trouve[1]].isalpha()


@pytest.mark.parametrize(
    ("ligne", "numero", "titre"),
    [
        ("1. OBJET ET DOMAINE D'APPLICATION", "1", "OBJET ET DOMAINE D'APPLICATION"),
        ("10. DÉROGATIONS", "10", "DÉROGATIONS"),
        ("9. ARCHIVAGE ET ENREGISTREMENTS", "9", "ARCHIVAGE ET ENREGISTREMENTS"),
    ],
)
def test_un_titre_de_section_est_reconnu(ligne: str, numero: str, titre: str) -> None:
    assert titre_de_section(ligne) == (numero, titre)


def test_dix_point_est_un_titre_et_dix_point_un_est_une_clause() -> None:
    """La confusion coûterait la section 10 entière : trois dérogations perdues."""
    assert reference_de_clause("10. DÉROGATIONS") is None
    assert titre_de_section("10. DÉROGATIONS") == ("10", "DÉROGATIONS")

    assert titre_de_section("10.1 Par dérogation au § 6.4.") is None
    assert reference_de_clause("10.1 Par dérogation au § 6.4.")[0] == "10.1"


# --------------------------------------------------- le négatif : aucune frontière en vol


@pytest.mark.parametrize(
    "ligne",
    [
        "Les modalités de retrait des EPI défectueux sont décrites au § 12.3.",
        "Elle intègre les dispositions de l'article R.4321-1 du Code du travail.",
        "La présente procédure est conforme à la norme ISO 45001:2018.",
        "Date d'application : 01/03/2024",
        "Le port de protections auditives est obligatoire au-delà de 85 dB(A).",
        "Les modalités figurent au § 11.2 de la procédure PR-QSE-04.",
        "Le présent document annule et remplace la version 2 du 15/06/2021.",
    ],
)
def test_une_sequence_chiffree_en_milieu_de_ligne_ne_coupe_rien(ligne: str) -> None:
    assert reference_de_clause(ligne) is None
    assert titre_de_section(ligne) is None


def test_les_references_trouvees_dans_d1_sont_exactement_celles_attendues(texte_d1: str) -> None:
    """Le filet de sécurité : on énumère, on ne se fie pas à un échantillon."""
    trouvees = [
        reference_de_clause(ligne)[0]
        for ligne in texte_d1.split("\n")
        if reference_de_clause(ligne)
    ]
    attendues = (
        ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "3.3"]
        + ["4.1", "4.2", "4.3", "4.4"]
        + [f"5.{i}" for i in range(1, 7)]
        + [f"6.{i}" for i in range(1, 6)]
        + [f"7.{i}" for i in range(1, 6)]
        + [f"8.{i}" for i in range(1, 5)]
        + ["9.1", "9.2", "9.3", "10.1", "10.2", "10.3"]
    )
    assert trouvees == attendues
    assert len(trouvees) == 37


# ------------------------------------------------------------------- le front-matter


def test_le_corps_commence_au_premier_titre_de_section(texte_d1: str) -> None:
    debut = debut_du_corps(texte_d1)
    assert texte_d1[debut:].startswith("1. OBJET ET DOMAINE D'APPLICATION")
    # Tout le bloc d'en-tête est en amont, « annule et remplace » compris.
    assert "annule et remplace" in texte_d1[:debut]


def test_l_entete_de_d1_est_lu_depuis_le_document(texte_d1: str, verite: dict) -> None:
    document = lire_entete("D1", "file-1.txt", texte_d1)
    attendu = next(d for d in verite["documents"] if d["id"] == "D1")

    assert document.code == attendu["code"]
    assert document.version == attendu["version"]
    assert document.type == attendu["type"]
    assert document.niveau_hierarchique == attendu["niveau_hierarchique"]
    assert document.date_application == date.fromisoformat(attendu["date_application"])
    assert document.site == "Radès"
    assert document.redacteur == "Service QSE"
    assert "CONTRÔLE DES ÉQUIPEMENTS" in document.titre


def test_l_entete_de_d2_est_lu_depuis_le_document(verite: dict) -> None:
    """POL-SEC-01 doit tomber dans « POL- » et non dans « PO- » : appariement par préfixe
    le plus long, sinon le niveau hiérarchique serait juste par accident."""
    texte = lire_texte_origine(FIXTURES / "file-2.txt")
    document = lire_entete("D2", "file-2.txt", texte)
    attendu = next(d for d in verite["documents"] if d["id"] == "D2")

    assert document.code == "POL-SEC-01" == attendu["code"]
    assert document.type == "POLITIQUE" == attendu["type"]
    assert document.niveau_hierarchique == 1 == attendu["niveau_hierarchique"]
    assert document.date_application == date.fromisoformat(attendu["date_application"])
    assert document.approbateur == "Direction générale"


def test_la_phrase_libre_du_front_matter_part_en_note_pas_en_clause(texte_d1: str) -> None:
    document = lire_entete("D1", "file-1.txt", texte_d1)
    assert any("annule et remplace" in note for note in document.notes)
