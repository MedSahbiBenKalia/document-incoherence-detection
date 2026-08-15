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
from cohera.graphe.libelles import normaliser_libelle
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


def test_un_verbe_etiquete_adjectif_est_quand_meme_une_action() -> None:
    """Non-régression : sur D1 §4.2, `fr_core_news_lg` étiquette « valide » en ADJ.

    L'homographe est réel — « valide » est aussi un adjectif — mais un adjectif français ne
    prend pas d'objet direct. La présence simultanée d'un sujet nominal et d'un `obj` sur la
    racine suffit donc à trancher, sans lexique de verbes.

    Sans cette réparation, `action_de` renvoyait `None` : la position `action` de la clé de
    comparaison de D1 §4.2 restait vide alors que celle de D2 §4.2 valait « valider », et les
    deux clauses ne pouvaient pas se rencontrer sur le canal CLE que `label.json` attend
    pour I01.
    """
    assert action_de(_doc("Le Responsable QSE valide chaque fiche de contrôle.")) == "valider"


@pytest.mark.parametrize(
    ("texte", "lemme"),
    [
        ("L'agent porte le casque.", "porter"),
        ("Le pilote signe la fiche.", "signer"),
        ("Le service applique la consigne.", "appliquer"),
    ],
)
def test_le_present_de_troisieme_personne_est_ramene_a_l_infinitif(texte, lemme) -> None:
    """La table `lemma_rules` de `fr_core_news_lg` couvre « -es », « -ent », « -ait »… mais
    **pas** « -e » : tout verbe du 1er groupe au présent 3ᵉ personne du singulier ressort
    donc lemmatisé sur sa propre forme fléchie.

    Ce n'est pas propre à « valide » : mesuré sur le corpus, « anime », « applique » et
    « comporte » sont touchés de la même façon. La réparation complète la table de spaCy et
    ne retient qu'un candidat attesté dans son propre index verbal.
    """
    assert action_de(_doc(texte)) == lemme


@pytest.mark.parametrize(
    "texte",
    [
        # Racine adjectivale, sujet mais aucun objet direct : « conformer » existe pourtant
        # comme verbe, c'est bien la syntaxe qui doit refuser, pas le lexique.
        "La signalisation est conforme à la norme.",
        "Le port du casque est obligatoire en zone A.",
        "Les registres sont accessibles à tout moment.",
    ],
)
def test_une_racine_adjectivale_sans_objet_direct_ne_devient_pas_une_action(texte) -> None:
    """Cas négatif de la réparation ci-dessus.

    C'est le garde-fou qui l'empêche de dégénérer : si le seul critère était « la racine
    n'est pas un verbe », « conforme » deviendrait l'action « conformer » et la clé de
    comparaison de toute clause de conformité serait fausse.
    """
    assert action_de(_doc(texte)) is None


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


def test_l_empan_d_un_acteur_ne_produit_pas_d_objet() -> None:
    """Un rôle du gazetteer est déjà un `ACTEUR` : le revoir en `OBJET` le compte deux fois.

    Le sujet « Le Responsable QSE » produisait « Responsable QSE » **et** sa tête nue
    « Responsable ». Cette dernière, rare donc à fort IDF, gagnait la position `objet` de la
    clé de comparaison de D1 §4.2 devant « fiche de contrôle ». D2 §4.2 y mettait bien
    « fiche de contrôle » — non par correction, mais parce que « Référent » y était moins
    discriminant. La clé dépendait donc d'un hasard d'IDF.

    C'est le groupe dont la **tête** tombe dans le rôle qui est écarté, et lui seul — voir
    `test_un_groupe_qui_contient_un_role_n_est_pas_troue` pour la raison.
    """
    doc = _doc("Le Responsable QSE valide chaque fiche de contrôle sous 48 heures.")
    objets = objets_de(doc, frozenset({"48 heures"}), frozenset({"Responsable QSE"}))
    assert "Responsable QSE" not in objets
    assert "Responsable" not in objets


def test_l_exclusion_de_l_acteur_epargne_les_vrais_objets() -> None:
    """Cas négatif du précédent : retirer l'acteur ne doit rien retirer d'autre."""
    doc = _doc("Le Responsable QSE valide chaque fiche de contrôle sous 48 heures.")
    objets = objets_de(doc, frozenset({"48 heures"}), frozenset({"Responsable QSE"}))
    assert "fiche de contrôle" in objets
    assert "contrôle" in objets


@pytest.mark.parametrize(
    ("texte", "role"),
    [
        (
            "Le Référent sécurité anime le réseau des correspondants sécurité des ateliers.",
            "correspondants sécurité",
        ),
        (
            "Elle s'applique à l'ensemble du personnel du site ainsi qu'aux prestataires.",
            "personnel",
        ),
        # La phrase entière de D1 §10.1 : isolée, « Directeur de site » serait la tête de son
        # propre groupe et l'exclusion l'écarterait à bon droit. C'est ici qu'il est enchâssé.
        (
            "Dérogation motivée par la nature répétitive des opérations, approuvée par le"
            " Directeur de site le 12 février 2026, valable jusqu'au 31 décembre 2026.",
            "Directeur de site",
        ),
    ],
)
def test_un_groupe_qui_contient_un_role_n_est_pas_troue(texte, role) -> None:
    """Cas négatif de l'exclusion, et la raison pour laquelle elle ne retire pas de jetons.

    Un rôle apparaît souvent **à l'intérieur** d'un groupe nominal plus large sans en être la
    tête. Traiter son empan comme celui d'une grandeur — retrait des jetons puis
    reconstruction — perçait le groupe : mesuré sur D2 §4.3, « réseau des correspondants
    sécurité des ateliers » ressortait en « réseau des des ateliers », et sur D1 §10.1
    « approuvée par le Directeur de site le 12 février » en « approuvée par février ».

    Trois concepts du corpus étaient mutilés de la sorte. D'où le choix d'écarter le groupe
    par sa tête plutôt que par ses jetons.

    L'invariant vérifié est « aucun trou », pas un syntagme exact : tout groupe qui mentionne
    encore un mot du rôle doit le mentionner **en entier et d'un seul tenant**. Un groupe
    troué garde le début du rôle et perd la suite, et échoue donc ici.
    """
    mots_du_role = normaliser_libelle(role)
    objets = objets_de(_doc(texte), frozenset(), frozenset({role}))

    concernes = [o for o in objets if mots_du_role.split()[0] in normaliser_libelle(o)]
    assert concernes, f"aucun groupe ne mentionne plus {role!r} : l'exclusion a trop mordu"
    for objet in concernes:
        assert mots_du_role in normaliser_libelle(objet), (
            f"{objet!r} a été troué : {role!r} n'y est plus d'un seul tenant"
        )


def test_sans_acteur_declare_les_objets_sont_inchanges() -> None:
    """Le paramètre est facultatif et neutre par défaut : le module reste utilisable seul."""
    doc = _doc("Toute anomalie détectée est signalée au chef d'atelier.")
    assert objets_de(doc) == objets_de(doc, frozenset(), frozenset())


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
