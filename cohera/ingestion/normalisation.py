"""Normalisation du texte brut.

Doit préserver la correspondance des offsets avec le texte d'origine :
`texte_origine[debut:fin] == texte_source` pour toute clause. Perdre cet
alignement est irréparable en aval — toutes les preuves du rapport seraient
décalées.

La parade tient en une séparation stricte :

- :func:`lire_texte_origine` est le **seul** endroit où la longueur du texte a le droit
  de changer (BOM, CRLF, NFC). Il s'exécute au chargement du fichier, avant qu'aucun
  offset n'existe, et ce qu'il renvoie devient la référence de tous les offsets ;
- :func:`normaliser` ne fait que des substitutions **caractère pour caractère**. Le texte
  normalisé et le texte d'origine ont donc la même longueur et le même découpage : on peut
  analyser l'un et trancher les preuves dans l'autre.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Substitutions 1:1. Chaque clé est un caractère, chaque valeur en est un aussi — c'est
# la condition qui rend les offsets transportables d'un texte à l'autre.
_SUBSTITUTIONS = {
    # Espaces exotiques : insécable, fine insécable, cadratin, demi-cadratin, fine.
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    # Apostrophes courbes. « L’Animateur » et « L'Animateur » doivent s'apparier.
    "‘": "'",
    "’": "'",
    "ʼ": "'",
    "′": "'",
    # Guillemets droits courbes. Les guillemets FRANÇAIS « » sont volontairement
    # conservés : ils signalent une définition (« anomalie », « zone à risque ») et le
    # J2 s'en sert pour repérer les clauses définitionnelles.
    "“": '"',
    "”": '"',
    "„": '"',
    "″": '"',
    # Tirets. Attention à ne pas toucher au trait d'union ASCII : « PR-QSE-04 » et
    # « au-delà » en dépendent.
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
}

_TABLE = str.maketrans(_SUBSTITUTIONS)

# Séparateur décimal français. Ancré entre deux chiffres, donc « production, de
# maintenance » n'est jamais touché.
_DECIMALE = re.compile(r"(?<=\d),(?=\d)")


def lire_texte_origine(chemin: Path | str) -> str:
    """Lit un `.txt` et renvoie le texte de référence de tous les offsets.

    Trois opérations, toutes susceptibles de changer la longueur, toutes faites ici et
    une seule fois : retrait du BOM, unification des fins de ligne, normalisation NFC.
    Ce qui sort est ce que `Document.texte_origine` conserve et ce dans quoi
    `texte_source` sera tranché.
    """
    brut = Path(chemin).read_text(encoding="utf-8-sig")
    brut = brut.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", brut)


def normaliser(texte: str) -> str:
    """Uniformise espaces, apostrophes, guillemets, tirets et séparateur décimal.

    Idempotente et **strictement conservatrice en longueur** : le résultat s'indexe avec
    les mêmes offsets que l'entrée. C'est ce qui permet d'analyser le texte normalisé tout
    en citant le texte d'origine.
    """
    normalise = _DECIMALE.sub(".", texte.translate(_TABLE))

    if len(normalise) != len(texte):
        raise RuntimeError(
            "La normalisation a changé la longueur du texte "
            f"({len(texte)} → {len(normalise)}) : les offsets ne sont plus alignés. "
            "Toute substitution ajoutée à _SUBSTITUTIONS doit remplacer un caractère "
            "par exactement un caractère."
        )
    return normalise
