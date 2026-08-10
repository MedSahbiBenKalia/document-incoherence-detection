"""Harnais d'évaluation : confronter ``rapport.json`` à la vérité terrain.

C'est ce module qui rend la semaine mesurable. Il doit donc être solide avant que quoi
que ce soit ne le nourrisse : au J0 il tourne sur un rapport vide et rend des zéros.

**Clé d'appariement.** Une constatation et une entrée de ``label.json`` désignent la même
chose si elles portent le même couple non ordonné ``{(doc, ref), (doc, ref)}``. Le
``frozenset`` rend l'ordre a/b indifférent : signaler « D1 §4.2 contre D2 §4.2 » ou
l'inverse est le même constat.

**Deux barèmes.** Le barème *global* couvre les 19 incohérences et les 9 contre-exemples.
Le barème *périmètre 7 jours* se restreint aux 12 et 7 que le plan de la semaine vise, et
c'est lui que confrontent les verdicts chiffrés.

Une nuance qui compte : dans le barème 7 jours, une constatation qui tombe sur une vraie
incohérence **hors** périmètre n'est ni un vrai positif, ni un faux positif. La compter en
faux positif punirait le fait d'avoir trouvé mieux que demandé.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cohera import reglages
from cohera.restitution.rapport_json import Constatation, Rapport

#: Un couple ``(doc, ref)`` par clause ; une paire en porte deux, une anomalie
#: mono-clause un seul.
Couple = tuple[str, str]
Cle = frozenset


# ------------------------------------------------------------------ vérité terrain


def chemin_verite(jeu: str = "fixtures") -> Path:
    return reglages.racine_projet() / "corpus" / jeu / "label.json"


def charger_verite(jeu: str = "fixtures") -> dict[str, Any]:
    """Charge ``corpus/<jeu>/label.json``. **Lecture seule** : ce fichier est la spécification."""
    chemin = chemin_verite(jeu)
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Vérité terrain introuvable : {chemin}\n"
            f"Jeux disponibles sous {chemin.parent.parent} ?"
        )
    return json.loads(chemin.read_text(encoding="utf-8"))


def _couple_depuis(brut: Any) -> Couple | None:
    if not isinstance(brut, dict):
        return None
    doc = str(brut.get("doc", "")).strip()
    ref = str(brut.get("ref", "")).strip()
    if not doc and not ref:
        return None
    return (doc, ref)


def cle_entree(entree: dict[str, Any]) -> Cle | None:
    """Clé d'appariement d'une entrée de ``label.json``."""
    couples = [c for c in (_couple_depuis(entree.get("clause_a")), _couple_depuis(entree.get("clause_b"))) if c]
    return frozenset(couples) if couples else None


def cle_constatation(constatation: Constatation) -> Cle:
    """Clé d'appariement d'une constatation de rapport.

    Ne renvoie jamais ``None`` : une constatation sans ``doc``/``ref`` exploitables
    produit une clé qui ne correspondra à rien, donc un faux positif anonyme. C'est
    voulu — une trouvaille non localisable ne peut pas être portée au crédit du système.
    """
    couples = [constatation.clause_a.couple()]
    if constatation.clause_b is not None:
        couples.append(constatation.clause_b.couple())
    return frozenset(couples)


def libelles(cle: Cle) -> list[str]:
    return sorted(f"{doc} §{ref}" for doc, ref in cle)


def cles_en_collision(verite: dict[str, Any]) -> list[str]:
    """Vérifie qu'aucune clé ne désigne deux entrées différentes de la vérité terrain.

    Garde-fou du harnais lui-même : si deux entrées partageaient une clé, un vrai positif
    et un faux positif deviendraient indiscernables, et toutes les métriques mentiraient
    sans qu'un test ne le montre.
    """
    vues: dict[Cle, str] = {}
    collisions: list[str] = []
    for rubrique in ("incoherences", "contre_exemples", "limites_connues"):
        for entree in verite.get(rubrique, []):
            cle = cle_entree(entree)
            if cle is None:
                continue
            identifiant = entree.get("id", "?")
            if cle in vues:
                collisions.append(f"{vues[cle]} et {identifiant} partagent {libelles(cle)}")
            else:
                vues[cle] = identifiant
    return collisions


# ------------------------------------------------------------------------ résultats


class FauxPositif(BaseModel):
    """Une constatation qui ne correspond à aucune incohérence attendue.

    ``id_contre_exemple`` est renseigné quand le piège est identifié (``N01``…) : savoir
    *lequel* des pièges a fonctionné vaut bien plus qu'un compteur.
    """

    id_contre_exemple: str | None = None
    clauses: list[str] = Field(default_factory=list)
    raison: str = ""


class Bareme(BaseModel):
    perimetre: str
    attendues: int = 0
    vrais_positifs: list[str] = Field(default_factory=list)
    faux_negatifs: list[str] = Field(default_factory=list)
    faux_positifs: list[FauxPositif] = Field(default_factory=list)
    precision: float = 0.0
    rappel: float = 0.0
    f1: float = 0.0
    rappel_ciblage: float = 0.0
    ciblage_manquants: list[str] = Field(default_factory=list)

    @property
    def ids_faux_positifs(self) -> list[str]:
        """Identifiants des contre-exemples piégés, dans l'ordre du rapport."""
        return [fp.id_contre_exemple for fp in self.faux_positifs if fp.id_contre_exemple]


class VerdictCible(BaseModel):
    """Un critère chiffré du plan, confronté à la mesure. ``atteint=None`` = non applicable."""

    nom: str
    valeur: str
    cible: str
    atteint: bool | None = None


class ResultatEvaluation(BaseModel):
    jeu: str = "fixtures"
    globale: Bareme = Field(default_factory=lambda: Bareme(perimetre="global"))
    perimetre_7j: Bareme = Field(default_factory=lambda: Bareme(perimetre="périmètre 7 jours"))
    paires_theoriques: int = 0
    paires_candidates: int = 0
    facteur_reduction: float = 0.0
    doublons: list[str] = Field(default_factory=list)
    hors_bareme: list[str] = Field(default_factory=list)
    derogations_attendues: list[str] = Field(default_factory=list)
    derogations_listees: list[str] = Field(default_factory=list)
    cibles: list[VerdictCible] = Field(default_factory=list)

    @property
    def cibles_manquees(self) -> list[VerdictCible]:
        return [c for c in self.cibles if c.atteint is False]


# --------------------------------------------------------------------------- calcul


def _div(numerateur: float, denominateur: float) -> float:
    """Division qui rend 0.0 au lieu d'exploser. C'est le cas du rapport vide."""
    return numerateur / denominateur if denominateur else 0.0


def _bareme(rapport: Rapport, verite: dict[str, Any], *, restreindre: bool) -> Bareme:
    """Calcule un barème. ``restreindre`` limite au périmètre du plan 7 jours."""

    def retenu(entree: dict[str, Any]) -> bool:
        return (not restreindre) or bool(entree.get("dans_perimetre_7j"))

    incoherences_retenues: dict[Cle, str] = {}
    incoherences_ecartees: dict[Cle, str] = {}
    for entree in verite.get("incoherences", []):
        cle = cle_entree(entree)
        if cle is None:
            continue
        cible = incoherences_retenues if retenu(entree) else incoherences_ecartees
        cible[cle] = entree.get("id", "?")

    contre_exemples_retenus: dict[Cle, dict[str, Any]] = {}
    contre_exemples_ecartes: set[Cle] = set()
    for entree in verite.get("contre_exemples", []):
        cle = cle_entree(entree)
        if cle is None:
            continue
        if retenu(entree):
            contre_exemples_retenus[cle] = entree
        else:
            contre_exemples_ecartes.add(cle)

    limites: dict[Cle, str] = {}
    for entree in verite.get("limites_connues", []):
        cle = cle_entree(entree)
        if cle is not None:
            limites[cle] = entree.get("id", "?")

    vrais_positifs: list[str] = []
    faux_positifs: list[FauxPositif] = []

    for constatation in rapport.constatations:
        cle = cle_constatation(constatation)

        if cle in incoherences_retenues:
            identifiant = incoherences_retenues[cle]
            if identifiant not in vrais_positifs:
                vrais_positifs.append(identifiant)
            continue

        if cle in incoherences_ecartees or cle in contre_exemples_ecartes:
            # Vraie incohérence hors périmètre, ou piège hors périmètre : hors barème.
            continue

        if cle in limites:
            # Limite connue, attendue NON détectée : ni crédit, ni pénalité.
            continue

        if cle in contre_exemples_retenus:
            entree = contre_exemples_retenus[cle]
            faux_positifs.append(
                FauxPositif(
                    id_contre_exemple=entree.get("id"),
                    clauses=libelles(cle),
                    raison=entree.get("raison", ""),
                )
            )
        else:
            faux_positifs.append(
                FauxPositif(
                    id_contre_exemple=None,
                    clauses=libelles(cle),
                    raison="Aucune correspondance dans la vérité terrain.",
                )
            )

    faux_negatifs = [i for i in incoherences_retenues.values() if i not in vrais_positifs]

    precision = _div(len(vrais_positifs), len(vrais_positifs) + len(faux_positifs))
    rappel = _div(len(vrais_positifs), len(incoherences_retenues))
    f1 = _div(2 * precision * rappel, precision + rappel)

    cibles_atteintes, cibles_manquees = _ciblage(rapport, verite, restreindre=restreindre)

    return Bareme(
        perimetre="périmètre 7 jours" if restreindre else "global",
        attendues=len(incoherences_retenues),
        vrais_positifs=vrais_positifs,
        faux_negatifs=faux_negatifs,
        faux_positifs=faux_positifs,
        precision=precision,
        rappel=rappel,
        f1=f1,
        rappel_ciblage=_div(len(cibles_atteintes), len(cibles_atteintes) + len(cibles_manquees)),
        ciblage_manquants=cibles_manquees,
    )


def _ciblage(
    rapport: Rapport, verite: dict[str, Any], *, restreindre: bool
) -> tuple[list[str], list[str]]:
    """Quelles incohérences le ciblage a-t-il mises à portée de la cascade ?

    Pour une paire, la question est « la paire figure-t-elle dans les candidates ». Pour
    une anomalie mono-clause (I09, I10, I17, I18), il n'existe aucune paire à cibler : la
    question devient « la clause a-t-elle seulement été segmentée et analysée ». Sans
    cette distinction, la cible ``12/12`` de ``label.json`` serait inatteignable par
    construction, puisque deux des douze n'ont pas de clause_b.
    """
    cles_candidates = {
        frozenset({paire.clause_a.couple(), paire.clause_b.couple()})
        for paire in rapport.paires_candidates
    }
    refs_analysees = {clause.couple() for clause in rapport.clauses_analysees}

    atteintes: list[str] = []
    manquees: list[str] = []

    for entree in verite.get("incoherences", []):
        if restreindre and not entree.get("dans_perimetre_7j"):
            continue
        cle = cle_entree(entree)
        if cle is None:
            continue

        if entree.get("clause_b") is None:
            couple = _couple_depuis(entree.get("clause_a"))
            ok = couple in refs_analysees
        else:
            ok = cle in cles_candidates

        (atteintes if ok else manquees).append(entree.get("id", "?"))

    return atteintes, manquees


# --------------------------------------------------------- lecture des cibles du plan


def _fraction(brut: Any) -> float | None:
    """Lit une cible chiffrée écrite en prose : ``">= 10/12"``, ``">= 0.91"``, ``0``."""
    if brut is None:
        return None
    if isinstance(brut, (int, float)):
        return float(brut)
    texte = str(brut).replace(",", ".")
    fraction = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", texte)
    if fraction:
        return _div(float(fraction.group(1)), float(fraction.group(2)))
    nombre = re.search(r"(\d+(?:\.\d+)?)", texte)
    return float(nombre.group(1)) if nombre else None


def _intervalle(brut: Any) -> tuple[float, float] | None:
    """Lit un intervalle écrit en prose : ``"80 a 140"``."""
    nombres = re.findall(r"\d+(?:\.\d+)?", str(brut).replace(",", "."))
    if len(nombres) >= 2:
        return (float(nombres[0]), float(nombres[1]))
    return None


def _verdicts(
    bareme_7j: Bareme,
    verite: dict[str, Any],
    *,
    paires_candidates: int,
    facteur_reduction: float,
) -> list[VerdictCible]:
    statistiques = verite.get("statistiques_attendues", {})
    cible_plan = verite.get("recapitulatif", {}).get("cible_plan_7_jours", {})
    verdicts: list[VerdictCible] = []

    brut_rappel = cible_plan.get("rappel")
    seuil = _fraction(brut_rappel)
    verdicts.append(
        VerdictCible(
            nom="Rappel (périmètre 7 j)",
            valeur=f"{len(bareme_7j.vrais_positifs)}/{bareme_7j.attendues} = {bareme_7j.rappel:.2f}",
            cible=str(brut_rappel or "—"),
            atteint=None if seuil is None else bareme_7j.rappel >= seuil,
        )
    )

    brut_fp = statistiques.get("faux_positifs_cible", 0)
    verdicts.append(
        VerdictCible(
            nom="Faux positifs (périmètre 7 j)",
            valeur=str(len(bareme_7j.faux_positifs)),
            cible=str(brut_fp),
            atteint=len(bareme_7j.faux_positifs) <= (_fraction(brut_fp) or 0),
        )
    )

    brut_ciblage = cible_plan.get("rappel_ciblage") or statistiques.get("rappel_ciblage_cible")
    seuil = _fraction(brut_ciblage)
    verdicts.append(
        VerdictCible(
            nom="Rappel du ciblage (périmètre 7 j)",
            valeur=f"{bareme_7j.rappel_ciblage:.2f}",
            cible=str(brut_ciblage or "—"),
            atteint=None if seuil is None else bareme_7j.rappel_ciblage >= seuil,
        )
    )

    brut_reduction = statistiques.get("facteur_reduction_cible")
    seuil = _fraction(brut_reduction)
    verdicts.append(
        VerdictCible(
            nom="Facteur de réduction",
            valeur=f"{facteur_reduction:.2f}" if paires_candidates else "aucune paire candidate",
            cible=str(brut_reduction or "—"),
            # Sur un rapport vide, le facteur vaut mécaniquement 1,00 : le déclarer
            # atteint serait un chiffre juste et un mensonge utile à personne.
            atteint=None if not paires_candidates or seuil is None else facteur_reduction >= seuil,
        )
    )

    brut_paires = statistiques.get("paires_candidates_cible")
    bornes = _intervalle(brut_paires)
    verdicts.append(
        VerdictCible(
            nom="Paires candidates",
            valeur=str(paires_candidates),
            cible=str(brut_paires or "—"),
            atteint=None if bornes is None else bornes[0] <= paires_candidates <= bornes[1],
        )
    )

    return verdicts


# ------------------------------------------------------------------------- entrée


def evaluer(rapport: Rapport, verite: dict[str, Any], jeu: str = "fixtures") -> ResultatEvaluation:
    """Compare un rapport à la vérité terrain. Ne lève jamais sur un rapport vide."""
    globale = _bareme(rapport, verite, restreindre=False)
    perimetre = _bareme(rapport, verite, restreindre=True)

    paires_theoriques = rapport.statistiques.paires_theoriques or int(
        verite.get("statistiques_attendues", {}).get("paires_theoriques", 0)
    )
    paires_candidates = len(rapport.paires_candidates) or rapport.statistiques.paires_candidates
    facteur = 1.0 - _div(paires_candidates, paires_theoriques)

    # Doublons : plusieurs constatations sur la même incohérence. Ni crédit
    # supplémentaire, ni pénalité, mais un signal de déduplication à faire au J6.
    comptes: dict[Cle, int] = {}
    for constatation in rapport.constatations:
        cle = cle_constatation(constatation)
        comptes[cle] = comptes.get(cle, 0) + 1
    index_ids = {
        cle_entree(e): e.get("id", "?")
        for e in verite.get("incoherences", [])
        if cle_entree(e) is not None
    }
    doublons = [index_ids.get(cle, str(libelles(cle))) for cle, n in comptes.items() if n > 1]

    # Limites connues détectées malgré tout : hors barème, mais à dire.
    limites = {cle_entree(e): e.get("id", "?") for e in verite.get("limites_connues", [])}
    detectees = {cle_constatation(c) for c in rapport.constatations}
    hors_bareme = [identifiant for cle, identifiant in limites.items() if cle in detectees]

    # Dérogations : N05 attend d'être *listée*, pas *signalée*.
    attendues, listees = _derogations(rapport, verite)

    return ResultatEvaluation(
        jeu=jeu,
        globale=globale,
        perimetre_7j=perimetre,
        paires_theoriques=paires_theoriques,
        paires_candidates=paires_candidates,
        facteur_reduction=facteur,
        doublons=doublons,
        hors_bareme=hors_bareme,
        derogations_attendues=attendues,
        derogations_listees=listees,
        cibles=_verdicts(
            perimetre, verite, paires_candidates=paires_candidates, facteur_reduction=facteur
        ),
    )


def _derogations(rapport: Rapport, verite: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Contre-exemples qui doivent figurer en « dérogations en vigueur », et ceux qui y sont."""
    attendues: dict[Cle, str] = {}
    for entree in verite.get("contre_exemples", []):
        if entree.get("attendu") == "AUCUNE_CONSTATATION_MAIS_LISTEE":
            cle = cle_entree(entree)
            if cle is not None:
                attendues[cle] = entree.get("id", "?")

    presentes: set[Cle] = set()
    for derogation in rapport.derogations_en_vigueur:
        couples = [derogation.clause_a.couple()]
        if derogation.clause_b is not None:
            couples.append(derogation.clause_b.couple())
        presentes.add(frozenset(couples))

    return (
        sorted(attendues.values()),
        sorted(identifiant for cle, identifiant in attendues.items() if cle in presentes),
    )


# ----------------------------------------------------------------------- restitution


def formater_resultat(resultat: ResultatEvaluation, couleur: bool = True) -> str:
    """Rend le résultat d'évaluation en texte lisible en terminal."""
    vert, rouge, jaune, gras, fin = (
        ("\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m") if couleur else ("",) * 5
    )
    lignes: list[str] = []

    def bloc(bareme: Bareme) -> None:
        lignes.append(f"{gras}Barème {bareme.perimetre}{fin}")
        lignes.append(
            f"  précision {bareme.precision:.2f}   rappel {bareme.rappel:.2f}   F1 {bareme.f1:.2f}"
            f"   ({len(bareme.vrais_positifs)} VP / {len(bareme.faux_positifs)} FP"
            f" / {bareme.attendues} attendues)"
        )
        lignes.append(
            f"  rappel du ciblage {bareme.rappel_ciblage:.2f}"
            + (f"   non ciblées : {', '.join(bareme.ciblage_manquants)}" if bareme.ciblage_manquants else "")
        )
        if bareme.faux_negatifs:
            lignes.append(f"  manquées : {', '.join(bareme.faux_negatifs)}")
        for fp in bareme.faux_positifs:
            etiquette = fp.id_contre_exemple or "inconnu"
            teinte = rouge if fp.id_contre_exemple else jaune
            lignes.append(f"  {teinte}faux positif {etiquette}{fin} : {' / '.join(fp.clauses)}")
        lignes.append("")

    lignes.append(f"{gras}Jeu {resultat.jeu}{fin}")
    lignes.append(
        f"  {resultat.paires_candidates} paires candidates sur {resultat.paires_theoriques} théoriques"
        f"   facteur de réduction {resultat.facteur_reduction:.2f}"
    )
    lignes.append("")

    bloc(resultat.globale)
    bloc(resultat.perimetre_7j)

    if resultat.doublons:
        lignes.append(f"Doublons de constatation : {', '.join(resultat.doublons)}")
    if resultat.hors_bareme:
        lignes.append(
            f"Limites connues détectées (hors barème) : {', '.join(resultat.hors_bareme)}"
        )
    if resultat.derogations_attendues:
        manquantes = sorted(set(resultat.derogations_attendues) - set(resultat.derogations_listees))
        etat = "toutes listées" if not manquantes else f"absentes du rapport : {', '.join(manquantes)}"
        lignes.append(f"Dérogations à lister ({', '.join(resultat.derogations_attendues)}) : {etat}")
    if resultat.doublons or resultat.hors_bareme or resultat.derogations_attendues:
        lignes.append("")

    lignes.append(f"{gras}Critères chiffrés du plan 7 jours{fin}")
    largeur_nom = max((len(c.nom) for c in resultat.cibles), default=0)
    largeur_valeur = max((len(c.valeur) for c in resultat.cibles), default=0)
    for cible in resultat.cibles:
        if cible.atteint is None:
            marque, teinte = "n/a ", jaune
        elif cible.atteint:
            marque, teinte = "OK  ", vert
        else:
            marque, teinte = "RATÉ", rouge
        lignes.append(
            f"  {teinte}{marque}{fin}  {cible.nom.ljust(largeur_nom)}  "
            f"{cible.valeur.ljust(largeur_valeur)}  cible {cible.cible}"
        )

    return "\n".join(lignes)
