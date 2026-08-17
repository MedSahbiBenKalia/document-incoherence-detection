"""Criticité et arbitrage hiérarchique : quelle clause est fautive, et à quel point.

architecture.md §8.3 :

    criticite = w_type x w_gravite x w_confiance x w_portee x w_hierarchie

**La criticité ordonne, elle ne filtre pas.** C'est la propriété qui compte, et elle est
testée : aucune constatation ne peut tomber à zéro et devenir invisible en fin de rapport.
Une constatation peu sûre doit rester lisible *parce qu*'elle est peu sûre — c'est le rôle
du plancher de confiance.

Tous les poids vivent dans `config/restitution.yaml`, aucun dans ce fichier (`CLAUDE.md`).
Les lectures sont mises en cache : ordonner un rapport consulte ces tables une fois par
constatation et par facteur.

**Deux choses mesurées au J7, et dites plutôt que masquées.**

* L'étage C rend ses constatations **sans gravité** — 7 sur 18 en profil local. Le contrat
  de sortie du juge (architecture.md §7.4) demande un verdict, une confiance et deux
  preuves ; il n'a pas de quoi calculer une gravité, et le lui demander serait lui faire
  inventer un chiffre. La gravité est donc **déduite du type de taxonomie** quand elle
  manque, et jamais quand elle est posée.
* `w_portee` est **neutre**. La portée effective est calculée au J5 mais n'est pas reportée
  sur la constatation : la restitution ne peut pas la lire. C'est une limite, elle est
  écrite dans le YAML et figée par
  `tests/test_criticite.py::test_le_facteur_de_portee_est_neutre_et_c_est_documente`.
"""

from __future__ import annotations

from functools import lru_cache

from cohera import reglages
from cohera.restitution.rapport_json import Constatation


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("restitution").get("criticite", {})


@lru_cache(maxsize=1)
def _arbitrage() -> dict:
    return reglages.charger_config("restitution").get("arbitrage", {})


def _bloc(nom: str) -> dict:
    return _config().get(nom, {})


# ----------------------------------------------------------------- les cinq facteurs


def gravite_effective(constatation: Constatation) -> str:
    """La gravité de la constatation, ou celle que son type implique si elle manque.

    Le repli ne s'applique **qu'à** une gravité absente : une gravité posée par un
    détecteur symbolique n'est jamais écrasée. Sans lui, les constatations de l'étage C
    partiraient toutes au même poids et le tri du rapport ne dirait plus rien.
    """
    if constatation.gravite:
        return constatation.gravite
    defauts = _bloc("gravite").get("defaut_par_type", {})
    return defauts.get(constatation.type, "")


def poids_de_type(constatation: Constatation) -> float:
    bloc = _bloc("type")
    return float(bloc.get("poids", {}).get(constatation.type, bloc.get("defaut", 1.0)))


def poids_de_gravite(constatation: Constatation) -> float:
    bloc = _bloc("gravite")
    return float(bloc.get("poids", {}).get(gravite_effective(constatation), bloc.get("defaut", 1.0)))


def poids_de_confiance(constatation: Constatation) -> float:
    """La confiance du détecteur, bornée par le bas.

    Le plancher n'embellit pas le chiffre : il empêche qu'un facteur nul annule le produit
    entier et fasse passer une constatation pour une absence.
    """
    plancher = float(_bloc("confiance").get("plancher", 0.5))
    return max(plancher, float(constatation.confiance))


def poids_de_portee(constatation: Constatation) -> float:
    """⚠️ Neutre au J7 — la portée effective n'est pas reportée sur la constatation.

    Le facteur reste dans la formule pour que le jour où `portee_effective` remontera du
    verdict jusqu'au rapport, seule cette fonction et son bloc de configuration changent.
    """
    return float(_bloc("portee").get("defaut", 1.0))


def inversion_hierarchique(constatation: Constatation, niveaux: dict[str, int]) -> bool:
    """Le document de niveau **inférieur** est-il le plus permissif ?

    C'est le cas fautif de la pyramide documentaire : une procédure qui relâche ce que la
    politique dont elle dérive impose. L'inverse — une politique plus permissive que sa
    déclinaison — est l'ordre normal d'une `DECLINAISON_PLUS_STRICTE` (N01), et n'est pas
    une inversion.

    Un niveau se lit « 1 = sommet de la pyramide » : le document de niveau **numériquement
    plus grand** est le plus bas dans la hiérarchie.
    """
    if constatation.plus_permissive not in ("A", "B") or constatation.clause_b is None:
        return False

    permissive = constatation.clause_a if constatation.plus_permissive == "A" else constatation.clause_b
    autre = constatation.clause_b if constatation.plus_permissive == "A" else constatation.clause_a

    niveau_permissif = niveaux.get(permissive.doc)
    niveau_autre = niveaux.get(autre.doc)
    if niveau_permissif is None or niveau_autre is None:
        return False
    return niveau_permissif > niveau_autre


def poids_hierarchique(constatation: Constatation, niveaux: dict[str, int]) -> float:
    """×2,0 pour une exigence externe, ×1,5 pour une inversion, ×1,0 sinon.

    Les deux ne se cumulent pas : §8.3 les présente en alternatives, le plus fort l'emporte.
    """
    bloc = _bloc("hierarchie")
    if constatation.cite_norme_externe:
        return float(bloc.get("exigence_externe", 2.0))
    if inversion_hierarchique(constatation, niveaux):
        return float(bloc.get("inversion_hierarchique", 1.5))
    return float(bloc.get("defaut", 1.0))


# ------------------------------------------------------------------- la criticité


def criticite(constatation: Constatation, niveaux: dict[str, int] | None = None) -> float:
    """Le produit des cinq facteurs d'architecture.md §8.3.

    Strictement positif pour toute constatation, y compris dégénérée : c'est ce qui garantit
    qu'ordonner un rapport ne peut jamais en faire disparaître une ligne.
    """
    niveaux = niveaux or {}
    return (
        poids_de_type(constatation)
        * poids_de_gravite(constatation)
        * poids_de_confiance(constatation)
        * poids_de_portee(constatation)
        * poids_hierarchique(constatation, niveaux)
    )


# ------------------------------------------------------------------- l'arbitrage


def clause_fautive(constatation: Constatation, niveaux: dict[str, int] | None = None) -> str:
    """Quelle clause est en cause — et non seulement « ces deux-là divergent ».

    architecture.md §8.3, appliqué à la lettre : « celle du document de niveau inférieur
    **si elle est plus permissive**, celle qui contredit l'exigence externe sinon ; si les
    deux documents sont de même niveau, ``ARBITRAGE_REQUIS`` ».

    ⚠️ **Désigner un fautif est une accusation, et la règle est donc étroite.** Quand la
    clause la plus permissive est celle du document le plus HAUT dans la pyramide, il n'y a
    personne à mettre en cause : une procédure plus stricte que la politique dont elle
    dérive est l'ordre normal d'une `DECLINAISON_PLUS_STRICTE`. La divergence reste une
    constatation — les valeurs diffèrent bel et bien — mais aucune des deux clauses n'est
    fautive, et le rapport doit le dire en ne désignant personne. C'est le cas d'I01 sur ce
    corpus : D1 exige 48 h là où D2 en accorde 5 jours.

    ⚠️ **`plus_permissive` porte deux sémantiques**, héritées des J5 et J6 : A2 y met la
    clause la plus permissive au sens de la monotonie du rôle (un fait), tandis qu'A5 et le
    juge y mettent directement la clause qu'ils tiennent pour fautive (une conclusion).
    Les deux se lisent ici de la même façon — « la clause mise en cause » — et la règle
    hiérarchique ne fait que confirmer ou refuser de confirmer cette mise en cause.
    """
    niveaux = niveaux or {}
    if constatation.clause_b is None:
        return constatation.clause_a.libelle()

    if constatation.plus_permissive not in ("A", "B"):
        return ""

    mise_en_cause = (
        constatation.clause_a if constatation.plus_permissive == "A" else constatation.clause_b
    )
    autre = constatation.clause_b if constatation.plus_permissive == "A" else constatation.clause_a

    # Une exigence externe tranche seule : la clause qui cite le référentiel périmé est
    # fautive quelle que soit la place de son document dans la pyramide (I08).
    if constatation.cite_norme_externe:
        return mise_en_cause.libelle()

    niveau_cause = niveaux.get(mise_en_cause.doc)
    niveau_autre = niveaux.get(autre.doc)
    if niveau_cause is None or niveau_autre is None:
        return ""
    if niveau_cause == niveau_autre:
        return str(_arbitrage().get("etiquette_arbitrage_requis", "ARBITRAGE_REQUIS"))
    if niveau_cause > niveau_autre:  # document plus BAS dans la pyramide, et plus permissif
        return mise_en_cause.libelle()
    return ""


# ------------------------------------------------------------ l'ordre du rapport


def ordonner(
    constatations: list[Constatation], niveaux: dict[str, int] | None = None
) -> list[Constatation]:
    """Renseigne `criticite` et `clause_fautive`, puis trie par criticité décroissante.

    Fonction **pure** : la liste reçue n'est pas modifiée, et **aucune constatation n'est
    perdue** — c'est ce que vérifie `test_ordonner_ne_perd_aucune_constatation`, y compris
    quand les niveaux hiérarchiques sont absents.

    À criticité égale, l'ordre d'entrée est conservé (tri stable de Python) : deux rapports
    produits sur le même corpus se comparent ligne à ligne.
    """
    niveaux = niveaux or {}
    evaluees = [
        constatation.model_copy(
            update={
                "criticite": round(criticite(constatation, niveaux), 4),
                "clause_fautive": clause_fautive(constatation, niveaux),
            }
        )
        for constatation in constatations
    ]
    return sorted(evaluees, key=lambda c: c.criticite, reverse=True)
