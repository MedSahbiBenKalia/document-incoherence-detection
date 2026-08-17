"""Lecture de `config/detection.yaml` — échelle déontique, gravité, preuve.

Un module dédié, sur le modèle de `ciblage/config_ciblage.py` : un seul endroit lit le
fichier, et les détecteurs ne connaissent que des fonctions nommées. Aucune valeur métier
ne vit dans un `.py` (`CLAUDE.md`).

La section `conditions` n'est pas lue ici mais dans `graphe/conditions.py`, qui en est le
seul consommateur — la hiérarchie des lieux n'a rien à faire dans la cascade.
"""

from __future__ import annotations

from functools import lru_cache

from cohera import reglages
from cohera.extraction.frames import Modalite


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("detection")


def vider_caches() -> None:
    """Oublie la configuration mémorisée. À appeler après un `monkeypatch` de config.

    ⚠️ La liste est énumérée en dur : tout nouvel accesseur mémorisé doit y être inscrit,
    sans quoi les tests qui surchargent la configuration resteront sur la valeur cachée.
    """
    for fonction in (
        _config, echelle_deontique, ecart_conflit_fort, polarites_opposees,
        objets_partages_min, _seuils_gravite,
        motifs_fermants, ecarter_les_portees_disjointes, max_appels_juge,
        echecs_consecutifs_max, confiance_min_juge, temperature_juge,
        longueur_max_texte,
    ):
        fonction.cache_clear()


# --------------------------------------------------------------------------- A1


@lru_cache(maxsize=1)
def echelle_deontique() -> dict[Modalite, int]:
    """Force de chaque modalité (architecture.md §7.1).

    Lue par A1 pour **recalculer** la force depuis la modalité plutôt que de reprendre
    `ClauseFrame.force` : `regles/deontique.py` inverse la modalité sous l'effet d'une
    négation sans toucher à la force, si bien qu'un « ne doit pas » rend INTERDICTION avec
    force 3 au lieu de 4.
    """
    brut = _config().get("deontique", {}).get("echelle", {})
    return {Modalite(nom): int(force) for nom, force in brut.items()}


@lru_cache(maxsize=1)
def ecart_conflit_fort() -> int:
    """Écart de force à partir duquel le conflit est ferme. En deçà : escalade."""
    return int(_config().get("deontique", {}).get("ecart_conflit_fort", 2))


@lru_cache(maxsize=1)
def polarites_opposees() -> frozenset[frozenset[Modalite]]:
    """Couples de modalités qui s'excluent quel que soit l'écart de force."""
    brut = _config().get("deontique", {}).get("polarites_opposees", [])
    return frozenset(frozenset(Modalite(nom) for nom in couple) for couple in brut)


# ------------------------------------------------------------------------- preuve


@lru_cache(maxsize=1)
def objets_partages_min() -> int:
    """Combien de concepts canoniques de type OBJET deux clauses doivent partager pour
    qu'un verdict de valeur soit ferme.

    Le ciblage établit qu'une paire mérite d'être examinée ; il n'établit pas qu'elle parle
    de la même chose. C'est ce que demande la clé de comparaison d'architecture.md §5.8, et
    ce garde-fou en est la version tolérante aux aliases.

    Le seuil est celui du canal conceptuel (`partages_min` de `config/ciblage.yaml`, §6.3),
    transposé aux seuls objets. Distribution mesurée et cas concernés : voir
    `config/detection.yaml`.
    """
    return int(_config().get("preuve", {}).get("objets_partages_min", 2))


# ------------------------------------------------------------------------ gravité


@lru_cache(maxsize=1)
def _seuils_gravite() -> tuple[tuple[float, str], ...]:
    brut = _config().get("gravite", {}).get("seuils_ecart_relatif", [])
    seuils = [(float(e["a_partir_de"]), str(e["gravite"])) for e in brut]
    return tuple(sorted(seuils, reverse=True))


def gravite_par_ecart(ecart_relatif: float) -> str:
    """La gravité d'une divergence numérique, par son écart relatif."""
    for borne, gravite in _seuils_gravite():
        if ecart_relatif >= borne:
            return gravite
    return "FAIBLE"


# ----------------------------------------------------------------- étage C — le juge


def _juge() -> dict:
    return _config().get("juge", {})


@lru_cache(maxsize=1)
def motifs_fermants() -> frozenset[str]:
    """Motifs par lesquels le symbolique a **positivement établi** la compatibilité.

    Une paire qui en porte un est close : le juge ne la voit pas. Tout autre silence — « je
    n'ai pas de grandeur comparable », « pas de modalité » — signifie seulement que l'étage
    A n'avait pas de données, et la paire lui est soumise. C'est cette distinction qui fait
    entrer I11 dans le périmètre et en écarte N06.
    """
    return frozenset(_juge().get("motifs_fermants", []))


@lru_cache(maxsize=1)
def ecarter_les_portees_disjointes() -> bool:
    """Tester la disjonction des portées sur la **paire**, et pas seulement sur le motif.

    Aucun détecteur ne pose `PORTEES_DISJOINTES` quand il s'arrête avant — mesuré sur N04.
    """
    return bool(_juge().get("ecarter_les_portees_disjointes", True))


@lru_cache(maxsize=1)
def max_appels_juge() -> int:
    """Plafond d'appels **réseau** pour l'ensemble du corpus (garde-fou n°5, §7.4)."""
    return int(_juge().get("max_appels", 60))


@lru_cache(maxsize=1)
def echecs_consecutifs_max() -> int:
    """Seuil du coupe-circuit : au-delà, le juge cesse d'appeler et marque le reste."""
    return int(_juge().get("echecs_consecutifs_max", 3))


@lru_cache(maxsize=1)
def confiance_min_juge() -> float:
    """En deçà, un verdict du juge devient une abstention plutôt qu'une affirmation."""
    return float(_juge().get("confiance_min", 0.70))


@lru_cache(maxsize=1)
def temperature_juge() -> float:
    """Température de jugement (architecture.md §12). Entre dans la clé de cache."""
    return float(_juge().get("temperature", 0.2))


@lru_cache(maxsize=1)
def longueur_max_texte() -> int:
    """Caractères de `texte_autonome` injectés par clause — garde-fou de contexte."""
    return int(_juge().get("longueur_max_texte", 600))
