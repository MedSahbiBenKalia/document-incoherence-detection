"""Lecture de `config/ciblage.yaml` — seuils, poids de fusion, budgets.

Un module dédié, sur le modèle de `graphe/config_alias.py` : un seul endroit lit le fichier,
et les canaux comme la fusion ne connaissent que des fonctions nommées. Aucune valeur métier
ne vit donc dans un `.py` (`CLAUDE.md`).

Les lectures sont mises en cache par :func:`functools.lru_cache` — la configuration ne change
pas en cours d'exécution, et un ciblage complet consulte ces valeurs des milliers de fois.
"""

from __future__ import annotations

from functools import lru_cache

from cohera import reglages
from cohera.ciblage.modeles import Canal
from cohera.extraction.frames import Modalite


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("ciblage")


def _canal(nom: str) -> dict:
    return _config().get("canaux", {}).get(nom, {})


# --------------------------------------------------------------------------- canaux


@lru_cache(maxsize=8)
def canal_actif(canal: Canal) -> bool:
    """Un canal désactivé par configuration ne produit aucun appariement.

    C'est le levier des ablations du J7 (`--sans-canal5`) : couper un canal ne doit pas
    demander de toucher au code.
    """
    return bool(_canal(canal.value.lower()).get("actif", False))


@lru_cache(maxsize=1)
def idf_min() -> float:
    """IDF minimal d'un concept pour qu'il compte comme partage (architecture.md §6.3)."""
    return float(_canal("conceptuel").get("idf_min", 1.5))


@lru_cache(maxsize=1)
def partages_min() -> int:
    """Nombre de concepts partagés exigé par le canal conceptuel."""
    return int(_canal("conceptuel").get("partages_min", 2))


@lru_cache(maxsize=1)
def seuil_vectoriel() -> float:
    """Seuil de cosinus du canal 4.

    Placé au percentile 97,0 de la distribution mesurée sur le corpus ; le détail du
    calibrage et son écart au seuil théorique sont dans `config/ciblage.yaml`.
    """
    return float(_canal("vectoriel").get("seuil", 0.82))


@lru_cache(maxsize=1)
def k_voisins() -> int:
    """Nombre de voisins demandés à l'index vectoriel, avant filtrage inter-documents."""
    return int(_canal("vectoriel").get("k_voisins", 24))


@lru_cache(maxsize=1)
def top_n_dimension() -> int:
    """Nombre de partenaires gardés par clause au canal 5, **sans** seuil de similarité."""
    return int(_canal("dimension").get("top_n", 3))


# --------------------------------------------------------------------- comparabilité


@lru_cache(maxsize=1)
def modalites_prescriptives() -> frozenset[Modalite]:
    """Les modalités qui prescrivent — CONSTAT et DEFINITION en sont absentes."""
    noms = _config().get("comparabilite", {}).get("modalites_prescriptives", [])
    return frozenset(Modalite(nom) for nom in noms)


# ---------------------------------------------------------------- fusion et budgets


@lru_cache(maxsize=1)
def poids_des_canaux() -> dict[Canal, float]:
    """Les poids de la fusion RRF (architecture.md §6.6)."""
    bruts = _config().get("fusion", {}).get("poids", {})
    return {Canal(nom): float(poids) for nom, poids in bruts.items()}


@lru_cache(maxsize=1)
def constante_rrf() -> int:
    """Le ``k`` de la formule RRF. 60 est la valeur usuelle de la littérature."""
    return int(_config().get("fusion", {}).get("k", 60))


@lru_cache(maxsize=1)
def top_k() -> int:
    """Plafond de paires candidates par clause."""
    return int(_config().get("budget", {}).get("top_k", 8))


@lru_cache(maxsize=1)
def canaux_exemptes() -> frozenset[Canal]:
    """Canaux exemptés du plafond : trop précis pour être coupés."""
    return frozenset(Canal(nom) for nom in _config().get("budget", {}).get("canaux_exemptes", []))


@lru_cache(maxsize=1)
def facteur_budget_global() -> int:
    """Le facteur de ``B = facteur × max(n₁, n₂)``."""
    return int(_config().get("budget", {}).get("global_facteur", 4))
