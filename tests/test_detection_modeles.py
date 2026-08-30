"""detection/modeles.py et la vérification de la preuve littérale.

Invariant #3 de `CLAUDE.md` : « aucun verdict sans preuve littérale — `preuve_a` et
`preuve_b` doivent être des sous-chaînes exactes de `texte_source`, vérifiées en Python
après l'appel ». Le contrôle vit dans un seul endroit, `cascade.sceller_preuves`, et sert
les trois détecteurs à la fois. Hors ligne.
"""

from __future__ import annotations

import pytest

from cohera.detection.cascade import sceller_preuves
from cohera.detection.modeles import Motif, TypeVerdict, Verdict, verifier_preuves

TEXTES = {
    "A": "Le Responsable QSE valide chaque fiche de contrôle sous 48 heures.",
    "B": "Le Référent sécurité est chargé de valider les fiches dans un délai de 5 jours ouvrés.",
}


def verdict(**champs) -> Verdict:
    defauts = dict(
        detecteur="A2", type=TypeVerdict.CONTRADICTION, motif=Motif.VALEURS_DIVERGENTES,
        clause_a="A", clause_b="B", preuve_a="48 heures", preuve_b="5 jours ouvrés",
        ferme=True,
    )
    return Verdict(**{**defauts, **champs})


def test_deux_preuves_litterales_se_verifient() -> None:
    assert verifier_preuves(verdict(), TEXTES)


def test_une_preuve_reformulee_ne_se_verifie_pas() -> None:
    """« 48h » n'apparaît pas dans le texte, qui écrit « 48 heures ». Une paraphrase, même
    juste, n'est pas une preuve."""
    assert not verifier_preuves(verdict(preuve_a="48h"), TEXTES)


def test_une_preuve_prise_dans_la_mauvaise_clause_ne_se_verifie_pas() -> None:
    """Le contrôle est par côté : `preuve_a` doit se trouver dans le texte de `clause_a`,
    pas n'importe où dans le corpus."""
    assert not verifier_preuves(verdict(preuve_a="5 jours ouvrés"), TEXTES)


# ------------------------------------------------------------------- le scellement


def test_un_verdict_ferme_et_prouve_reste_ferme() -> None:
    assert sceller_preuves(verdict(), TEXTES).ferme


@pytest.mark.parametrize(
    "champs, raison",
    [
        ({"preuve_a": None}, "preuve absente d'un côté"),
        ({"preuve_b": None}, "preuve absente de l'autre"),
        ({"preuve_a": "quarante-huit heures"}, "preuve qui ne se vérifie pas"),
    ],
)
def test_un_verdict_sans_preuve_litterale_escalade(champs: dict, raison: str) -> None:
    """**Une escalade, pas un rejet.** Le verdict garde son type et son explication ; il
    cesse seulement d'affirmer. Une preuve absente est un cas légitime : A1 pose
    `modalite_surface = None` quand le marqueur déontique n'apparaît que dans
    `texte_autonome`, ce qui est le cas des clauses issues d'une liste à chapeau (CAP02)."""
    scelle = sceller_preuves(verdict(**champs), TEXTES)
    assert not scelle.ferme, raison
    assert scelle.motif is Motif.PREUVE_LITTERALE_ABSENTE
    assert scelle.type is TypeVerdict.CONTRADICTION, "le verdict n'est pas effacé"


def test_une_anomalie_mono_clause_n_exige_qu_une_seule_preuve() -> None:
    """A5 sur une clause seule (I09, I10) n'a pas de `clause_b` : lui réclamer une seconde
    preuve la ferait escalader à tort."""
    mono = verdict(clause_b=None, preuve_b=None, motif=Motif.REFERENCE_CASSEE,
                   preuve_a="fiche de contrôle")
    assert sceller_preuves(mono, TEXTES).ferme


def test_un_verdict_deja_non_ferme_n_est_pas_requalifie() -> None:
    """Le scellement ne réécrit pas le motif d'une escalade déjà décidée en amont : on
    perdrait la raison réelle — objets sans recouvrement, grandeur imprécise — au profit
    d'une raison générique."""
    escalade = verdict(ferme=False, motif=Motif.OBJETS_SANS_RECOUVREMENT, preuve_a=None)
    assert sceller_preuves(escalade, TEXTES).motif is Motif.OBJETS_SANS_RECOUVREMENT


# ---------------------------------------------------------------- est_constatation


@pytest.mark.parametrize(
    "champs, attendu, pourquoi",
    [
        ({}, True, "contradiction ferme"),
        ({"ferme": False}, False, "escalade"),
        ({"type": TypeVerdict.SPECIALISATION}, False, "compatible, c'est N01"),
        ({"type": TypeVerdict.AUCUNE}, False, "rien à dire"),
        ({"type": TypeVerdict.DIVERGENCE_PERSPECTIVE}, True, "ferme, donc affirmé"),
    ],
)
def test_ce_qui_compte_comme_constatation(champs: dict, attendu: bool, pourquoi: str) -> None:
    """C'est ce compte, et lui seul, qui entre au dénominateur de la précision. Une
    spécialisation n'est pas une constatation : N01 serait sinon un faux positif."""
    assert verdict(**champs).est_constatation is attendu, pourquoi


# ═══════════════════════ le garde-fou du juge : quel texte fait foi (J9)
#
# Le prompt de l'étage C affiche `texte_autonome` (juge_llm._bloc_clause) et vérifiait ses
# citations contre `texte_source` : 3 des 7 verdicts annulés du J8 tombaient pour cet écart
# et non pour une hallucination. Ce que la correction accepte, et surtout ce qu'elle
# continue de rejeter, est figé ici.

#: Le texte de travail : le chapeau de liste a été redistribué, l'anaphore résolue. C'est
#: ce que le juge lit — et « L'Animateur QSE » n'apparaît pas dans `texte_source`.
AUTONOMES = {
    "A": "L'Animateur QSE valide chaque fiche de contrôle sous 48 heures.",
    "B": "Le Référent sécurité est chargé de valider les fiches dans un délai de 5 jours ouvrés.",
}


def test_une_citation_du_texte_autonome_est_acceptee() -> None:
    """Test POSITIF de la correction : le juge cite ce qu'on lui a montré.

    « L'Animateur QSE » ne figure que dans `texte_autonome`. Le refuser reviendrait à
    reprocher au modèle de ne pas citer un texte qu'il n'a jamais vu.
    """
    citation = "L'Animateur QSE valide chaque fiche"
    assert not verifier_preuves(verdict(preuve_a=citation), TEXTES)
    assert verifier_preuves(verdict(preuve_a=citation), TEXTES, AUTONOMES)


def test_l_apostrophe_typographique_ne_fait_pas_echouer_une_citation() -> None:
    """`texte_source` est tranché dans le texte d'origine, apostrophes courbes comprises ;
    `texte_autonome` est normalisé. Une citation ne doit pas tomber sur « ’ » contre « ' ».
    """
    textes = {"A": "L\u2019Animateur QSE valide la fiche.", "B": TEXTES["B"]}
    assert verifier_preuves(
        verdict(preuve_a="L'Animateur QSE valide la fiche."), textes
    )


def test_une_citation_empruntee_a_l_autre_clause_reste_rejetee() -> None:
    """⭐ Test NÉGATIF n°1 : la tolérance porte sur le TEXTE recevable, pas sur le côté.

    Élargir à `texte_autonome` ne doit pas revenir à accepter n'importe quelle phrase du
    corpus : c'est l'un des deux motifs des 4 annulations qui subsistent.
    """
    citation = "dans un délai de 5 jours ouvrés"
    assert not verifier_preuves(verdict(preuve_a=citation), TEXTES, AUTONOMES)


def test_une_citation_de_l_entete_du_prompt_reste_rejetee() -> None:
    """⭐ Test NÉGATIF n°2 : le juge qui recopie l'en-tête du prompt n'a rien prouvé.

    « D1 · niveau 3 · §8.1 » est fabriqué par `juge_llm._bloc_clause`, il n'appartient à
    aucun des deux textes de la clause. C'est le second motif des annulations restantes.
    """
    citation = "D1 · niveau 3 · §8.1 8. FORMATION ET HABILITATION"
    assert not verifier_preuves(verdict(preuve_a=citation), TEXTES, AUTONOMES)


def test_une_paraphrase_reste_rejetee_meme_avec_le_texte_autonome() -> None:
    """Test NÉGATIF n°3 : la reformulation était rejetée, elle le reste. La correction
    ajoute un texte recevable, elle n'assouplit pas la littéralité."""
    assert not verifier_preuves(verdict(preuve_a="48h"), TEXTES, AUTONOMES)
