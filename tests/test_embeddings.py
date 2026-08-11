"""cohera/embeddings.py — cache disque par hash.

Exigence du J3 (docs/plan-1-semaine.md) : « embeddings … avec cache disque par hash ».
La propriété qui compte est celle que le J6 réclamera pour le LLM — « même entrée deux
fois, un seul calcul » — et elle se teste ici sans charger le moindre modèle, grâce à
l'encodeur injectable.

Aucun test de ce fichier ne télécharge bge-m3 : tous passent un `encodeur` factice qui
compte ses appels. Le modèle réel est déjà couvert par `cohera doctor`.
"""

from __future__ import annotations

import numpy as np
import pytest

from cohera import embeddings

DIMENSION_TEST = 8


class EncodeurCompteur:
    """Encodeur factice : vecteurs déterministes, et il retient ce qu'on lui a demandé."""

    def __init__(self) -> None:
        self.appels: list[list[str]] = []

    def __call__(self, textes: list[str]) -> np.ndarray:
        self.appels.append(list(textes))
        vecteurs = []
        for texte in textes:
            graine = np.frombuffer(texte.encode("utf-8")[:8].ljust(8, b"\0"), dtype=np.uint8)
            vecteur = graine.astype(np.float32)
            vecteurs.append(vecteur / (np.linalg.norm(vecteur) or 1.0))
        return np.vstack(vecteurs)

    @property
    def nb_textes_encodes(self) -> int:
        return sum(len(appel) for appel in self.appels)


@pytest.fixture
def cache_isole(tmp_path, monkeypatch):
    """Redirige le cache disque vers `tmp_path` : aucun test ne pollue `.cache/` du dépôt."""
    monkeypatch.setattr(embeddings, "dossier_cache", lambda: tmp_path / "embeddings")
    return tmp_path


# ------------------------------------------------------------------------- la clé


def test_la_cle_depend_du_texte() -> None:
    assert embeddings.cle_cache("a", "m") != embeddings.cle_cache("b", "m")


def test_la_cle_depend_du_modele() -> None:
    """Changer de modèle ne doit jamais relire les vecteurs de l'ancien.

    C'est la panne silencieuse par excellence : des cosinus calculés entre deux espaces
    vectoriels différents, sans rien qui le signale.
    """
    assert embeddings.cle_cache("a", "bge-m3") != embeddings.cle_cache("a", "solon")


def test_la_cle_est_stable_entre_deux_appels() -> None:
    assert embeddings.cle_cache("contrôle des EPI", "m") == embeddings.cle_cache(
        "contrôle des EPI", "m"
    )


def test_le_separateur_nul_evite_les_collisions() -> None:
    """Sans séparateur, ("ab", "c") et ("a", "bc") produiraient la même concaténation."""
    assert embeddings.cle_cache("c", "ab") != embeddings.cle_cache("bc", "a")


# ----------------------------------------------------------------------- le cache


def test_le_meme_texte_deux_fois_ne_declenche_qu_un_encodage(cache_isole) -> None:
    """LE critère du J3. Le second appel doit être servi par le disque."""
    encodeur = EncodeurCompteur()

    premier = embeddings.encoder(["le contrôle des EPI"], encodeur=encodeur)
    second = embeddings.encoder(["le contrôle des EPI"], encodeur=encodeur)

    assert encodeur.nb_textes_encodes == 1, encodeur.appels
    np.testing.assert_array_equal(premier, second)


def test_seuls_les_textes_absents_sont_encodes(cache_isole) -> None:
    encodeur = EncodeurCompteur()

    embeddings.encoder(["a", "b"], encodeur=encodeur)
    embeddings.encoder(["b", "c"], encodeur=encodeur)

    assert encodeur.appels == [["a", "b"], ["c"]]


def test_les_doublons_d_un_meme_appel_sont_dedupliques(cache_isole) -> None:
    """« harnais antichute » apparaît dans quatre clauses du corpus : l'encoder quatre fois
    serait du gaspillage pur."""
    encodeur = EncodeurCompteur()

    resultat = embeddings.encoder(["x", "y", "x", "x"], encodeur=encodeur)

    assert encodeur.appels == [["x", "y"]]
    assert resultat.shape[0] == 4
    np.testing.assert_array_equal(resultat[0], resultat[2])
    np.testing.assert_array_equal(resultat[0], resultat[3])


def test_l_ordre_de_sortie_suit_l_ordre_d_entree(cache_isole) -> None:
    """Le cache ne doit pas réordonner : les vecteurs sont appariés aux concepts par
    position, un décalage ici donnerait des alias entre des termes sans rapport."""
    encodeur = EncodeurCompteur()

    ensemble = embeddings.encoder(["a", "b", "c"], encodeur=encodeur)
    for indice, texte in enumerate(["a", "b", "c"]):
        np.testing.assert_array_equal(
            ensemble[indice], embeddings.encoder([texte], encodeur=encodeur)[0]
        )


def test_le_cache_desactive_reencode(cache_isole) -> None:
    """Le cas négatif : sans cache, deux appels donnent deux encodages."""
    encodeur = EncodeurCompteur()

    embeddings.encoder(["a"], encodeur=encodeur, utiliser_cache=False)
    embeddings.encoder(["a"], encodeur=encodeur, utiliser_cache=False)

    assert encodeur.nb_textes_encodes == 2


def test_un_fichier_de_cache_corrompu_est_ignore_et_non_fatal(cache_isole) -> None:
    """Une exécution interrompue laisse un `.npy` tronqué. Il doit être traité comme
    absent, pas faire échouer toute la journée."""
    encodeur = EncodeurCompteur()
    embeddings.encoder(["a"], encodeur=encodeur)

    fichier = next((cache_isole / "embeddings").rglob("*.npy"))
    fichier.write_bytes(b"\x93NUMPY tronqu")

    embeddings.encoder(["a"], encodeur=encodeur)
    assert encodeur.nb_textes_encodes == 2


def test_l_entree_vide_ne_leve_pas(cache_isole) -> None:
    resultat = embeddings.encoder([], encodeur=EncodeurCompteur())
    assert resultat.shape[0] == 0


def test_un_encodeur_qui_ment_sur_le_nombre_de_vecteurs_leve(cache_isole) -> None:
    """Garde-fou : un encodeur renvoyant trop peu de vecteurs décalerait silencieusement
    tout l'appariement concept ↔ vecteur."""

    def menteur(textes: list[str]) -> np.ndarray:
        return np.zeros((1, DIMENSION_TEST), dtype=np.float32)

    with pytest.raises(RuntimeError, match="vecteur"):
        embeddings.encoder(["a", "b"], encodeur=menteur)


# ---------------------------------------------------------------------- cosinus


def test_le_cosinus_de_deux_vecteurs_identiques_vaut_un() -> None:
    v = np.array([0.6, 0.8], dtype=np.float32)
    assert embeddings.cosinus(v, v) == pytest.approx(1.0)


def test_le_cosinus_reste_borne() -> None:
    """Les miettes d'arrondi donneraient sinon des scores comme 1.0000000002 dans le
    rapport."""
    v = np.array([1.0, 0.0], dtype=np.float32)
    assert -1.0 <= embeddings.cosinus(v, v) <= 1.0
    assert -1.0 <= embeddings.cosinus(v, -v) <= 1.0


def test_le_cosinus_de_deux_vecteurs_orthogonaux_est_nul() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert embeddings.cosinus(a, b) == pytest.approx(0.0)
