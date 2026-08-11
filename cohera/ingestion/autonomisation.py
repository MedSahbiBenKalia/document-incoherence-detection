"""Autonomisation des anaphores, par règle (CAP01) — aucun appel LLM.

Le NLI et le juge LLM voient une paire **hors de son document**. « Il est archivé pendant
3 ans. » y est inexploitable : ni sujet, ni objet, rien à apparier. C'est la condition de
I03, et c'est pour cela que CAP01 en fait une capacité requise.

`architecture.md` §3.3 confie cette étape à Mistral 7B. Le plan 7 jours la fait **par
règle** : si la clause commence par un pronom, on reprend le sujet de la clause précédente.
Écart assumé, à mentionner dans le rapport — sur un corpus de PoC la règle suffit, et elle
est vérifiable, ce qu'un appel de modèle n'est pas.

On ne réécrit que ce qui en a besoin. Une réécriture systématique fabriquerait des sujets
faux partout, et personne ne le verrait : `texte_source` reste juste, seul le texte de
travail dérive.
"""

from __future__ import annotations

import re
from functools import lru_cache

from spacy.tokens import Doc, Span

from cohera import reglages


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("segmentation")["anaphores"]


@lru_cache(maxsize=1)
def _motif_anaphore() -> re.Pattern:
    return re.compile(_config()["motif"], re.IGNORECASE)


@lru_cache(maxsize=1)
def _dependances_sujet() -> frozenset[str]:
    return frozenset(_config()["dependances_sujet"])


def besoin_autonomisation(texte: str, doc: Doc) -> bool:
    """La clause perd-elle son sujet dès qu'on la sort de son document ?

    Deux signaux, celui d'`architecture.md` §3.3 à la lettre : une ouverture pronominale,
    ou l'absence de tout sujet dans l'arbre de dépendances.
    """
    if _motif_anaphore().match(texte):
        return True
    return not any(jeton.dep_ in _dependances_sujet() for jeton in doc)


def sujet_nominal(doc: Doc) -> Span | None:
    """Le groupe nominal sujet, sous-arbre complet : « Le registre de contrôle des EPI ».

    Renvoie `None` si le sujet est lui-même un pronom — reprendre « Il » pour résoudre
    « Il » ne résoudrait rien.
    """
    for jeton in doc:
        if jeton.dep_ not in _dependances_sujet():
            continue
        if jeton.pos_ not in ("NOUN", "PROPN"):
            continue
        return doc[jeton.left_edge.i : jeton.right_edge.i + 1]
    return None


def _accorde(pronom, tete) -> bool:
    """Le pronom et l'antécédent s'accordent-ils en genre et en nombre ?

    Départage « Il » (le registre) de « Elle » (la procédure) quand plusieurs clauses
    précèdent. Un trait absent ne disqualifie pas : mieux vaut un antécédent plausible
    qu'aucun.
    """
    for trait in ("Gender", "Number"):
        attendu = pronom.morph.get(trait)
        candidat = tete.morph.get(trait)
        if attendu and candidat and attendu != candidat:
            return False
    return True


def antecedent(doc: Doc, precedents: list[Doc]) -> Span | None:
    """Cherche l'antécédent en remontant les clauses précédentes, la plus proche d'abord.

    La portée est bornée par `portee_arriere_max` : au-delà, un sujet lointain est une
    supposition, pas une résolution.
    """
    pronom = doc[0]
    portee = _config()["portee_arriere_max"]

    candidats = []
    for precedent in reversed(precedents[-portee:]):
        sujet = sujet_nominal(precedent)
        if sujet is None:
            continue
        if _accorde(pronom, sujet.root):
            return sujet
        candidats.append(sujet)

    # Aucun accord trouvé : on prend le plus proche plutôt que de renoncer, l'étiquetage
    # morphologique n'étant pas infaillible.
    return candidats[0] if candidats else None


def autonomiser(texte: str, doc: Doc, precedents: list[Doc]) -> str | None:
    """Réécrit le texte de travail en substituant l'antécédent au pronom initial.

    « Il est archivé pendant 3 ans. »
    → « Le registre de contrôle des EPI est archivé pendant 3 ans. »

    Renvoie `None` quand la réécriture n'est ni possible ni souhaitable — et ce n'est pas
    un échec : la clause reste utilisable telle quelle, simplement moins autoportante.
    """
    trouve = _motif_anaphore().match(texte)
    if not trouve:
        return None

    # « Ce », « Cette », « Ces » suivis d'un nom sont des déterminants, pas des pronoms :
    # « Ces équipements sont retirés » ne doit pas devenir « La procédure équipements ».
    if doc[0].pos_ != "PRON":
        return None

    remplacement = antecedent(doc, precedents)
    if remplacement is None:
        return None

    reecrit = remplacement.text + texte[trouve.end(1) :]
    return reecrit if reecrit != texte else None
