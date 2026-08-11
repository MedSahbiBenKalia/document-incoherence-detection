"""regles/references.py — renvois internes/croisés, citations de normes et d'exigences.

Critères (docs/plan-1-semaine.md §J2) : D1 §7.5 -> § 12.3 marqué non résolu ; D2 §6.3 ->
§ 11.2 de PR-QSE-04 marqué non résolu (résolution cherchant dans D1) ; « une tolérance de
4,3 % » ne produit aucune référence.
"""

from __future__ import annotations

from cohera.extraction.frames import TypeReference
from cohera.extraction.regles.references import extraire_references
from cohera.ingestion.modeles import Clause


def _clause(texte: str) -> Clause:
    return Clause(
        clause_id="TEST::S0::C01",
        doc_id="D1",
        ref="0.1",
        ordre=1,
        texte_source=texte,
        texte_autonome=texte,
        offset=(0, len(texte)),
    )


def test_iso_45001_est_une_norme_avec_sa_version(d1, jeu) -> None:
    refs = extraire_references(d1.clause("2.1"), "D1", jeu)
    assert len(refs) == 1
    assert refs[0].type is TypeReference.NORME
    assert refs[0].cible == "ISO 45001"
    assert refs[0].version == "2018"
    assert refs[0].resolu is None  # pas de registre_normes.yaml en J2 : None, jamais False


def test_ohsas_18001_est_une_norme_sans_version(d2, jeu) -> None:
    refs = extraire_references(d2.clause("10.1"), "D2", jeu)
    assert len(refs) == 1
    assert refs[0].type is TypeReference.NORME
    assert refs[0].cible == "OHSAS 18001"
    assert refs[0].resolu is None


def test_l_article_r_4321_1_est_une_exigence_avec_sa_source(d1, jeu) -> None:
    refs = extraire_references(d1.clause("2.2"), "D1", jeu)
    assert len(refs) == 1
    assert refs[0].type is TypeReference.EXIGENCE
    assert "4321-1" in refs[0].cible
    assert refs[0].source == "Code du travail"
    assert refs[0].resolu is None


def test_d1_7_5_reference_au_paragraphe_12_3_est_marquee_non_resolue(d1, jeu) -> None:
    """D1 n'a que 10 sections : § 12.3 n'existe pas."""
    refs = extraire_references(d1.clause("7.5"), "D1", jeu)
    assert len(refs) == 1
    assert refs[0].type is TypeReference.INTERNE
    assert refs[0].cible == "§ 12.3"
    assert refs[0].document_cible == "D1"
    assert refs[0].resolu is False


def test_d2_6_3_renvoi_croise_vers_pr_qse_04_est_marque_non_resolu(d2, jeu) -> None:
    """La cible du renvoi est D1 (via le code PR-QSE-04), et D1 n'a pas de § 11."""
    refs = extraire_references(d2.clause("6.3"), "D2", jeu)
    assert len(refs) == 1
    assert refs[0].document_cible == "D1"
    assert refs[0].resolu is False


def test_d1_10_1_derogation_vers_pol_sec_01_6_4_est_resolue(d1, jeu) -> None:
    """Renvoi croisé vers D2, dont le § 6.4 existe réellement."""
    refs = extraire_references(d1.clause("10.1"), "D1", jeu)
    assert len(refs) == 1
    assert refs[0].document_cible == "D2"
    assert refs[0].resolu is True


def test_d1_10_2_vers_pr_qse_02_est_orpheline(d1, jeu) -> None:
    """PR-QSE-02 n'existe nulle part dans ce corpus à deux documents."""
    refs = extraire_references(d1.clause("10.2"), "D1", jeu)
    assert len(refs) == 1
    assert refs[0].document_cible is None
    assert refs[0].resolu is False


def test_d1_10_3_vers_la_presente_procedure_5_1_est_resolue(d1, jeu) -> None:
    """Renvoi vers soi-même (« de la présente procédure »), et D1 § 5.1 existe."""
    refs = extraire_references(d1.clause("10.3"), "D1", jeu)
    assert len(refs) == 1
    assert refs[0].document_cible == "D1"
    assert refs[0].resolu is True


def test_une_tolerance_en_pourcentage_ne_produit_aucune_reference(jeu) -> None:
    """« 4,3 % » n'est ni un § ni un code documentaire ni une norme : aucun motif de
    motifs_reference ne peut s'y accrocher."""
    assert extraire_references(_clause("Une tolérance de 4,3 % est appliquée."), "D1", jeu) == []


def test_une_phrase_sans_aucun_motif_ne_produit_aucune_reference(jeu) -> None:
    assert extraire_references(_clause("Le contrôle est réalisé chaque trimestre."), "D1", jeu) == []
