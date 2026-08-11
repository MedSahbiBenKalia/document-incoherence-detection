"""Encodage vectoriel avec cache disque par hash.

Exigence du J3 (docs/plan-1-semaine.md) : « Embeddings BAAI/bge-m3 sur clauses et concepts,
**avec cache disque par hash** ». Le cache n'est pas un confort : le pont inter-documents
et les canaux 4 et 5 réencodent le même corpus à chaque exécution, et le J7 doit pouvoir
rejouer trois ablations sans repayer le chargement du modèle à chaque fois.

**Le découpage suit la convention du dépôt** (`compat.py`, `schema.py`) : la logique de
cache est séparée du modèle. :func:`encoder` accepte un `encodeur` injectable, ce qui rend
« deux appels sur le même texte ne déclenchent qu'un seul encodage » testable en une
seconde, sans télécharger 2,3 Go.

**Clé de cache.** ``sha256(modèle + "\\0" + texte)`` tronqué. Le nom du modèle en fait
partie : basculer de `bge-m3` à un autre modèle ne doit pas relire des vecteurs de
l'ancien — c'est exactement le genre de panne silencieuse qui donnerait des cosinus
absurdes sans rien signaler. Le séparateur nul empêche que deux couples
(modèle, texte) différents produisent la même concaténation.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from cohera import reglages

#: Longueur de la clé de cache, en caractères hexadécimaux. Aligné sur `Clause.hash`.
LONGUEUR_CLE = 16


def dossier_cache() -> Path:
    """`.cache/embeddings/` à la racine du dépôt. Créé à la demande."""
    return reglages.racine_projet() / ".cache" / "embeddings"


def cle_cache(texte: str, modele: str) -> str:
    """Empreinte stable d'un couple (modèle, texte)."""
    graine = f"{modele}\0{texte}".encode("utf-8")
    return hashlib.sha256(graine).hexdigest()[:LONGUEUR_CLE]


def _chemin_vecteur(cle: str, modele: str) -> Path:
    """Chemin du `.npy` d'une clé, réparti en sous-dossiers.

    Le shardage sur les deux premiers caractères évite un répertoire à plusieurs milliers
    d'entrées, que Windows parcourt lentement.
    """
    slug = modele.replace("/", "_").replace("\\", "_")
    return dossier_cache() / slug / cle[:2] / f"{cle}.npy"


# --------------------------------------------------------------------- modèle réel


@lru_cache(maxsize=2)
def _modele(nom: str, device: str):
    """Charge le modèle une fois par processus. Import différé : ~3 s et 2,3 Go."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(nom, device=device)


def _encodeur_par_defaut(textes: list[str]) -> np.ndarray:
    """Encodage réel, vecteurs **normalisés** : le cosinus se réduit à un produit scalaire.

    Normaliser ici plutôt que chez l'appelant garantit que les vecteurs écrits dans Neo4j
    et ceux comparés en Python sont les mêmes — une divergence donnerait des scores
    d'alias différents entre le graphe et les tests.
    """
    config = reglages.charger().embeddings
    modele = _modele(config.modele, reglages.device_effectif())
    return np.asarray(
        modele.encode(textes, normalize_embeddings=True, batch_size=16),
        dtype=np.float32,
    )


# ------------------------------------------------------------------------- encodage


def encoder(
    textes: Sequence[str],
    *,
    encodeur: Callable[[list[str]], np.ndarray] | None = None,
    modele: str | None = None,
    utiliser_cache: bool = True,
) -> np.ndarray:
    """Vecteurs des `textes`, dans l'ordre, en lisant et alimentant le cache disque.

    Seuls les textes absents du cache sont transmis à l'`encodeur` — c'est la propriété
    que teste « même texte deux fois, un seul encodage ». Les doublons *au sein d'un même
    appel* sont également dédupliqués, ce qui compte sur un corpus où « harnais antichute »
    apparaît dans quatre clauses.

    Renvoie un tableau `(len(textes), dimension)`. Une entrée vide renvoie un tableau vide
    de la bonne forme plutôt que de lever : le corpus peut légitimement ne produire aucun
    concept d'un type donné.
    """
    modele = modele or reglages.charger().embeddings.modele
    encodeur = encodeur or _encodeur_par_defaut
    dimension = reglages.charger().embeddings.dimension

    if not textes:
        return np.empty((0, dimension), dtype=np.float32)

    # Déduplication en conservant l'ordre de première apparition.
    uniques: list[str] = list(dict.fromkeys(textes))
    vecteurs: dict[str, np.ndarray] = {}
    manquants: list[str] = []

    for texte in uniques:
        vecteur = _lire(texte, modele) if utiliser_cache else None
        if vecteur is None:
            manquants.append(texte)
        else:
            vecteurs[texte] = vecteur

    if manquants:
        calcules = np.asarray(encodeur(manquants), dtype=np.float32)
        if calcules.shape[0] != len(manquants):
            raise RuntimeError(
                f"L'encodeur a renvoyé {calcules.shape[0]} vecteur(s) pour "
                f"{len(manquants)} texte(s)."
            )
        for texte, vecteur in zip(manquants, calcules):
            vecteurs[texte] = vecteur
            if utiliser_cache:
                _ecrire(texte, modele, vecteur)

    return np.vstack([vecteurs[texte] for texte in textes])


def encoder_un(texte: str, **kwargs) -> np.ndarray:
    """Le vecteur d'un texte unique."""
    return encoder([texte], **kwargs)[0]


# ------------------------------------------------------------------ accès au disque


def _lire(texte: str, modele: str) -> np.ndarray | None:
    chemin = _chemin_vecteur(cle_cache(texte, modele), modele)
    if not chemin.is_file():
        return None
    try:
        return np.load(chemin)
    except (ValueError, OSError):
        # Fichier tronqué par une interruption : on le traite comme absent plutôt que de
        # faire échouer toute une exécution sur un octet manquant.
        return None


def _ecrire(texte: str, modele: str, vecteur: np.ndarray) -> None:
    chemin = _chemin_vecteur(cle_cache(texte, modele), modele)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # Écriture atomique : un `.npy` à moitié écrit serait relu comme un vecteur valide.
    # `np.save` ajoute lui-même « .npy » quand on lui passe un *chemin* qui ne s'y termine
    # pas — d'où le descripteur ouvert, seule forme qui écrive exactement où on demande.
    provisoire = chemin.with_name(chemin.name + ".tmp")
    with provisoire.open("wb") as flux:
        np.save(flux, vecteur)
    provisoire.replace(chemin)


def vider_cache_disque(modele: str | None = None) -> int:
    """Efface les vecteurs mémorisés. Renvoie le nombre de fichiers retirés."""
    import shutil

    cible = dossier_cache()
    if modele:
        cible = cible / modele.replace("/", "_").replace("\\", "_")
    if not cible.is_dir():
        return 0
    nombre = sum(1 for _ in cible.rglob("*.npy"))
    shutil.rmtree(cible)
    return nombre


def cosinus(a: np.ndarray, b: np.ndarray) -> float:
    """Similarité cosinus de deux vecteurs déjà normalisés.

    Ne renormalise pas : les vecteurs produits ici le sont toujours. Le résultat est borné
    dans [-1, 1] pour absorber les miettes d'arrondi flottant, qui donneraient sinon des
    scores comme 1.0000000002 dans le rapport.
    """
    return float(np.clip(np.dot(a, b), -1.0, 1.0))
