"""graphe/libelles.py — normalisation des libellés de concept.

Niveau 1 de la cascade du pont inter-documents (architecture.md §5.6) : « minuscules, sans
accents ni déterminants, lemmatisée ». C'est ce qui décide d'un `ALIAS_DE {EXACT}`, donc
une normalisation trop gourmande fabrique des alias erronés — le risque n°1 du projet
(architecture.md §13, R1). D'où les cas négatifs : ce que la normalisation ne doit PAS
confondre compte autant que ce qu'elle doit rapprocher.

Aucun modèle n'est chargé ici sauf dans la section lemmatisation, isolée en fin de fichier.
"""

from __future__ import annotations

import pytest

from cohera.graphe.libelles import normaliser_libelle, sans_accents

# ------------------------------------------------------------------ formes de surface


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("Le Responsable QSE", "responsable qse"),
        ("le responsable QSE", "responsable qse"),
        ("l'installation", "installation"),
        ("L'Animateur QSE", "animateur qse"),
        ("  Contrôle   des EPI  ", "controle des epi"),
        ("La présente procédure", "procedure"),
        ("tout le personnel du site", "personnel du site"),
        ("zone à risque", "zone a risque"),
        ("EPI", "epi"),
        ("équipements de protection", "equipements de protection"),
        ("Référent sécurité", "referent securite"),
        ("chef d'atelier", "chef d atelier"),
        ("harnais antichute", "harnais antichute"),
    ],
)
def test_un_libelle_du_corpus_est_normalise(brut: str, attendu: str) -> None:
    assert normaliser_libelle(brut) == attendu


def test_la_normalisation_est_idempotente() -> None:
    """La réappliquer ne doit rien changer : sinon la clé d'un dictionnaire dépendrait du
    nombre de fois qu'on l'a calculée."""
    for brut in ("Le Responsable QSE", "l'installation", "La présente procédure", "EPI"):
        une_fois = normaliser_libelle(brut)
        assert normaliser_libelle(une_fois) == une_fois


def test_le_libelle_vide_ne_leve_pas() -> None:
    assert normaliser_libelle("") == ""


def test_sans_accents_conserve_la_longueur_en_caracteres_de_base() -> None:
    assert sans_accents("sécurité") == "securite"
    assert sans_accents("Radès") == "Rades"


# ------------------------------------------------------- les négatifs : ne pas confondre


@pytest.mark.parametrize(
    ("gauche", "droite"),
    [
        # Le cœur de la liste noire : ces couples doivent rester distincts après
        # normalisation, sinon ils deviendraient des alias EXACT et le veto arriverait
        # trop tard.
        ("casque", "gants"),
        ("anomalie", "écart"),
        ("chef d'atelier", "hiérarchie"),
        ("signaler", "remonter"),
        ("contrôle", "vérification"),
        ("Responsable QSE", "Référent sécurité"),
        ("Responsable QSE", "Animateur QSE"),
        ("service Qualité", "service Méthodes"),
        # Deux périmètres distincts que le retrait des déterminants pourrait aplatir.
        ("zone A", "zone de stockage"),
    ],
)
def test_deux_concepts_distincts_ne_se_confondent_pas(gauche: str, droite: str) -> None:
    assert normaliser_libelle(gauche) != normaliser_libelle(droite)


def test_le_determinant_interne_est_conserve() -> None:
    """« contrôle des EPI » ne doit pas devenir « contrôle EPI ».

    Retirer les déterminants ailleurs qu'en tête ferait collisionner des syntagmes que
    rien ne rapproche — c'est la raison d'être du commentaire de `config/lexique_qhse.yaml`
    sur `determinants_initiaux`.
    """
    assert normaliser_libelle("le contrôle des EPI") == "controle des epi"
    assert normaliser_libelle("contrôle des EPI") != normaliser_libelle("contrôle EPI")


# ---------------------------------------------------------------- lemmatisation (spaCy)


def test_le_pluriel_est_absorbe_par_la_lemmatisation() -> None:
    """`fiche de contrôle` ≡ `fiches de contrôle`, alias EXACT attendu par le J3.

    C'est le seul écart de la liste blanche que la forme de surface ne sait pas absorber :
    il faut le lemmatiseur.
    """
    from cohera.graphe.libelles import forme_canonique

    assert forme_canonique("fiche de contrôle") == forme_canonique("fiches de contrôle")


def test_la_lemmatisation_ne_confond_pas_deux_termes_distincts() -> None:
    """Le cas négatif obligatoire : le lemmatiseur ne doit pas rapprocher plus que le
    pluriel. « gants » et « casque » partagent un contexte mais pas un lemme."""
    from cohera.graphe.libelles import forme_canonique

    assert forme_canonique("casque") != forme_canonique("gants")
    assert forme_canonique("anomalie") != forme_canonique("écart")
