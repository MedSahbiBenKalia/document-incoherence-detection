"""Criticité et arbitrage hiérarchique — architecture.md §8.3.

    criticite = w_type x w_gravite x w_confiance x w_portee x w_hierarchie

La criticité **ordonne** le rapport, elle ne filtre rien. Ces tests le vérifient
explicitement : aucune constatation ne doit pouvoir tomber à zéro et devenir invisible.

Deux points mesurés au J7 que ces tests figent :

* l'étage C rend ses constatations **sans gravité** (7 sur 18 en profil local) ; la gravité
  est alors déduite du type de taxonomie, jamais inventée ;
* `w_portee` est **neutre**, faute de portée effective reportée sur la constatation. C'est
  une limite documentée dans `config/restitution.yaml`, et un test la fige — un commentaire
  seul ne suffirait pas.
"""

from __future__ import annotations

import pytest

from cohera.consolidation import criticite as module
from cohera.restitution.rapport_json import Constatation, CoteClause

#: Les niveaux du corpus fixtures : D2 est la politique (1), D1 la procédure qui la décline (3).
NIVEAUX = {"D1": 3, "D2": 1}


def constatation(
    type_: str = "NUMERIQUE",
    *,
    gravite: str = "ELEVEE",
    confiance: float = 0.95,
    plus_permissive: str = "",
    cite_norme_externe: bool = False,
    doc_a: str = "D1",
    doc_b: str | None = "D2",
) -> Constatation:
    return Constatation(
        id="T-001",
        type=type_,
        gravite=gravite,
        confiance=confiance,
        detecteur="A2",
        etage="A",
        plus_permissive=plus_permissive,
        cite_norme_externe=cite_norme_externe,
        clause_a=CoteClause(doc=doc_a, ref="5.1", preuve="x"),
        clause_b=CoteClause(doc=doc_b, ref="5.1", preuve="y") if doc_b else None,
    )


# ------------------------------------------------------------------- la formule


def test_la_criticite_croit_avec_la_gravite():
    faible = module.criticite(constatation(gravite="FAIBLE"), NIVEAUX)
    moyenne = module.criticite(constatation(gravite="MOYENNE"), NIVEAUX)
    critique = module.criticite(constatation(gravite="CRITIQUE"), NIVEAUX)

    assert faible < moyenne < critique


def test_la_criticite_croit_avec_le_type_de_la_taxonomie():
    """Une contradiction causale prime une divergence terminologique, à gravité égale."""
    causal = module.criticite(constatation("CAUSAL", gravite="MOYENNE"), NIVEAUX)
    terminologique = module.criticite(constatation("TERMINOLOGIQUE", gravite="MOYENNE"), NIVEAUX)

    assert causal > terminologique


def test_la_criticite_croit_avec_la_confiance():
    sure = module.criticite(constatation(confiance=1.0), NIVEAUX)
    incertaine = module.criticite(constatation(confiance=0.7), NIVEAUX)

    assert sure > incertaine


def test_une_confiance_nulle_ne_fait_pas_disparaitre_la_constatation():
    """⭐ La criticité ORDONNE, elle ne filtre pas.

    Sans plancher, `w_confiance = 0` annulerait tout le produit : la constatation
    tomberait en fin de rapport avec une criticité de 0, indistinguable d'une absence.
    Une constatation peu sûre doit rester lisible, précisément parce qu'elle est peu sûre.
    """
    assert module.criticite(constatation(confiance=0.0), NIVEAUX) > 0.0


def test_un_type_inconnu_ne_casse_pas_le_calcul():
    """La taxonomie peut s'étendre sans rendre le rapport inordonnable."""
    assert module.criticite(constatation("TYPE_QUI_N_EXISTE_PAS"), NIVEAUX) > 0.0


# -------------------------------------------------- gravité absente : l'étage C


def test_la_gravite_manquante_est_deduite_du_type_jamais_laissee_vide():
    """Mesuré au J7 : l'étage C rend 7 constatations sur 18 sans gravité.

    Test POSITIF du repli : une constatation CAUSAL sans gravité doit se comporter comme
    une CRITIQUE, parce que c'est ce que dit `defaut_par_type`.
    """
    sans = constatation("CAUSAL", gravite="")
    avec = constatation("CAUSAL", gravite="CRITIQUE")

    assert module.gravite_effective(sans) == "CRITIQUE"
    assert module.criticite(sans, NIVEAUX) == module.criticite(avec, NIVEAUX)


def test_une_gravite_posee_par_un_detecteur_n_est_jamais_ecrasee():
    """Test NÉGATIF du repli : le défaut par type ne s'applique QU'À une gravité absente."""
    posee = constatation("CAUSAL", gravite="FAIBLE")

    assert module.gravite_effective(posee) == "FAIBLE"
    assert module.criticite(posee, NIVEAUX) < module.criticite(
        constatation("CAUSAL", gravite=""), NIVEAUX
    )


# --------------------------------------------------------- le facteur hiérarchique


def test_une_exigence_externe_double_la_criticite():
    """I08 : « ISO 45001:2018 » contre « OHSAS 18001 », retirée depuis mars 2021."""
    ordinaire = constatation("FACTUEL")
    externe = constatation("FACTUEL", cite_norme_externe=True)

    assert module.criticite(externe, NIVEAUX) == pytest.approx(
        2.0 * module.criticite(ordinaire, NIVEAUX)
    )


def test_l_inversion_hierarchique_majore_la_criticite():
    """D1 est la procédure (niveau 3) ; si c'est ELLE la plus permissive, il y a inversion."""
    inversee = constatation("NUMERIQUE", plus_permissive="A")  # A = D1, niveau 3
    droite = constatation("NUMERIQUE", plus_permissive="B")    # B = D2, niveau 1

    assert module.criticite(inversee, NIVEAUX) > module.criticite(droite, NIVEAUX)


def test_le_document_de_niveau_superieur_plus_permissif_n_est_pas_une_inversion():
    """Test NÉGATIF : une politique plus permissive que sa déclinaison est l'ordre NORMAL.

    C'est le sens même d'une déclinaison plus stricte (N01, `DECLINAISON_PLUS_STRICTE`) :
    le document dérivé resserre, il n'inverse pas.
    """
    assert not module.inversion_hierarchique(constatation(plus_permissive="B"), NIVEAUX)
    assert module.inversion_hierarchique(constatation(plus_permissive="A"), NIVEAUX)


def test_les_deux_multiplicateurs_ne_se_cumulent_pas():
    """§8.3 les présente en alternatives : le plus fort l'emporte."""
    les_deux = constatation("FACTUEL", plus_permissive="A", cite_norme_externe=True)
    externe_seule = constatation("FACTUEL", cite_norme_externe=True)

    assert module.criticite(les_deux, NIVEAUX) == module.criticite(externe_seule, NIVEAUX)


def test_sans_plus_permissive_il_n_y_a_pas_d_inversion():
    """Test NÉGATIF : la monotonie n'a désigné personne, on n'invente pas de fautif."""
    assert not module.inversion_hierarchique(constatation(plus_permissive=""), NIVEAUX)


# ------------------------------------------------------------------ l'arbitrage


def test_la_clause_fautive_est_celle_du_document_le_plus_permissif():
    """I13 : `label.json` désigne « D1 (niveau 3, plus permissif que le niveau 1) »."""
    constat = constatation("HIERARCHIQUE", plus_permissive="A")

    assert module.clause_fautive(constat, NIVEAUX) == "D1 §5.1"


def test_deux_documents_de_meme_niveau_exigent_un_arbitrage_humain():
    """§8.3 : « la constatation est marquée ARBITRAGE_REQUIS »."""
    constat = constatation(plus_permissive="A")

    assert module.clause_fautive(constat, {"D1": 2, "D2": 2}) == "ARBITRAGE_REQUIS"


def test_sans_monotonie_aucune_clause_n_est_designee_fautive():
    """Test NÉGATIF : ne rien dire vaut mieux qu'accuser au hasard."""
    assert module.clause_fautive(constatation(plus_permissive=""), NIVEAUX) == ""


def test_une_declinaison_plus_stricte_ne_designe_aucun_fautif():
    """⭐ Test NÉGATIF central de l'arbitrage — le cas d'I01 sur ce corpus.

    D1 (procédure, niveau 3) exige 48 h là où D2 (politique, niveau 1) accorde 5 jours : la
    clause la plus permissive est celle du document le plus HAUT dans la pyramide. C'est
    l'ordre normal d'une `DECLINAISON_PLUS_STRICTE`, et personne n'est fautif.

    La divergence reste une constatation — les valeurs diffèrent — mais §8.3 ne désigne un
    fautif que « du document de niveau inférieur SI elle est plus permissive ». Désigner
    quand même la politique reviendrait à lui reprocher que sa déclinaison soit plus
    exigeante qu'elle.
    """
    assert module.clause_fautive(constatation(plus_permissive="B"), NIVEAUX) == ""


def test_une_exigence_externe_designe_le_fautif_meme_sans_inversion():
    """I08 : « OHSAS 18001 » est portée par D2, le document de niveau 1.

    Aucune inversion hiérarchique ici — mais citer un référentiel retiré depuis mars 2021
    est fautif quelle que soit la place du document dans la pyramide. §8.3 : « celle qui
    contredit l'exigence externe sinon ».
    """
    constat = constatation("FACTUEL", plus_permissive="B", cite_norme_externe=True)

    assert module.clause_fautive(constat, NIVEAUX) == "D2 §5.1"


def test_sans_niveau_hierarchique_connu_aucun_fautif_n_est_designe():
    """Test NÉGATIF : un document dont on ignore le niveau ne permet aucun arbitrage."""
    assert module.clause_fautive(constatation(plus_permissive="A"), {}) == ""


def test_une_anomalie_mono_clause_designe_sa_propre_clause():
    """I09, I10 : il n'y a pas de second document à mettre en cause."""
    mono = constatation("FACTUEL", doc_b=None)

    assert module.clause_fautive(mono, NIVEAUX) == "D1 §5.1"


# ------------------------------------------------------- la limite, figée par un test


def test_le_facteur_de_portee_est_neutre_et_c_est_documente():
    """⚠️ Limite connue du J7, figée ici pour qu'elle ne se perde pas.

    `w_portee` vaut 1,0 pour toute constatation : la portée effective est calculée au J5
    mais n'est pas reportée sur la constatation, donc la restitution ne peut pas la lire.
    `config/restitution.yaml` le dit ; ce test l'exige. Le jour où quelqu'un branche la
    portée, ce test échoue et force la mise à jour du commentaire — un commentaire seul
    ne suffit pas à tenir une limite.
    """
    assert module.poids_de_portee(constatation()) == 1.0
    assert module.poids_de_portee(constatation("CAUSAL", gravite="CRITIQUE")) == 1.0


# ------------------------------------------------------------------- le tri du rapport


def test_ordonner_trie_par_criticite_decroissante():
    basse = constatation("TERMINOLOGIQUE", gravite="FAIBLE")
    haute = constatation("CAUSAL", gravite="CRITIQUE")

    ordonnees = module.ordonner([basse, haute], NIVEAUX)

    assert [c.type for c in ordonnees] == ["CAUSAL", "TERMINOLOGIQUE"]
    assert ordonnees[0].criticite > ordonnees[1].criticite


def test_ordonner_renseigne_criticite_et_clause_fautive():
    ordonnees = module.ordonner([constatation("HIERARCHIQUE", plus_permissive="A")], NIVEAUX)

    assert ordonnees[0].criticite > 0.0
    assert ordonnees[0].clause_fautive == "D1 §5.1"


def test_ordonner_ne_modifie_pas_la_liste_recue():
    origine = [constatation()]
    module.ordonner(origine, NIVEAUX)

    assert origine[0].criticite == 0.0


def test_l_arbitrage_reproduit_la_relation_hierarchique_de_la_verite_terrain(verite):
    """⭐ La règle de §8.3 doit retrouver le `relation_hierarchique` de `label.json`.

    Le test n'est pas circulaire : l'**entrée** (quelle clause la monotonie désigne comme la
    plus permissive) vient de la mesure du pipeline, l'**attendu** vient de `label.json`, et
    c'est la règle d'arbitrage qui fait le lien entre les deux.

    `plus_permissive` est repris de l'exécution du J7 en profil local, où A2 le pose depuis
    la monotonie du rôle (`registre_grandeurs.yaml`) :

        I01  D1 §4.2 « sous 48 heures »   / D2 §4.2 « 5 jours ouvrés »   -> B (D2, niveau 1)
        I02  D1 §5.1 « tous les trimestres » / D2 §5.1 « deux fois par an » -> B
        I13  D1 §7.1 « à plus de 3 m »    / D2 §7.1 « à plus de 2 m »    -> A (D1, niveau 3)
        I14  D1 §5.5 « au-delà de 85 dB » / D2 §5.5 « dépasse 80 dB »    -> A
        I15  D1 §8.2 « tous les 3 ans »   / D2 §8.2 « tous les 2 ans »   -> A

    Une `DECLINAISON_PLUS_STRICTE` ne doit désigner personne ; une `INVERSION_HIERARCHIQUE`
    doit désigner la clause du document de niveau inférieur — celle que `label.json` nomme
    explicitement pour I13 : « D1 (niveau 3, plus permissif que le niveau 1) ».
    """
    mesure = {"I01": "B", "I02": "B", "I13": "A", "I14": "A", "I15": "A"}
    attendu_par_relation = {"DECLINAISON_PLUS_STRICTE": "", "INVERSION_HIERARCHIQUE": "D1"}

    verifies = 0
    for entree in verite["incoherences"]:
        permissive = mesure.get(entree["id"])
        relation = entree.get("relation_hierarchique")
        if permissive is None or relation not in attendu_par_relation:
            continue

        constat = constatation(
            entree["type"],
            plus_permissive=permissive,
            doc_a=entree["clause_a"]["doc"],
            doc_b=entree["clause_b"]["doc"],
        )
        fautive = module.clause_fautive(constat, NIVEAUX)

        attendu = attendu_par_relation[relation]
        assert fautive.startswith(attendu) if attendu else fautive == "", (
            f"{entree['id']} ({relation}) : arbitrage « {fautive or '—'} »"
        )
        verifies += 1

    assert verifies == len(mesure), "toutes les incohérences mesurées doivent être couvertes"


def test_ordonner_ne_perd_aucune_constatation():
    """⭐ Le tri ORDONNE, il ne filtre pas — y compris les cas dégénérés."""
    lot = [
        constatation(confiance=0.0),
        constatation("TYPE_INCONNU", gravite=""),
        constatation(doc_b=None),
        constatation("CAUSAL", gravite="CRITIQUE"),
    ]

    assert len(module.ordonner(lot, NIVEAUX)) == len(lot)
    assert len(module.ordonner(lot, {})) == len(lot), "niveaux absents : on ordonne quand même"
