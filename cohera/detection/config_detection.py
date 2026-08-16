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
    """Oublie la configuration mémorisée. À appeler après un `monkeypatch` de config."""
    for fonction in (
        _config, echelle_deontique, ecart_conflit_fort, polarites_opposees,
        objets_partages_min, _seuils_gravite,
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
