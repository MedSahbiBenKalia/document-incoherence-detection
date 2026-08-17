"""`evaluation/historique.csv` — une ligne par exécution, du J4 à aujourd'hui.

`docs/plan-1-semaine.md` §4 : « Une ligne par exécution dans `historique.csv`. **Cette table
est une figure du rapport de stage** : elle raconte l'architecture mieux qu'un paragraphe. »

**La colonne `source` est ce qui rend la table honnête.** Elle distingue :

* ``mesure`` — la ligne vient d'une exécution faite maintenant, dans la configuration du
  jour concerné. Les lignes J4 (ciblage seul) et J5 (étage A seul) sont dans ce cas : ces
  deux configurations se rejouent exactement, l'une par `cohera cibler`, l'autre par
  `cohera detecter --sans-etage-c`. Elles ne sont donc **pas** recopiées du Journal.
* ``journal`` — la ligne est transcrite de `CLAUDE.md`, parce qu'elle n'est plus
  reproductible sans payer : la durée du run distant du J6, par exemple, dépend d'un
  cadençage à 8 s et de 43 appels réseau.

Sans cette distinction, un lecteur ne saurait pas quelles cellules sont des mesures et
lesquelles sont des souvenirs — et une figure dont on ne sait pas cela n'argumente rien.

**Idempotence.** Consigner deux fois la même exécution (même jour, même configuration,
même profil) remplace la ligne au lieu de l'empiler : rejouer les ablations trois fois de
suite ne doit pas donner un CSV de trois fois la même chose.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

COLONNES = [
    "horodatage",
    "jour",
    "configuration",
    "profil",
    "paires_candidates",
    "rappel_ciblage",
    "vrais_positifs",
    "faux_positifs",
    "rappel",
    "precision",
    "f1",
    "appels_llm",
    "duree_s",
    "source",
]

#: La clé d'identité d'une exécution. Deux lignes qui la partagent décrivent la même chose :
#: la seconde remplace la première.
CLE = ("jour", "configuration", "profil")


def _horodatage() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lire(chemin: Path | str) -> list[dict]:
    """Les lignes déjà consignées. Un fichier absent rend une liste vide, pas une erreur."""
    chemin = Path(chemin)
    if not chemin.is_file():
        return []
    with chemin.open(encoding="utf-8", newline="") as flux:
        return list(csv.DictReader(flux))


def consigner(chemin: Path | str, lignes: list[dict]) -> Path:
    """Ajoute ou remplace des lignes, en conservant l'ordre d'apparition.

    Les lignes existantes ne sont pas perdues : seule celle qui partage la clé d'identité
    d'une nouvelle ligne est écrasée.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)

    existantes = lire(chemin)
    index = {tuple(ligne.get(c, "") for c in CLE): rang for rang, ligne in enumerate(existantes)}

    for ligne in lignes:
        complete = {colonne: "" for colonne in COLONNES} | {
            colonne: ligne.get(colonne, "") for colonne in COLONNES
        }
        complete["horodatage"] = complete["horodatage"] or _horodatage()
        cle = tuple(str(complete.get(c, "")) for c in CLE)
        if cle in index:
            existantes[index[cle]] = complete
        else:
            index[cle] = len(existantes)
            existantes.append(complete)

    # La table est une figure : elle se lit du J4 au J7, pas dans l'ordre où les commandes
    # ont été lancées. Le tri est stable, donc deux lignes du même jour gardent leur ordre
    # d'insertion — l'idempotence de la clé n'en dépend pas.
    existantes.sort(key=lambda ligne: str(ligne.get("jour", "")))

    with chemin.open("w", encoding="utf-8", newline="") as flux:
        redacteur = csv.DictWriter(flux, fieldnames=COLONNES)
        redacteur.writeheader()
        redacteur.writerows(existantes)

    return chemin


def _f1(precision: float, rappel: float) -> float:
    return 0.0 if not (precision + rappel) else 2 * precision * rappel / (precision + rappel)


def ligne_depuis_bareme(
    *,
    jour: str,
    configuration: str,
    profil: str = "—",
    paires_candidates: int,
    rappel_ciblage: str,
    vrais_positifs: int,
    faux_positifs: int,
    attendues: int,
    precision: float,
    appels_llm: int | str = 0,
    duree_s: float = 0.0,
    source: str = "mesure",
) -> dict:
    """Fabrique une ligne à partir d'un barème d'évaluation."""
    rappel_numerique = vrais_positifs / attendues if attendues else 0.0
    return {
        "jour": jour,
        "configuration": configuration,
        "profil": profil,
        "paires_candidates": paires_candidates,
        "rappel_ciblage": rappel_ciblage,
        "vrais_positifs": vrais_positifs,
        "faux_positifs": faux_positifs,
        "rappel": f"{vrais_positifs}/{attendues}",
        "precision": f"{precision:.2f}",
        "f1": f"{_f1(precision, rappel_numerique):.2f}",
        "appels_llm": appels_llm,
        "duree_s": f"{duree_s:.1f}" if duree_s else "",
        "source": source,
    }


def ligne_depuis_rapport(
    rapport,
    verite: dict,
    *,
    jour: str,
    configuration: str,
    profil: str,
    duree_s: float = 0.0,
    source: str = "mesure",
) -> dict:
    """Une ligne d'historique tirée d'un `rapport.json` déjà écrit.

    Le nombre d'appels LLM vient des statistiques du rapport lui-même, pas d'un compteur
    tenu à part : c'est ce que l'exécution a réellement coûté. `None` — l'étage C n'a pas
    tourné — s'écrit `0` et non une case vide, parce que zéro appel est une information.
    """
    from cohera.evaluation import metriques

    bareme = metriques.evaluer(rapport, verite).perimetre_7j
    llm = rapport.statistiques_llm

    return ligne_depuis_bareme(
        jour=jour,
        configuration=configuration,
        profil=profil,
        paires_candidates=len(rapport.paires_candidates) or rapport.statistiques.paires_candidates,
        rappel_ciblage=f"{round(bareme.rappel_ciblage * bareme.attendues):d}/{bareme.attendues}",
        vrais_positifs=len(bareme.vrais_positifs),
        faux_positifs=len(bareme.faux_positifs),
        attendues=bareme.attendues,
        precision=bareme.precision,
        appels_llm=llm.appels_reseau if llm is not None else 0,
        duree_s=duree_s,
        source=source,
    )


def consigner_ablations(chemin: Path | str, resultat) -> Path:
    """Consigne les branches d'ablation du J7.

    La branche de référence porte le jour **J5** : à étage A seul, elle *est* la
    configuration du J5, et c'est ce qui permet à la figure du rapport de stage de montrer
    la progression J4 → J5 → J6 sans recopier un seul chiffre du Journal.
    """
    lignes = [
        ligne_depuis_bareme(
            jour="J5",
            configuration="étage A seul (référence des ablations)",
            paires_candidates=resultat.reference.paires_candidates,
            rappel_ciblage=resultat.reference.rappel_ciblage,
            vrais_positifs=resultat.reference.vrais_positifs,
            faux_positifs=resultat.reference.faux_positifs,
            attendues=12,
            precision=resultat.reference.precision,
            duree_s=resultat.reference.duree_s,
        )
    ]
    lignes += [
        ligne_depuis_bareme(
            jour="J7",
            configuration=f"ablation {branche.drapeau}",
            paires_candidates=branche.paires_candidates,
            rappel_ciblage=branche.rappel_ciblage,
            vrais_positifs=branche.vrais_positifs,
            faux_positifs=branche.faux_positifs,
            attendues=12,
            precision=branche.precision,
            duree_s=branche.duree_s,
        )
        for branche in resultat.branches
    ]
    return consigner(chemin, lignes)
