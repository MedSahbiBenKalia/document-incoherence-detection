"""graphe/alias.py — le pont inter-documents.

Critères du J3 (docs/plan-1-semaine.md §J3) :
  - les alias attendus existent, avec la bonne méthode ;
  - « la liste noire tient » : casque≢gants, anomalie≢écart, chef d'atelier≢hiérarchie ;
  - `zone_grise.jsonl` contient 2 paires.

⚠️ **Deux critères sont ROUGES, et les tests le disent au lieu de le masquer.** Le calibrage
mesuré au J3 est consigné dans `config/lexique_qhse.yaml` et au Journal de `CLAUDE.md` :

1. « Responsable QSE » ~ « Référent sécurité » et « contrôle » ~ « vérification » étaient
   attendus en VECTEUR à ~0,88 et ~0,91. Mesuré 0,546 et 0,624 avec bge-m3, 0,450 et 0,561
   avec Solon. Deux paires de la liste noire scorent aussi haut : aucun seuil ne sépare les
   deux listes. Ces alias sont donc portés par le LEXIQUE, et les tests assertent LEXIQUE —
   la méthode réellement obtenue, pas celle qu'on aurait aimé afficher.
2. La zone grise ne remonte pas les 2 paires attendues. Test en `xfail(strict=True)` : il
   échouera bruyamment le jour où le comportement changera, dans un sens comme dans l'autre.

Le fichier applique la règle du dépôt « un détecteur = un test positif ET un test négatif » :
chaque section a sa contrepartie.
"""

from __future__ import annotations

import pytest

from cohera.graphe.alias import Methode, UnionFind, ecrire_zone_grise, lire_zone_grise

# --------------------------------------------------------------------- liste blanche


@pytest.mark.parametrize(
    ("gauche", "droite", "methode_attendue"),
    [
        # Pluriel absorbé par la lemmatisation — le seul cas que la forme de surface ne
        # sait pas traiter (D1 §4.2 « chaque fiche de contrôle » / D2 §4.2 « les fiches »).
        ("fiche de contrôle", "fiches de contrôle", Methode.EXACT),
        # Acronyme et forme développée : le vectoriel les place à 0,43, seul le lexique
        # peut les rapprocher. Alias requis par I02.
        ("EPI", "équipements de protection", Methode.LEXIQUE),
        # Attendus en VECTEUR par le plan ; portés par le lexique, cf. l'en-tête.
        ("Responsable QSE", "Référent sécurité", Methode.LEXIQUE),
        ("contrôle", "vérification", Methode.LEXIQUE),
    ],
)
def test_un_alias_attendu_existe_avec_sa_methode(pont, gauche, droite, methode_attendue) -> None:
    arete = pont.alias_de(gauche, droite)
    assert arete is not None, f"aucune arête ALIAS_DE entre {gauche!r} et {droite!r}"
    assert arete.methode is methode_attendue


@pytest.mark.parametrize("libelle", ["harnais antichute", "zone à risque"])
def test_un_libelle_identique_dans_les_deux_documents_est_un_seul_concept(
    pont, vocabulaire, libelle
) -> None:
    """Le plan les attendait en `ALIAS_DE {EXACT}`. Ils sont mieux que cela : **un seul
    nœud `Concept`**, mentionné par les clauses des deux documents.

    Il n'y a pas d'arête parce qu'il n'y a rien à relier — `concept_id` est global
    (architecture.md §5.2), donc deux occurrences du même libellé sont le même nœud. Le pont
    est établi, et il l'est plus fortement qu'avec une arête révisable.
    """
    concept = vocabulaire.par_libelle(libelle)
    assert concept is not None, f"{libelle!r} n'a pas été extrait comme concept"
    assert sorted(set(concept.doc_ids)) == ["D1", "D2"]


def test_les_alias_vectoriels_restent_au_dessus_du_seuil(pont) -> None:
    """Aucune arête VECTEUR ne doit exister sous le seuil configuré."""
    from cohera.graphe.config_alias import charger_config_alias

    seuil = charger_config_alias().seuils.alias_vecteur
    for arete in pont.aretes:
        if arete.methode is Methode.VECTEUR:
            assert arete.score >= seuil, f"{arete.libelle_a}/{arete.libelle_b} sous le seuil"


def test_l_alias_de_lemmatisation_requis_par_i15_existe(pont) -> None:
    """`label.json` I15 exige « recyclage = recycler (lemmatisation) ».

    Contre-exemple utile à ma propre conclusion : l'étage vectoriel n'est pas inutile sur ce
    corpus — il ne débloque simplement pas les deux paires que le plan visait.
    """
    arete = pont.alias_de("recycler", "recyclage")
    assert arete is not None, "I15 attend l'alias recyclage = recycler"


# ----------------------------------------------------------------------- liste noire


@pytest.mark.parametrize(
    ("gauche", "droite", "origine"),
    [
        ("casque", "gants", "N02"),
        ("anomalie", "écart", "LIM01"),
        ("chef d'atelier", "hiérarchie", "I12"),
        ("signaler", "remonter", "I12"),
    ],
)
def test_une_paire_de_la_liste_noire_ne_produit_aucune_arete(pont, gauche, droite, origine) -> None:
    assert pont.alias_de(gauche, droite) is None, (
        f"{origine} : {gauche!r} et {droite!r} ne doivent jamais être alias"
    )


@pytest.mark.parametrize(
    ("gauche", "droite"),
    [
        ("casque", "gants"),
        ("anomalie", "écart"),
        ("chef d'atelier", "hiérarchie"),
        ("signaler", "remonter"),
    ],
)
def test_une_paire_de_la_liste_noire_ne_partage_pas_de_classe_canonique(
    pont, vocabulaire, gauche, droite
) -> None:
    """Plus fort que l'absence d'arête directe : l'absence de classe commune.

    Deux concepts peuvent se retrouver unis **par transitivité** via un tiers, sans arête
    entre eux. Un alias transitif erroné est tout aussi destructeur qu'un alias direct —
    c'est lui qui rendrait comparables des dizaines de clauses sans rapport.
    """
    assert not pont.sont_allies(gauche, droite, vocabulaire)


@pytest.mark.parametrize(
    ("gauche", "droite"),
    [
        ("casque", "gants"),
        ("anomalie", "écart"),
        ("chef d'atelier", "hiérarchie"),
        ("signaler", "remonter"),
    ],
)
def test_la_liste_noire_n_est_pas_verte_par_accident(pont, vocabulaire, gauche, droite) -> None:
    """Le garde-fou contre la tautologie.

    Une paire noire pourrait « passer » simplement parce qu'un de ses concepts n'a pas été
    extrait, ou parce que la paire n'a jamais été examinée. Le test exige donc que les deux
    concepts existent **et** que la paire ait bien été confrontée, cosinus mesuré à l'appui.
    Sans cela, un bug d'extraction de concepts afficherait du vert.
    """
    assert vocabulaire.par_libelle(gauche) is not None, f"{gauche!r} non extrait"
    assert vocabulaire.par_libelle(droite) is not None, f"{droite!r} non extrait"
    assert pont.cosinus_de(gauche, droite) is not None, (
        f"la paire {gauche!r}/{droite!r} n'a jamais été examinée par la cascade"
    )


def test_le_veto_trace_ce_qui_l_aurait_accepte(pont) -> None:
    """Chaque veto dit quel niveau aurait laissé passer la paire.

    C'est ce qui rend la liste noire auditable, et c'est ce qui a révélé un fait qu'il faut
    savoir : sur ce corpus, avec les seuils inchangés, **tous les vetos rapportent
    `AUCUN`**. Le seuil vectoriel de 0,86 rejette déjà ces paires par lui-même ; la liste
    noire est une garantie de second rideau, pas le mécanisme qui les porte. Elle
    redeviendrait décisive dès qu'on abaisserait le seuil.
    """
    assert pont.vetos, "aucun veto appliqué : la liste noire ne sert-elle à rien ?"
    for veto in pont.vetos:
        assert veto.niveau_qui_aurait_accepte in {
            "EXACT",
            "LEXIQUE",
            "VECTEUR",
            "ZONE_GRISE",
            "AUCUN",
        }


# ------------------------------------------------------------------------ zone grise


def test_la_zone_grise_respecte_son_budget(pont) -> None:
    from cohera.graphe.config_alias import charger_config_alias

    budget = charger_config_alias().seuils.zone_grise_budget
    assert len(pont.zone_grise) == budget


def test_la_zone_grise_ne_contient_aucune_paire_deja_alias(pont) -> None:
    """Cas négatif : une paire tranchée n'a rien à faire en arbitrage LLM au J6."""
    couples_alias = {arete.couple for arete in pont.aretes}
    for paire in pont.zone_grise:
        from cohera.graphe.libelles import normaliser_libelle

        couple = frozenset(
            (normaliser_libelle(paire.libelle_a), normaliser_libelle(paire.libelle_b))
        )
        assert couple not in couples_alias


def test_la_zone_grise_ne_contient_aucune_paire_de_la_liste_noire(pont) -> None:
    from cohera.graphe.config_alias import couples_interdits
    from cohera.graphe.libelles import normaliser_libelle

    for paire in pont.zone_grise:
        couple = frozenset(
            (normaliser_libelle(paire.libelle_a), normaliser_libelle(paire.libelle_b))
        )
        assert couple not in couples_interdits()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CRITÈRE ROUGE, consigné dans CLAUDE.md. Le plan attend « archiver/conserver » et "
        "« registre de contrôle des EPI / enregistrements de vérification » en zone grise. "
        "Mesuré avec bge-m3 : 0,613 et 0,600, sous le plancher de 0,72 — et loin derrière "
        "les paires que le budget retient (0,856 et 0,852). Gonfler le budget jusqu'à les "
        "faire remonter serait exactement le contournement que le plan interdit. "
        "Conséquence : le J6 n'a pas ces deux arbitrages, donc I03 reste bloquée."
    ),
)
def test_la_zone_grise_contient_les_deux_paires_attendues(pont) -> None:
    from cohera.graphe.libelles import normaliser_libelle

    presentes = {
        frozenset((normaliser_libelle(p.libelle_a), normaliser_libelle(p.libelle_b)))
        for p in pont.zone_grise
    }
    attendues = [
        ("archiver", "conserver"),
        ("registre de contrôle des EPI", "enregistrements de vérification"),
    ]
    for gauche, droite in attendues:
        couple = frozenset((normaliser_libelle(gauche), normaliser_libelle(droite)))
        assert couple in presentes, f"{gauche!r} ~ {droite!r} absente de la zone grise"


def test_la_zone_grise_s_ecrit_et_se_relit(pont, tmp_path) -> None:
    chemin = ecrire_zone_grise(pont, tmp_path / "zone_grise.jsonl")
    relues = lire_zone_grise(chemin)
    assert len(relues) == len(pont.zone_grise)
    assert [p.libelle_a for p in relues] == [p.libelle_a for p in pont.zone_grise]


def test_un_fichier_de_zone_grise_absent_donne_une_liste_vide(tmp_path) -> None:
    assert lire_zone_grise(tmp_path / "inexistant.jsonl") == []


# ------------------------------------------------------------------------ union-find


def test_l_union_find_regroupe_par_transitivite() -> None:
    union = UnionFind()
    union.unir("a", "b")
    union.unir("b", "c")
    assert union.trouver("a") == union.trouver("c")


def test_l_union_find_garde_disjoint_ce_qui_n_est_pas_uni() -> None:
    union = UnionFind()
    union.unir("a", "b")
    union.ajouter("z")
    assert union.trouver("a") != union.trouver("z")


def test_l_union_find_est_deterministe() -> None:
    """Deux exécutions doivent élire la même racine, sinon le canonique change d'un
    chargement à l'autre et l'idempotence de `cle_comparaison` tombe."""
    premier, second = UnionFind(), UnionFind()
    premier.unir("b", "a")
    second.unir("a", "b")
    assert premier.trouver("a") == second.trouver("a")


# ---------------------------------------------------------------------- canoniques


def test_chaque_concept_a_un_canonique(pont, vocabulaire) -> None:
    for concept_id in vocabulaire.concepts:
        assert concept_id in pont.canoniques


def test_les_membres_d_une_classe_partagent_leur_canonique(pont) -> None:
    for arete in pont.aretes:
        assert pont.canoniques[arete.concept_a] == pont.canoniques[arete.concept_b]


def test_le_canonique_est_stable_entre_deux_constructions(vocabulaire) -> None:
    """Deux constructions du pont doivent élire exactement les mêmes canoniques.

    C'est la condition de l'idempotence du chargement : un canonique qui changerait
    réécrirait toutes les `cle_comparaison` et ferait diverger le second chargement.
    """
    from cohera.graphe.alias import construire_pont

    assert construire_pont(vocabulaire).canoniques == construire_pont(vocabulaire).canoniques
