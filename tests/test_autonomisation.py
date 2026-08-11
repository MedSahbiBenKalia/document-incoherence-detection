"""Autonomisation des anaphores, par règle et sans LLM.

Le NLI et le juge LLM voient une paire **hors de son document**. « Il est archivé pendant
3 ans. » y est inexploitable : ni sujet, ni objet, rien à comparer. CAP01 en fait la
condition de I03.

On ne réécrit que ce qui en a besoin — le test négatif compte donc autant que le positif :
une réécriture systématique introduirait des sujets faux partout.
"""

from __future__ import annotations

import pytest

from cohera.ingestion.autonomisation import besoin_autonomisation
from cohera.ingestion.modeles import Segmentation
from cohera.ingestion.phrases import analyseur, decouper_en_phrases


# ------------------------------------------------------------------ CAP01 : le cas pilote


def test_le_pronom_de_d1_9_2_est_remplace_par_son_antecedent(d1: Segmentation) -> None:
    """CAP01 : « Il est archivé pendant 3 ans. » doit devenir « Le registre de contrôle
    des EPI est archivé pendant 3 ans. »"""
    clause = d1.clause("9.2")

    assert clause.texte_source == "Il est archivé pendant 3 ans."
    assert "registre de contrôle des EPI" in clause.texte_autonome
    assert clause.texte_autonome.endswith("est archivé pendant 3 ans.")
    assert clause.autonomise is True


def test_l_antecedent_vient_de_la_clause_precedente(d1: Segmentation) -> None:
    """Il est pris dans 9.1, dont le sujet est « Le registre de contrôle des EPI »."""
    assert d1.clause("9.1").texte_source.startswith("Le registre de contrôle des EPI")
    assert d1.clause("9.2").texte_autonome.startswith("Le registre de contrôle des EPI")


def test_la_preuve_reste_litterale_apres_reecriture(d1: Segmentation) -> None:
    """La réécriture ne touche jamais `texte_source` : c'est lui qu'on citera en preuve."""
    clause = d1.clause("9.2")
    origine = d1.document.texte_origine
    assert origine[clause.debut : clause.fin] == clause.texte_source
    assert clause.texte_source != clause.texte_autonome


# -------------------------------------------------------------- les autres anaphores


@pytest.mark.parametrize(
    ("ref", "attendu"),
    [
        ("1.2", "La présente procédure"),
        ("2.2", "La présente procédure"),
    ],
)
def test_les_elle_de_d1_sont_resolus(d1: Segmentation, ref: str, attendu: str) -> None:
    clause = d1.clause(ref)
    assert clause.texte_autonome.startswith(attendu)
    assert clause.autonomise is True


def test_le_elle_de_d2_2_2_est_resolu(d2: Segmentation) -> None:
    clause = d2.clause("2.2")
    assert clause.texte_source.startswith("Elle couvre")
    assert clause.texte_autonome.startswith("La politique sécurité")


# -------------------------------------- le négatif : on ne réécrit pas ce qui va bien


@pytest.mark.parametrize("ref", ["5.1", "5.4", "7.1", "4.2", "10.2"])
def test_une_clause_deja_autonome_n_est_pas_reecrite(d1: Segmentation, ref: str) -> None:
    clause = d1.clause(ref)
    assert clause.autonomise is False
    assert clause.texte_autonome == clause.texte_source


def test_l_autonomisation_reste_l_exception(d1: Segmentation, d2: Segmentation) -> None:
    """architecture.md §3.3 annonce 15–25 % des clauses. Au-delà, c'est que le détecteur
    d'anaphore mord sur des clauses saines."""
    toutes = d1.clauses + d2.clauses
    proportion = sum(c.autonomise for c in toutes) / len(toutes)
    assert 0 < proportion <= 0.25


@pytest.mark.parametrize(
    "texte",
    [
        "Le contrôle des EPI doit être renouvelé tous les trimestres.",
        "Les harnais antichute font l'objet d'une vérification annuelle.",
        "En zone A, le contrôle visuel des EPI est réalisé avant chaque prise de poste.",
    ],
)
def test_une_phrase_avec_sujet_explicite_n_a_pas_besoin_d_autonomisation(texte: str) -> None:
    assert not besoin_autonomisation(texte, analyseur()(texte))


@pytest.mark.parametrize(
    "texte",
    [
        "Il est archivé pendant 3 ans.",
        "Elle s'applique à l'ensemble du personnel du site.",
        "Ce dernier valide la fiche sous 48 heures.",
    ],
)
def test_une_phrase_anaphorique_est_detectee(texte: str) -> None:
    assert besoin_autonomisation(texte, analyseur()(texte))


# ------------------------------------------ le piège spaCy : les codes documentaires


@pytest.mark.parametrize(
    ("texte", "phrases"),
    [
        ("Par dérogation à la procédure PR-QSE-02 § 3.1, le délai est porté à 15 jours.", 1),
        ("Par dérogation au § 6.4 de la politique POL-SEC-01, les interventions sont dispensées.", 1),
        ("Le contrôle est fait. Le registre est tenu à jour.", 2),
    ],
)
def test_les_codes_documentaires_ne_coupent_pas_la_phrase(texte: str, phrases: int) -> None:
    """Sans le composant `frontieres_qhse`, le parser insère une frontière avant le tiret
    de « PR-QSE-02 » : la clause 10.2 partirait en trois morceaux."""
    assert len(decouper_en_phrases(texte)) == phrases


@pytest.mark.parametrize(
    "texte",
    [
        "Elle intègre les dispositions de l'article R.4321-1 du Code du travail.",
        "La présente procédure est conforme à la norme ISO 45001:2018.",
        "Les modalités de retrait sont décrites au § 12.3.",
        "Le port de protections auditives est obligatoire au-delà de 85 dB(A).",
    ],
)
def test_les_abreviations_et_decimales_ne_coupent_pas_la_phrase(texte: str) -> None:
    assert len(decouper_en_phrases(texte)) == 1
