"""Détection et explosion des blocs tabulaires (CAP03).

Les matrices de responsabilité (RACI) et les tableaux de périodicité QHSE portent des
exigences qu'aucun découpage en phrases ne verrait : « Approbation du plan de prévention |
Animateur QSE | Responsable QSE » n'a ni verbe ni modalité, mais désigne un approbateur —
et c'est exactement ce que I07 oppose au « Directeur de site » de D2.

La ligne d'en-tête donne les rôles et **n'est pas une clause**.
"""

from __future__ import annotations

from functools import lru_cache

from cohera import reglages
from cohera.ingestion.structure import Ligne, Unite


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("segmentation")["tableau"]


def _est_ligne_de_tableau(ligne: Ligne) -> bool:
    config = _config()
    return ligne.texte.count(config["separateur"]) >= config["min_separateurs"]


def detecter(unite: Unite) -> tuple[Ligne, list[Ligne]] | None:
    """Renvoie `(en-tête, lignes de données)` si l'unité contient un tableau, `None` sinon.

    Exige `min_lignes` lignes alignées consécutives : « a | b » isolé est une coïncidence
    typographique bien plus souvent qu'un tableau.
    """
    config = _config()
    alignees = [ligne for ligne in unite.lignes if _est_ligne_de_tableau(ligne)]
    if len(alignees) < config["min_lignes"]:
        return None
    if not config["premiere_ligne_est_entete"]:
        return alignees[0], alignees
    return alignees[0], alignees[1:]


def _cellules(ligne: Ligne) -> list[str]:
    separateur = _config()["separateur"]
    return [cellule.strip() for cellule in ligne.texte.split(separateur)]


def exploser(unite: Unite, texte_origine: str) -> list[dict]:
    """Une clause par ligne de données, avec les rôles de l'en-tête en attributs.

    `texte_source` est la ligne **littérale** — c'est sous cette forme que la vérité
    terrain cite I07. Le texte de travail, lui, est recomposé en phrase lisible pour que
    le plongement et le NLI aient quelque chose à se mettre sous la dent.
    """
    detecte = detecter(unite)
    if detecte is None:
        return []

    entete, donnees = detecte
    colonnes = _cellules(entete)
    produites = []

    for ligne in donnees:
        valeurs = _cellules(ligne)
        attributs = {
            colonne: valeur
            for colonne, valeur in zip(colonnes, valeurs)
            if colonne and valeur
        }

        decalage = len(ligne.texte) - len(ligne.texte.lstrip())
        debut = ligne.debut + decalage
        fin = ligne.debut + len(ligne.texte.rstrip())

        produites.append(
            {
                "debut": debut,
                "fin": fin,
                "texte_source": texte_origine[debut:fin],
                "texte_autonome": _recomposer(colonnes, valeurs),
                "attributs": attributs,
            }
        )
    return produites


def _recomposer(colonnes: list[str], valeurs: list[str]) -> str:
    """« Contrôle périodique des EPI - Réalisation : Animateur QSE ; Approbation : … »

    La première colonne porte l'objet, les suivantes des rôles. Sans cette remise en
    phrase, la ligne est un sac de mots que le vectoriel apparie n'importe comment.
    """
    if not valeurs:
        return ""
    roles = [
        f"{colonne} : {valeur}"
        for colonne, valeur in zip(colonnes[1:], valeurs[1:])
        if colonne and valeur
    ]
    if not roles:
        return valeurs[0]
    return f"{valeurs[0]} - " + " ; ".join(roles) + "."
