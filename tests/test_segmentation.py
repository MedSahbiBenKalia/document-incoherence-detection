"""Segmentation complète : les critères chiffrés du J1.

Les trois qui comptent :
  1. 41 clauses pour D1, 37 pour D2 ;
  2. `texte_origine[debut:fin] == texte_source` pour les 78 — le piège du jour ;
  3. les capacités CAP02 (listes), CAP03 (tableaux), CAP08 (phrase de cadrage).

Si un compte ne tombe pas, ce n'est ni le corpus ni `label.json` qu'on ajuste :
`cohera corpus verifier --jeu fixtures` sort le tableau et montre où est l'écart.
"""

from __future__ import annotations

import pytest

from cohera.ingestion.modeles import OrigineClause, Segmentation
from cohera.ingestion.phrases import qualifier

PHRASE_DE_CADRAGE = "Ce document est diffusé à l'ensemble des services par voie électronique."


# ------------------------------------------------------------------ critère n°1 : compte


def test_d1_produit_exactement_41_clauses(d1: Segmentation) -> None:
    assert len(d1.clauses) == 41


def test_d2_produit_exactement_37_clauses(d2: Segmentation) -> None:
    assert len(d2.clauses) == 37


def test_le_compte_par_document_correspond_a_la_verite_terrain(
    d1: Segmentation, d2: Segmentation, verite: dict
) -> None:
    attendu = {d["id"]: d["nb_clauses_attendu"] for d in verite["documents"]}
    assert len(d1.clauses) == attendu["D1"]
    assert len(d2.clauses) == attendu["D2"]


# ---------------------------------------------------- critère n°2 : offsets alignés


def test_les_offsets_de_d1_retombent_sur_le_texte_source(d1: Segmentation) -> None:
    assert d1.ecarts_offsets() == []


def test_les_offsets_de_d2_retombent_sur_le_texte_source(d2: Segmentation) -> None:
    assert d2.ecarts_offsets() == []


def test_chaque_clause_est_verifiee_une_par_une(d1: Segmentation, d2: Segmentation) -> None:
    """La même chose que ci-dessus, mais en nommant la clause fautive s'il y en a une."""
    for segmentation in (d1, d2):
        origine = segmentation.document.texte_origine
        for clause in segmentation.clauses:
            assert origine[clause.debut : clause.fin] == clause.texte_source, clause.clause_id


def test_aucun_texte_source_n_est_vide_ni_deborde(d1: Segmentation, d2: Segmentation) -> None:
    for segmentation in (d1, d2):
        taille = len(segmentation.document.texte_origine)
        for clause in segmentation.clauses:
            assert clause.texte_source.strip(), clause.clause_id
            assert 0 <= clause.debut < clause.fin <= taille, clause.clause_id


# ------------------------------------------------------- CAP08 : la phrase de cadrage


def test_la_phrase_de_cadrage_n_est_pas_une_clause(d1: Segmentation) -> None:
    """CAP08. Diffusion constatée : aucun marqueur déontique, aucune grandeur, aucune
    référence, aucun verbe définitionnel."""
    assert all(PHRASE_DE_CADRAGE not in c.texte_source for c in d1.clauses)


def test_la_phrase_de_cadrage_est_rattachee_en_contexte(d1: Segmentation) -> None:
    """Écartée, pas perdue : elle reste lisible à côté de la clause qui la précède."""
    contextes = [ligne for c in d1.clauses for ligne in c.contexte]
    assert any(PHRASE_DE_CADRAGE in ligne for ligne in contextes)
    assert any(PHRASE_DE_CADRAGE in ligne for ligne in d1.clause("1.2").contexte)


def test_la_qualification_accepte_un_enonce_normatif() -> None:
    """Le pendant positif du test CAP08 : la règle écarte, elle ne refuse pas tout."""
    assert qualifier("Le contrôle des EPI doit être renouvelé tous les trimestres.")
    assert qualifier("Le port du casque est obligatoire en zone A.")
    assert qualifier("On entend par « anomalie » tout écart constaté.")
    assert qualifier("Les modalités sont décrites au § 12.3.")


def test_la_qualification_ecarte_une_phrase_de_cadrage() -> None:
    assert not qualifier(PHRASE_DE_CADRAGE)


# ------------------------------------------------------------- CAP02 : listes à chapeau


def test_la_liste_de_d1_4_4_produit_trois_clauses(d1: Segmentation) -> None:
    items = d1.par_ref("4.4")
    assert len(items) == 3
    assert all(c.origine is OrigineClause.LISTE for c in items)


def test_chaque_item_de_liste_reprend_le_chapeau(d1: Segmentation) -> None:
    """CAP02. Sans redistribution, « planifier les contrôles » n'a ni sujet ni modalité :
    le J2 n'y verrait aucune obligation et aucun acteur."""
    for clause in d1.par_ref("4.4"):
        assert clause.texte_autonome.startswith("L'Animateur QSE doit")
        assert clause.chapeau == "L'Animateur QSE doit :"


def test_le_chapeau_de_liste_n_est_pas_une_clause_a_lui_seul(d1: Segmentation) -> None:
    assert all(c.texte_source.strip() != "L'Animateur QSE doit :" for c in d1.clauses)


def test_les_trois_items_sont_les_bons(d1: Segmentation) -> None:
    sources = [c.texte_source for c in d1.par_ref("4.4")]
    assert sources[0].startswith("planifier les contrôles périodiques")
    assert sources[1].startswith("tenir à jour le registre")
    assert sources[2].startswith("informer le chef d'atelier")


# ---------------------------------------------------------- CAP03 : blocs tabulaires


def test_le_tableau_de_d1_4_1_produit_trois_clauses(d1: Segmentation) -> None:
    lignes = d1.par_ref("4.1")
    assert len(lignes) == 3
    assert all(c.origine is OrigineClause.TABLEAU for c in lignes)


def test_l_en_tete_du_tableau_n_est_pas_une_clause(d1: Segmentation) -> None:
    """CAP03. « Activité | Réalisation | Approbation » donne les rôles, pas une exigence."""
    assert all("Réalisation" not in c.texte_source for c in d1.par_ref("4.1"))
    assert all(not c.texte_source.startswith("Activité") for c in d1.clauses)


def test_les_lignes_de_tableau_portent_les_roles_en_attributs(d1: Segmentation) -> None:
    approbation = d1.par_ref("4.1")[1]
    assert approbation.texte_source.startswith("Approbation du plan de prévention")
    assert approbation.attributs["Réalisation"] == "Animateur QSE"
    assert approbation.attributs["Approbation"] == "Responsable QSE"
    assert approbation.attributs["Activité"] == "Approbation du plan de prévention"


def test_le_chapeau_du_tableau_n_est_pas_une_clause(d1: Segmentation) -> None:
    assert all(
        "La répartition des responsabilités est la suivante" not in c.texte_source
        for c in d1.clauses
    )


# --------------------------------------------- les négatifs : pas de sur-détection


def test_le_corpus_ne_compte_que_trois_clauses_de_tableau(
    d1: Segmentation, d2: Segmentation
) -> None:
    """Un détecteur de tableau trop gourmand transformerait n'importe quelle phrase à
    tirets en matrice RACI."""
    toutes = d1.clauses + d2.clauses
    assert sum(c.origine is OrigineClause.TABLEAU for c in toutes) == 3


def test_le_corpus_ne_compte_que_trois_clauses_de_liste(
    d1: Segmentation, d2: Segmentation
) -> None:
    toutes = d1.clauses + d2.clauses
    assert sum(c.origine is OrigineClause.LISTE for c in toutes) == 3


def test_d2_n_a_ni_liste_ni_tableau(d2: Segmentation) -> None:
    assert all(c.origine is OrigineClause.TEXTE for c in d2.clauses)


# ------------------------------------------------- la règle du fragment (section 10)


def test_la_section_dix_produit_exactement_trois_clauses(d1: Segmentation) -> None:
    """Les dérogations 10.1 et 10.3 comptent deux phrases chacune, mais la seconde
    (« Dérogation motivée par… ») n'a pas de verbe fini : c'est un complément, pas un
    énoncé normatif autonome."""
    assert len(d1.par_section("10")) == 3


def test_la_derogation_10_1_couvre_ses_deux_phrases(d1: Segmentation) -> None:
    clause = d1.clause("10.1")
    assert clause.texte_source.startswith("Par dérogation au § 6.4")
    # La justification, l'approbateur et l'échéance restent dans la clause : le J-CAP10
    # en aura besoin sans avoir à recoller deux nœuds.
    assert "approuvée par le Directeur de site" in clause.texte_source
    assert clause.texte_source.rstrip().endswith("valable jusqu'au 31 décembre 2026.")


def test_la_derogation_10_3_couvre_ses_deux_phrases(d1: Segmentation) -> None:
    clause = d1.clause("10.3")
    assert clause.texte_source.startswith("Par dérogation au § 5.1")
    assert clause.texte_source.rstrip().endswith("Dérogation valable jusqu'au 31 décembre 2024.")


def test_la_derogation_10_2_reste_une_seule_clause(d1: Segmentation) -> None:
    """Celle-ci part en trois morceaux chez spaCy si « PR-QSE-02 » est coupé."""
    clause = d1.clause("10.2")
    assert "PR-QSE-02" in clause.texte_source
    assert clause.texte_source.rstrip().endswith("est porté à 15 jours.")


# ------------------------------------------------------------- cohérence d'ensemble


def test_les_identifiants_sont_uniques(d1: Segmentation, d2: Segmentation) -> None:
    ids = [c.clause_id for c in d1.clauses + d2.clauses]
    assert len(ids) == len(set(ids))


def test_l_ordre_est_strictement_croissant(d1: Segmentation, d2: Segmentation) -> None:
    for segmentation in (d1, d2):
        ordres = [c.ordre for c in segmentation.clauses]
        assert ordres == sorted(ordres)
        assert len(set(ordres)) == len(ordres)


def test_les_clauses_sont_dans_l_ordre_du_document(d1: Segmentation) -> None:
    debuts = [c.debut for c in d1.clauses]
    assert debuts == sorted(debuts)


def test_chaque_clause_porte_son_chemin_de_section(d1: Segmentation, d2: Segmentation) -> None:
    for segmentation in (d1, d2):
        for clause in segmentation.clauses:
            assert clause.section_path, clause.clause_id
            assert clause.section_path[0].startswith(clause.ref.split(".")[0] + ".")


def test_chaque_clause_porte_son_document_et_sa_reference(d1: Segmentation) -> None:
    """`(doc_id, ref)` est la clé sur laquelle le harnais d'évaluation apparie avec
    `label.json`. Sans elle, rien n'est mesurable au J4."""
    assert all(c.doc_id == "D1" for c in d1.clauses)
    assert d1.clause("4.2").libelle == "D1 §4.2"


def test_les_references_de_la_verite_terrain_existent_toutes(
    d1: Segmentation, d2: Segmentation, verite: dict
) -> None:
    """Chaque clause citée par `label.json` doit avoir été produite par la segmentation,
    sinon le J4 ne pourra pas l'apparier."""
    par_doc = {"D1": d1, "D2": d2}
    manquantes = []
    entrees = verite["incoherences"] + verite["contre_exemples"] + verite["limites_connues"]
    for entree in entrees:
        for cote in ("clause_a", "clause_b"):
            reference = entree.get(cote)
            if not reference:
                continue
            segmentation = par_doc[reference["doc"]]
            if not segmentation.par_ref(reference["ref"]):
                manquantes.append(f"{entree['id']} → {reference['doc']} §{reference['ref']}")
    assert manquantes == []


@pytest.mark.parametrize("ref", ["9.2", "5.1", "7.4", "10.2"])
def test_une_clause_porte_une_empreinte_stable(d1: Segmentation, ref: str) -> None:
    clause = d1.clause(ref)
    assert len(clause.hash) == 16
