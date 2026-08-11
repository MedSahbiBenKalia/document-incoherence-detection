"""La normalisation, et la propriété qui rend l'alignement des offsets possible.

Le piège du J1 : perdre l'alignement pendant la normalisation. La parade tient en une
phrase — `normaliser` ne substitue QUE caractère pour caractère. Tout ce qui pourrait
changer la longueur (BOM, CRLF, NFC) est fait une fois pour toutes par
`lire_texte_origine`, avant qu'aucun offset n'existe.

Les caractères piégeux sont écrits en échappements `\\uXXXX` : un espace insécable et un
espace ordinaire sont indiscernables à l'œil, et un test qu'on ne peut pas relire ne
prouve rien.
"""

from __future__ import annotations

import unicodedata

import pytest

from cohera import reglages
from cohera.ingestion.normalisation import lire_texte_origine, normaliser

FIXTURES = reglages.racine_projet() / "corpus" / "fixtures"

# Formes qu'un export bureautique produit et que les `.txt` du corpus ne contiennent pas
# encore. Elles doivent traverser la normalisation sans décaler un seul caractère.
CAS_FORGES = [
    "Le contrôle doit être fait.",           # U+00A0 espace insécable
    "Le délai est de 24 heures.",                 # U+202F espace fine insécable
    "L’Animateur QSE doit planifier.",                 # U+2019 apostrophe courbe
    "Une tolérance de 4,3 % est admise.",              # virgule décimale
    "Le seuil — fixé en 2024 – tient.",      # U+2014 / U+2013 tirets
    "Il a dit “non” hier.",                       # U+201C / U+201D guillemets courbes
    "« anomalie » et « écart » diffèrent.",  # « » conservés
]


def _textes_du_corpus() -> list[str]:
    return [lire_texte_origine(FIXTURES / nom) for nom in ("file-1.txt", "file-2.txt")]


# ------------------------------------------------------------------- idempotence


@pytest.mark.parametrize("texte", CAS_FORGES)
def test_normaliser_est_idempotent_sur_les_cas_forges(texte: str) -> None:
    assert normaliser(normaliser(texte)) == normaliser(texte)


def test_normaliser_est_idempotent_sur_le_corpus() -> None:
    for texte in _textes_du_corpus():
        assert normaliser(normaliser(texte)) == normaliser(texte)


# ------------------------------------------------- la propriété qui sauve les offsets


@pytest.mark.parametrize("texte", CAS_FORGES)
def test_normaliser_preserve_la_longueur_sur_les_cas_forges(texte: str) -> None:
    assert len(normaliser(texte)) == len(texte)


def test_normaliser_preserve_la_longueur_sur_le_corpus() -> None:
    for texte in _textes_du_corpus():
        assert len(normaliser(texte)) == len(texte)


def test_normaliser_ne_deplace_aucun_saut_de_ligne() -> None:
    """Plus fort que l'égalité des longueurs : les positions des `\\n` sont identiques.

    Un décalage compensé — un caractère ajouté ici, un retiré là — passerait le test de
    longueur en cassant tous les offsets. Les sauts de ligne servent de repères.
    """
    for texte in _textes_du_corpus():
        avant = [i for i, c in enumerate(texte) if c == "\n"]
        apres = [i for i, c in enumerate(normaliser(texte)) if c == "\n"]
        assert avant == apres


# ------------------------------------------------------------ ce qu'elle doit changer


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("24 heures", "24 heures"),
        ("24 heures", "24 heures"),
        ("L’Animateur", "L'Animateur"),
        ("4,3 %", "4.3 %"),
        ("2024 — 2025", "2024 - 2025"),
        ("2024 – 2025", "2024 - 2025"),
        ("“non”", '"non"'),
    ],
)
def test_normaliser_substitue_ce_qui_gene_les_regles(brut: str, attendu: str) -> None:
    assert normaliser(brut) == attendu


@pytest.mark.parametrize(
    "texte",
    [
        "On entend par « anomalie » tout écart.",  # « » : signal de définition
        "les activités de production, de maintenance",       # virgule de liste
        "la norme ISO 45001:2018",
        "l'article R.4321-1 du Code du travail",
        "au-delà de 85 dB(A)",
        "PR-QSE-04 et POL-SEC-01",
    ],
)
def test_normaliser_laisse_intact_ce_qui_porte_du_sens(texte: str) -> None:
    """Le cas négatif. La virgule de « production, de maintenance » n'est pas décimale ;
    les guillemets français signalent une définition, que le J2 exploite ; et le tiret de
    « PR-QSE-04 » n'est pas un tiret cadratin."""
    assert normaliser(texte) == texte


# ---------------------------------------------------------------- lire_texte_origine


def test_lire_texte_origine_retire_le_bom(tmp_path) -> None:
    fichier = tmp_path / "avec_bom.txt"
    fichier.write_bytes("﻿PR-QSE-04\n".encode("utf-8"))
    assert lire_texte_origine(fichier) == "PR-QSE-04\n"


def test_lire_texte_origine_unifie_les_fins_de_ligne(tmp_path) -> None:
    fichier = tmp_path / "crlf.txt"
    fichier.write_bytes(b"une\r\ndeux\rtrois\n")
    assert lire_texte_origine(fichier) == "une\ndeux\ntrois\n"


def test_lire_texte_origine_applique_nfc(tmp_path) -> None:
    """NFC est la SEULE étape autorisée à changer la longueur, et elle s'exécute avant
    qu'aucun offset n'existe."""
    decompose = "équipement"  # « e » + accent aigu combinant
    fichier = tmp_path / "nfd.txt"
    fichier.write_text(decompose, encoding="utf-8")

    lu = lire_texte_origine(fichier)
    assert lu == "équipement"
    assert len(lu) == len(decompose) - 1
    assert unicodedata.is_normalized("NFC", lu)


def test_le_corpus_est_deja_en_nfc() -> None:
    """Constat, pas exigence : il documente pourquoi les offsets tiennent sur ce corpus."""
    for nom in ("file-1.txt", "file-2.txt"):
        brut = (FIXTURES / nom).read_text(encoding="utf-8")
        assert unicodedata.is_normalized("NFC", brut)
        assert lire_texte_origine(FIXTURES / nom) == brut
