"""graphe/concepts.py — acteur (gazetteer), action et objet (syntaxe spaCy).

Critère du J3 (docs/plan-1-semaine.md §J3) : « Concepts : acteur (gazetteer), objet et
action (syntaxe spaCy : sujet / verbe / objet direct) ».

Le vrai enjeu de ce module n'est pas la couverture mais la **précision** : chaque concept
extrait devient un point d'accroche du pont, et un concept mal découpé (« fiche de contrôle
sous heures », « à hiérarchie ») produit soit du bruit, soit un alias erroné. D'où le poids
donné ici aux cas négatifs.
"""

from __future__ import annotations

import pytest

from cohera.graphe.concepts import TypeConcept, acteurs_de, action_de, objets_de
from cohera.ingestion.phrases import analyseur


def _doc(texte: str):
    return analyseur()(texte)


# ------------------------------------------------------------------------- acteurs


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("Le Responsable QSE valide chaque fiche de contrôle.", "Responsable QSE"),
        ("Le Référent sécurité est chargé de valider les fiches.", "Référent sécurité"),
        ("Toute anomalie est signalée au chef d'atelier.", "chef d'atelier"),
        ("Le plan de prévention est approuvé par le Directeur de site.", "Directeur de site"),
        ("L'installation est arrêtée immédiatement par l'opérateur.", "opérateur"),
    ],
)
def test_un_role_du_gazetteer_est_reconnu(texte: str, attendu: str) -> None:
    assert attendu in acteurs_de(texte)


def test_le_role_le_plus_long_gagne() -> None:
    """« Responsable QSE » doit être reconnu comme tel, pas décomposé.

    Sans le tri par longueur, un rôle court inclus dans un rôle long les ferait s'effondrer
    l'un sur l'autre — et « Responsable QSE » deviendrait indistinct d'« Animateur QSE ».
    """
    trouves = acteurs_de("Le Responsable QSE valide.")
    assert "Responsable QSE" in trouves
    assert "Animateur QSE" not in trouves


def test_deux_roles_distincts_de_la_meme_phrase_sont_tous_deux_vus() -> None:
    trouves = acteurs_de("Le registre est tenu à jour par l'Animateur QSE et le Magasinier.")
    assert "Animateur QSE" in trouves
    assert "Magasinier" in trouves


def test_une_phrase_sans_role_ne_produit_aucun_acteur() -> None:
    """Cas négatif : le gazetteer ne doit pas halluciner un acteur."""
    assert acteurs_de("Le port du casque est obligatoire en zone A.") == []


# -------------------------------------------------------------------------- actions


@pytest.mark.parametrize(
    ("texte", "lemme"),
    [
        ("Toute anomalie détectée est signalée au chef d'atelier.", "signaler"),
        ("Les écarts constatés sont remontés à la hiérarchie.", "remonter"),
        ("Le registre est archivé pendant 3 ans.", "archiver"),
        ("Les enregistrements sont conservés pendant 5 ans.", "conserver"),
        # Verbe support : l'action réelle est dans le xcomp.
        ("Le contrôle des EPI doit être renouvelé.", "renouveler"),
        ("Le Référent sécurité est chargé de valider les fiches.", "valider"),
    ],
)
def test_l_action_est_le_verbe_porteur_de_sens(texte: str, lemme: str) -> None:
    assert action_de(_doc(texte)) == lemme


def test_une_clause_sans_verbe_ne_produit_aucune_action() -> None:
    """Cas négatif. « Le port du casque est obligatoire » a une racine adjectivale : c'est
    sa modalité qui la caractérise, déjà extraite au J2, pas une action."""
    assert action_de(_doc("Le port du casque est obligatoire en zone A.")) is None


# --------------------------------------------------------------------------- objets


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("Le Responsable QSE valide chaque fiche de contrôle.", "fiche de contrôle"),
        ("Le registre de contrôle des EPI est tenu à jour.", "registre de contrôle des EPI"),
        ("Les enregistrements de vérification sont conservés.", "enregistrements de vérification"),
        ("Le harnais antichute est requis pour les interventions.", "harnais antichute"),
        ("Le port du harnais antichute est obligatoire.", "harnais antichute"),
    ],
)
def test_un_syntagme_est_reconstruit_d_un_seul_tenant(texte: str, attendu: str) -> None:
    """`noun_chunks` découpe « fiche de contrôle » en deux ; le sous-arbre de dépendance,
    non. C'est la raison du choix documenté en tête de module."""
    assert attendu in objets_de(_doc(texte))


def test_une_erreur_d_analyse_connue_ampute_un_syntagme() -> None:
    """Limite mesurée, consignée plutôt que masquée.

    Sur D1 §5.3 « Le contrôle approfondi des harnais antichute est réalisé tous les
    12 mois », `fr_core_news_lg` rattache « antichute » en `amod` de **contrôle** au lieu de
    **harnais**. Le sous-arbre de « harnais » ne contient donc pas son adjectif, et cette
    clause-là ne produit que « harnais ».

    Sans conséquence sur le corpus : les trois autres occurrences (D1 §7.1, D2 §5.3, D2
    §7.1) sont correctement analysées, et « harnais antichute » existe donc bien comme
    concept partagé par les deux documents. Ce test fige le comportement réel — s'il change,
    on veut le savoir.
    """
    objets = objets_de(_doc("Le contrôle approfondi des harnais antichute est réalisé."))
    assert "harnais" in objets
    assert "harnais antichute" not in objets


def test_la_tete_nue_accompagne_le_syntagme_complet() -> None:
    """« gants de manutention » doit aussi produire « gants ».

    C'est ce niveau-là qui s'aligne d'un document à l'autre — et c'est ce dont dépend le
    veto `casque ≢ gants`, qui ne pourrait pas s'appliquer à un concept inexistant.
    """
    objets = objets_de(_doc("Le port de gants de manutention est obligatoire."))
    assert "gants de manutention" in objets
    assert "gants" in objets


def test_la_preposition_de_tete_est_retiree() -> None:
    """« remontés à la hiérarchie » donne « hiérarchie », pas « à hiérarchie »."""
    objets = objets_de(_doc("Les écarts sont remontés à la hiérarchie dans la semaine."))
    assert "hiérarchie" in objets
    assert not any(o.startswith("à ") for o in objets)


def test_la_preposition_interne_est_conservee() -> None:
    """Cas négatif du précédent : retirer les prépositions internes ferait collisionner
    « contrôle des EPI » avec des syntagmes que rien ne rapproche."""
    objets = objets_de(_doc("Le contrôle des EPI doit être renouvelé."))
    assert "contrôle des EPI" in objets


def test_les_jetons_d_une_grandeur_sont_ecartes() -> None:
    """Sur cette phrase, spaCy rattache « heures » en `nmod` de « contrôle » : sans retrait
    des jetons de quantité, le sous-arbre produirait « fiche de contrôle sous heures ».

    Une quantité est réifiée en nœud `Quantite` ; la voir aussi dans le vocabulaire
    polluerait l'IDF et le canal conceptuel.
    """
    doc = _doc("Le Responsable QSE valide chaque fiche de contrôle sous 48 heures.")
    objets = objets_de(doc, frozenset({"48 heures"}))
    assert "fiche de contrôle" in objets
    assert not any("heure" in o for o in objets)


def test_aucun_objet_ne_se_reduit_a_un_nombre() -> None:
    objets = objets_de(_doc("Le harnais est requis à plus de 3 mètres."))
    assert not any(o.strip().isdigit() for o in objets)


# ---------------------------------------------------------------- sur tout le corpus


@pytest.mark.parametrize(
    ("libelle", "type_attendu"),
    [
        ("Responsable QSE", TypeConcept.ACTEUR),
        ("Référent sécurité", TypeConcept.ACTEUR),
        ("chef d'atelier", TypeConcept.ACTEUR),
        ("signaler", TypeConcept.ACTION),
        ("remonter", TypeConcept.ACTION),
        ("archiver", TypeConcept.ACTION),
        ("casque", TypeConcept.OBJET),
        ("gants", TypeConcept.OBJET),
        ("hiérarchie", TypeConcept.OBJET),
        ("anomalie", TypeConcept.OBJET),
        ("écart", TypeConcept.OBJET),
        ("harnais antichute", TypeConcept.OBJET),
        ("zone à risque", TypeConcept.OBJET),
        ("registre de contrôle des EPI", TypeConcept.OBJET),
        ("enregistrements de vérification", TypeConcept.OBJET),
    ],
)
def test_un_concept_dont_depend_un_critere_est_present(vocabulaire, libelle, type_attendu) -> None:
    """Tous les termes cités par la liste blanche, la liste noire ou la zone grise doivent
    exister comme concepts — sinon les tests du pont seraient tautologiques."""
    concept = vocabulaire.par_libelle(libelle)
    assert concept is not None, f"{libelle!r} n'a pas été extrait"
    assert concept.type is type_attendu


def test_l_idf_discrimine(vocabulaire) -> None:
    """Un terme omniprésent doit avoir un IDF plus faible qu'un terme rare.

    Le canal 3 du J4 ne retient que `idf > 1,5` : sans cette propriété, il apparierait sur
    « site » ou « document » et produirait du bruit à grande échelle.
    """
    frequents = [c for c in vocabulaire.concepts.values() if c.frequence >= 5]
    rares = [c for c in vocabulaire.concepts.values() if c.frequence == 1]
    assert frequents and rares
    assert max(c.idf for c in frequents) < max(c.idf for c in rares)


def test_aucun_concept_ne_commence_par_une_preposition(vocabulaire) -> None:
    """Contrôle de propreté sur tout le corpus, pas seulement sur les cas choisis."""
    fautifs = [
        c.libelle
        for c in vocabulaire.concepts.values()
        if c.libelle.lower().split()[0] in {"de", "du", "des", "à", "au", "aux", "en", "sous"}
    ]
    assert not fautifs, f"concepts mal découpés : {fautifs[:10]}"


def test_chaque_mention_pointe_vers_un_concept_existant(vocabulaire) -> None:
    for mention in vocabulaire.mentions:
        assert mention.concept_id in vocabulaire.concepts
