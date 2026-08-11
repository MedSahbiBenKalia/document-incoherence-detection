"""Mise en forme d'un libellé de concept avant comparaison.

C'est le niveau 1 de la cascade du pont inter-documents (architecture.md §5.6) :
« minuscules, sans accents ni déterminants, lemmatisée ». Ce module porte la partie
**purement lexicale** ; la lemmatisation, qui exige spaCy, est isolée dans
:func:`lemmatiser_libelle` pour que tout le reste soit testable sans charger un modèle.

Le découpage suit la convention de `compat.py` : la logique qui décide est une fonction
pure, ce qui a besoin d'une ressource lourde est à côté et se contourne en test.

**Deux formes, deux usages, à ne pas confondre.**

- :func:`normaliser_libelle` — forme de *surface* : minuscules, sans accents, sans
  déterminant initial, sans ponctuation. C'est la clé du veto de la liste noire et des
  dictionnaires de configuration. Elle ne dépend d'aucun modèle, donc elle est stable.
- :func:`forme_canonique` — la précédente **plus** la lemmatisation, donc « fiches de
  contrôle » et « fiche de contrôle » s'y confondent. C'est elle, et elle seule, qui décide
  d'un `ALIAS_DE {EXACT}`.

La liste noire est volontairement comparée sur la forme de *surface* : un veto doit être
lisible et prévisible par qui l'écrit dans le YAML, pas dépendre de ce qu'un lemmatiseur
décide un jour de faire de « gants ».
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from cohera import reglages

#: Tout ce qui n'est ni lettre, ni chiffre, ni espace — apostrophes et guillemets compris.
_PONCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)

_ESPACES = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _determinants() -> tuple[str, ...]:
    """Déterminants retirés en tête de libellé, lus depuis `config/lexique_qhse.yaml`.

    Triés du plus long au plus court : « de la » doit être essayé avant « de », sans quoi
    « de la zone » donnerait « la zone ».

    Les déterminants subissent **le même désaccentuage que le libellé** : le YAML les écrit
    en français correct (« présente »), alors que la comparaison se fait sur une forme déjà
    dépouillée (« presente »). Sans cela, aucun déterminant accentué ne serait jamais
    retiré — et l'échec serait silencieux.
    """
    brut = reglages.charger_config("lexique_qhse").get("normalisation", {})
    determinants = brut.get("determinants_initiaux", [])
    depouilles = {sans_accents(d).lower().strip() for d in determinants}
    # L'apostrophe est mangée par la ponctuation en amont : « l' » arrive ici en « l ».
    depouilles = {_PONCTUATION.sub("", d) for d in depouilles if d}
    return tuple(sorted(depouilles, key=len, reverse=True))


def sans_accents(texte: str) -> str:
    """« sécurité » -> « securite ». Décomposition NFD puis retrait des diacritiques."""
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _retirer_determinants_initiaux(texte: str) -> str:
    """Retire les déterminants **en tête**, autant de fois qu'il en reste.

    Boucle plutôt qu'un seul passage : « tout le personnel » en porte deux. La boucle
    s'arrête dès qu'un tour ne retire rien, et ne peut donc pas tourner indéfiniment.
    """
    courant = texte
    while True:
        for determinant in _determinants():
            # L'apostrophe a déjà été mangée par la ponctuation : « l'installation »
            # arrive ici en « l installation », d'où le simple préfixe + espace.
            prefixe = f"{determinant} "
            if courant.startswith(prefixe):
                courant = courant[len(prefixe) :]
                break
        else:
            return courant


def normaliser_libelle(texte: str) -> str:
    """Forme de surface d'un libellé : minuscules, sans accents, sans déterminant initial.

    >>> normaliser_libelle("Le Responsable QSE")
    'responsable qse'
    >>> normaliser_libelle("l'installation")
    'installation'
    >>> normaliser_libelle("  Contrôle   des EPI  ")
    'controle des epi'

    Idempotente : la réappliquer ne change rien, ce que vérifie le test du même nom.
    """
    if not texte:
        return ""
    sans_diacritiques = sans_accents(texte).lower()
    sans_ponctuation = _PONCTUATION.sub(" ", sans_diacritiques)
    compacte = _ESPACES.sub(" ", sans_ponctuation).strip()
    return _retirer_determinants_initiaux(compacte)


def lemmatiser_libelle(texte: str, nlp=None) -> str:
    """Libellé lemmatisé, mot à mot, sur le texte déjà normalisé.

    Sépare « fiches de contrôle » de « fiche de contrôle » — c'est le seul écart que la
    forme de surface ne sait pas absorber, et c'est un alias EXACT attendu par le J3.

    `nlp` est injectable pour les tests ; sans lui, l'analyseur partagé de L0 est réutilisé
    (déjà en cache, aucun coût supplémentaire).
    """
    normalise = normaliser_libelle(texte)
    if not normalise:
        return ""

    if nlp is None:
        from cohera.ingestion.phrases import analyseur

        nlp = analyseur()

    # `sans_accents` a déjà été appliqué : on relemmatise sur la forme sans accents, ce
    # que fr_core_news_lg encaisse sans broncher pour des groupes nominaux courts.
    return " ".join(jeton.lemma_.lower() for jeton in nlp(normalise) if not jeton.is_space)


def forme_canonique(texte: str, nlp=None) -> str:
    """La forme qui décide d'un `ALIAS_DE {EXACT}` : normalisée **et** lemmatisée."""
    return lemmatiser_libelle(texte, nlp=nlp)


def vider_caches() -> None:
    """Oublie les déterminants mémorisés. À appeler après un `monkeypatch` de config."""
    _determinants.cache_clear()
