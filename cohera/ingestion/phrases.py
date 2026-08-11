"""Segmentation en phrases (spaCy, avec exceptions) et qualification en clause.

Une phrase devient une clause si elle porte un marqueur déontique, une grandeur, une
référence ou un verbe définitionnel. Sinon elle est rattachée en `contexte` à la clause
précédente : « Ce document est diffusé à l'ensemble des services par voie électronique. »
(CAP08) est une diffusion constatée, pas une exigence.

**Les exceptions comptent autant que le découpage.** Laissé à lui-même, le parser français
insère une frontière de phrase avant le tiret des codes documentaires : « POL-SEC-01 » et
« PR-QSE-02 » éclatent, et avec eux les dérogations D1 §10.1 et §10.2. Le composant
`frontieres_qhse`, inséré **avant** le parser, n'autorise une frontière que sur `.!?` suivi
d'une majuscule, abréviations et initiales exclues.
"""

from __future__ import annotations

import re
from functools import lru_cache

from spacy.language import Language
from spacy.tokens import Doc, Span

from cohera import reglages


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("segmentation")


@lru_cache(maxsize=1)
def _qualification() -> dict:
    return reglages.charger_config("lexique_qhse")["qualification"]


# ------------------------------------------------------------------ frontières de phrase


@lru_cache(maxsize=1)
def _abreviations() -> frozenset[str]:
    return frozenset(a.lower() for a in _config()["phrases"]["abreviations"])


@Language.component("frontieres_qhse")
def frontieres_qhse(doc: Doc) -> Doc:
    """Fixe les frontières de phrase avant que le parser ne s'en mêle.

    Une frontière n'est ouverte que sur `.!?` suivi d'une majuscule. Elle est refusée si
    le jeton qui précède la ponctuation est une abréviation connue, une initiale ou un
    nombre — « art. 5 », un article de code réglementaire, un renvoi « § 12.3 », une norme
    datée.
    """
    initiales = _config()["phrases"]["initiales_insecables"]
    abreviations = _abreviations()

    for indice, jeton in enumerate(doc):
        if indice == 0:
            jeton.is_sent_start = True
            continue

        precedent = doc[indice - 1]
        if precedent.text not in ".!?" or not jeton.text[:1].isupper():
            jeton.is_sent_start = False
            continue

        avant = doc[indice - 2] if indice >= 2 else None
        insecable = avant is not None and (
            avant.text.lower() in abreviations
            or avant.text.isdigit()
            or (initiales and len(avant.text) == 1 and avant.text.isalpha())
        )
        jeton.is_sent_start = not insecable

    return doc


@lru_cache(maxsize=1)
def analyseur() -> Language:
    """Le modèle spaCy du projet, chargé une fois, muni de ses exceptions de découpage."""
    import spacy

    nlp = spacy.load(reglages.charger().spacy.modele)
    if "frontieres_qhse" not in nlp.pipe_names:
        nlp.add_pipe("frontieres_qhse", before="parser")
    return nlp


def phrases_de(doc: Doc) -> list[Span]:
    """Les phrases non vides du document analysé."""
    return [phrase for phrase in doc.sents if phrase.text.strip()]


def decouper_en_phrases(texte: str) -> list[tuple[int, int, str]]:
    """`[(debut, fin, texte)]`, offsets relatifs au texte fourni, blancs rognés."""
    return [_rogner(phrase) for phrase in phrases_de(analyseur()(texte))]


def _rogner(phrase: Span) -> tuple[int, int, str]:
    brut = phrase.text
    tete = len(brut) - len(brut.lstrip())
    debut = phrase.start_char + tete
    fin = phrase.start_char + len(brut.rstrip())
    return debut, fin, brut.strip()


# ------------------------------------------------------------------------- autonomie


@lru_cache(maxsize=1)
def _dependances_sujet() -> frozenset[str]:
    return frozenset(_config()["anaphores"]["dependances_sujet"])


def est_autonome(phrase: Span) -> bool:
    """Un verbe conjugué **et** un sujet : la phrase se tient toute seule.

    Ce qui échoue à ce test — « Dérogation motivée par la nature répétitive des
    opérations, approuvée par le Directeur de site… » — est un complément, pas un énoncé
    normatif. Il prolonge la clause voisine au lieu d'en ouvrir une nouvelle.
    """
    fini = any("VerbForm=Fin" in str(jeton.morph) for jeton in phrase)
    sujet = any(jeton.dep_ in _dependances_sujet() for jeton in phrase)
    return fini and sujet


def grouper_en_clauses(doc: Doc) -> list[tuple[int, int]]:
    """Regroupe les phrases d'un paragraphe en empans de clause : un par phrase autonome.

    Les fragments se raccrochent à la clause précédente, ou à la suivante s'il n'y en a
    pas encore — c'est le cas de D1 §10.2, dont le premier morceau (« Par dérogation à la
    procédure PR-QSE-02 § 3.1 ») précède le seul énoncé conjugué du paragraphe.

    Un paragraphe dont aucune phrase n'est autonome reste **une** clause : le parser rate
    parfois le sujet (D1 §4.2, D2 §8.1), et perdre la clause serait bien pire que de la
    garder entière.
    """
    phrases = [_rogner(phrase) for phrase in phrases_de(doc)]
    if not phrases:
        return []

    autonomes = [est_autonome(phrase) for phrase in phrases_de(doc)]
    if not any(autonomes):
        return [(phrases[0][0], phrases[-1][1])]

    groupes: list[list[int]] = []
    en_attente: int | None = None

    for (debut, fin, _), autonome in zip(phrases, autonomes):
        if autonome:
            groupes.append([en_attente if en_attente is not None else debut, fin])
            en_attente = None
        elif groupes:
            groupes[-1][1] = fin
        elif en_attente is None:
            en_attente = debut

    if en_attente is not None:
        groupes.append([en_attente, phrases[-1][1]])

    return [(debut, fin) for debut, fin in groupes]


# ---------------------------------------------------------------------- qualification


@lru_cache(maxsize=1)
def _motifs_de_qualification() -> tuple[re.Pattern, ...]:
    config = _qualification()
    motifs = [re.escape(m) for m in config["marqueurs_deontiques"]]
    motifs += [re.escape(v) for v in config["verbes_definitionnels"]]
    compiles = [re.compile(rf"\b{m}\b", re.IGNORECASE) for m in motifs]
    compiles.append(re.compile(config["motif_terme_defini"]))
    compiles += [re.compile(m, re.IGNORECASE) for m in config["motifs_reference"]]
    compiles += [re.compile(m, re.IGNORECASE) for m in config["motifs_grandeur"]]
    return tuple(compiles)


def qualifier(texte: str) -> bool:
    """La phrase porte-t-elle une exigence, une valeur, un renvoi ou une définition ?

    Appliquée aux unités **non numérotées** : dans un document QHSE structuré, la
    numérotation est elle-même le signal normatif, et un paragraphe « 7.2 » est une clause
    qu'il porte ou non un modal. La fonction reste écrite pour le cas général — c'est elle
    qui fait tout le travail en repli « document plat ».
    """
    return any(motif.search(texte) for motif in _motifs_de_qualification())
