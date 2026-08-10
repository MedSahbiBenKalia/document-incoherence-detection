"""Tests de la couche de compatibilité vectorielle Neo4j.

Aucun serveur n'est nécessaire : :func:`requete_vectorielle` est une fonction pure, et
c'est précisément pour cela qu'elle a été isolée de son exécution. Les deux branches sont
donc exerçables en dehors de toute infrastructure — y compris celle qu'on n'a pas sous la
main, comme une instance 5.x héritée.
"""

from __future__ import annotations

import textwrap

import pytest

from cohera import reglages
from cohera.graphe import compat


# ------------------------------------------------------------- analyse de version


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("2026.06.0", (2026, 6)),      # calendaire, le schéma actuel
        ("2026.01.0", (2026, 1)),
        ("5.26.0", (5, 26)),           # sémantique, le schéma hérité
        ("5.9.0", (5, 9)),
        ("2026.06.0-aura", (2026, 6)), # suffixe de distribution
    ],
)
def test_analyser_version(brut: str, attendu: tuple[int, int]) -> None:
    assert compat.analyser_version(brut) == attendu


@pytest.mark.parametrize("brut", ["", "inconnue", "5", None])
def test_analyser_version_refuse_ce_qui_est_inexploitable(brut) -> None:
    with pytest.raises(ValueError):
        compat.analyser_version(brut)


@pytest.mark.parametrize(
    ("version", "attendu"),
    [
        ((2026, 6), True),    # au-delà de la dépréciation de la procédure
        ((2026, 4), True),
        ((2026, 1), True),    # première version exposant la clause SEARCH
        ((2025, 12), False),  # juste avant : frontière basse
        ((5, 26), False),     # dernière branche sémantique
    ],
)
def test_frontiere_de_la_clause_search(version: tuple[int, int], attendu: bool) -> None:
    assert compat.supporte_clause_search(version) is attendu


# --------------------------------------------------------- construction de requête


def test_version_moderne_produit_la_clause_search() -> None:
    requete = compat.requete_vectorielle((2026, 6), "clause_vecteur", k=10)

    assert "SEARCH" in requete
    assert "VECTOR INDEX clause_vecteur" in requete
    assert "CYPHER 25" in requete
    assert "db.index.vector.queryNodes" not in requete
    # k et le vecteur restent paramétrés : seul le nom d'index est interpolé.
    assert "$vecteur" in requete and "$k" in requete


def test_version_heritee_produit_la_procedure() -> None:
    requete = compat.requete_vectorielle((5, 26), "clause_vecteur", k=10)

    assert "db.index.vector.queryNodes" in requete
    assert "SEARCH" not in requete
    # Sur cette branche, tout est paramétrable, y compris le nom d'index.
    assert "$index" in requete and "$k" in requete and "$vecteur" in requete


def test_les_deux_branches_exposent_les_memes_colonnes() -> None:
    """Le reste du code ne doit jamais avoir à savoir quelle branche a servi."""
    moderne = compat.requete_vectorielle((2026, 6), "idx", k=5)
    heritee = compat.requete_vectorielle((5, 26), "idx", k=5)

    for requete in (moderne, heritee):
        assert "noeud" in requete
        assert "score" in requete


# ------------------------------------------------------------------ anti-injection


@pytest.mark.parametrize(
    "nom",
    [
        "idx) RETURN 1 //",     # sortir de la parenthèse de SEARCH
        "idx; MATCH (n)",
        "1_commence_par_un_chiffre",
        "avec-tiret",
        "avec espace",
        "",
    ],
)
def test_un_nom_d_index_douteux_est_refuse(nom: str) -> None:
    """Le nom d'index ne peut pas être un paramètre dans la clause SEARCH : il est
    interpolé. Sans ce garde-fou, un nom venu de la configuration serait une injection."""
    with pytest.raises(ValueError):
        compat.valider_nom_index(nom)
    with pytest.raises(ValueError):
        compat.requete_vectorielle((2026, 6), nom, k=5)


@pytest.mark.parametrize("nom", ["idx", "clause_vecteur", "_prive", "Index2026"])
def test_un_nom_d_index_valide_passe(nom: str) -> None:
    assert compat.valider_nom_index(nom) == nom


def test_k_doit_etre_positif() -> None:
    with pytest.raises(ValueError):
        compat.recherche_vectorielle("idx", 0, [0.1, 0.2])


# ------------------------------------------------------- échappatoire de configuration


def _config_forcant(tmp_path, syntaxe: str):
    """Écrit une configuration technique minimale forçant une syntaxe vectorielle."""
    chemin = tmp_path / "technique.yaml"
    chemin.write_text(
        textwrap.dedent(
            f"""
            device: cpu
            neo4j:
              uri: bolt://localhost:7687
              syntaxe_vectorielle: {syntaxe}
            """
        ).strip(),
        encoding="utf-8",
    )
    return chemin


@pytest.mark.parametrize(
    ("syntaxe", "version", "marqueur_attendu", "marqueur_absent"),
    [
        # Forcer la procédure sur un serveur moderne : utile pour exercer le chemin
        # hérité sans avoir d'instance 5.x sous la main.
        ("procedure", (2026, 6), "db.index.vector.queryNodes", "SEARCH"),
        # Forcer SEARCH malgré une version qui dit le contraire : parade si le serveur
        # annonce mal sa version.
        ("search", (5, 26), "SEARCH", "db.index.vector.queryNodes"),
    ],
)
def test_la_configuration_peut_forcer_une_branche(
    tmp_path, monkeypatch, syntaxe, version, marqueur_attendu, marqueur_absent
) -> None:
    monkeypatch.setenv("COHERA_CONFIG", str(_config_forcant(tmp_path, syntaxe)))
    reglages.charger.cache_clear()
    try:
        requete = compat.requete_vectorielle(version, "idx", k=5)
        assert marqueur_attendu in requete
        assert marqueur_absent not in requete
    finally:
        reglages.charger.cache_clear()


def test_la_configuration_par_defaut_laisse_decider_la_version() -> None:
    """`auto` est bien le comportement du dépôt : c'est la version qui tranche."""
    reglages.charger.cache_clear()
    try:
        assert reglages.charger().neo4j.syntaxe_vectorielle == "auto"
        assert compat.syntaxe_effective((2026, 6)) == "search"
        assert compat.syntaxe_effective((5, 26)) == "procedure"
    finally:
        reglages.charger.cache_clear()
