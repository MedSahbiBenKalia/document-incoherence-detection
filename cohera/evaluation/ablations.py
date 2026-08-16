"""Ablations : mesurer ce que chaque composant apporte vraiment.

Canal 5 retiré, seuil d'alias abaissé à 0,65 (LIM01 serait détectée mais des
alias erronés apparaîtraient), embeddings CPU contre GPU, LLM local contre
distant.

Le J4 en produit une seule, exigée par le plan : **le rappel du ciblage avec et sans le pont
inter-documents**. Les autres viennent au J7, pilotées par des drapeaux de la CLI.

⚠️ **Ce que cette ablation ablate, et ce qu'elle n'ablate pas.** Le pont intervient à deux
moments, et un seul est réversible à la requête :

* *à la requête* — le canal conceptuel et le calcul des concepts canoniques traversent
  `ALIAS_DE`. C'est ce que `avec_pont=False` supprime.
* *au chargement* — `graphe/chargeur.py::cle_comparaison` remplace chaque terme par le
  représentant canonique de sa classe **avant** d'écrire la clé sur la clause. Rejouer le
  ciblage sans le pont ne défait pas ce calcul : le canal CLE continue de voir les clés
  canonicalisées du J3.

La mesure du canal CLE est donc **optimiste** dans la branche « sans pont ». Plutôt que de
recharger tout le graphe pour la corriger — ce qui rendrait l'ablation lente et destructrice
—, :func:`apport_du_pont_sur_la_cle` la chiffre directement en recalculant les clés en
mémoire, avec et sans pont. Les deux chiffres sont rendus ensemble.
"""

from __future__ import annotations

from typing import Any

from neo4j import Session
from pydantic import BaseModel, Field

from cohera.ciblage import Ciblage, cibler
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.alias import Pont
from cohera.graphe.chargeur import cle_comparaison
from cohera.graphe.concepts import Vocabulaire


class BrancheAblation(BaseModel):
    """Une branche de l'ablation : le ciblage obtenu dans une configuration donnée."""

    nom: str
    paires_candidates: int = 0
    facteur_reduction: float = 0.0
    appariements_par_canal: dict[str, int] = Field(default_factory=dict)
    rappel_ciblage: str = ""
    incoherences_manquees: list[str] = Field(default_factory=list)


class ResultatAblation(BaseModel):
    """Les deux branches, plus le chiffre que la branche « sans pont » ne peut pas voir."""

    avec: BrancheAblation
    sans: BrancheAblation
    #: Paires que le canal CLE ne doit qu'à la canonicalisation faite au chargement.
    paires_cle_dues_au_pont: int = 0
    #: Rappel perdu en retirant le pont, en nombre d'incohérences du périmètre.
    perte_de_rappel: int = 0


# ------------------------------------------------------- la part du pont dans la clé


def apport_du_pont_sur_la_cle(
    clause_ids_par_document: dict[str, list[str]],
    frames: dict[str, ClauseFrame],
    vocabulaire: Vocabulaire,
    pont: Pont,
) -> int:
    """Combien de paires du canal CLE disparaîtraient si la clé n'était pas canonicalisée.

    Recalcule les clés deux fois en mémoire — avec le pont, puis avec un pont vide — et
    compte les paires inter-documents que seule la première version apparie. Aucun accès au
    graphe : c'est une propriété de `cle_comparaison`, pas du chargement.
    """
    def paires(pont_utilise: Pont) -> set[tuple[str, str]]:
        cles = {
            doc_id: {
                clause_id: cle_comparaison(clause_id, frames, vocabulaire, pont_utilise)
                for clause_id in clause_ids
            }
            for doc_id, clause_ids in clause_ids_par_document.items()
        }
        documents = sorted(cles)
        trouvees: set[tuple[str, str]] = set()
        for indice, gauche in enumerate(documents):
            for droite in documents[indice + 1 :]:
                for id_a, cle_a in cles[gauche].items():
                    for id_b, cle_b in cles[droite].items():
                        if cle_a and cle_a == cle_b:
                            trouvees.add((id_a, id_b))
        return trouvees

    return len(paires(pont) - paires(Pont()))


# ---------------------------------------------------------------------- l'ablation


def ablation_pont(
    session: Session,
    frames: dict[str, ClauseFrame],
    verite: dict[str, Any],
    correspondance: dict[tuple[str, str], str],
    vocabulaire: Vocabulaire | None = None,
    pont: Pont | None = None,
) -> ResultatAblation:
    """Rejoue le ciblage avec et sans le pont inter-documents.

    ``correspondance`` traduit un couple ``(doc, ref)`` de `label.json` en ``clause_id`` :
    c'est la même correspondance que produit `cohera corpus verifier`.
    """
    branches = {}
    manquees_par_branche = {}
    for nom, avec_pont in (("avec", True), ("sans", False)):
        ciblage = cibler(session, frames, avec_pont=avec_pont)
        atteintes, manquees = _rappel_ciblage(ciblage, verite, correspondance)
        branches[nom] = BrancheAblation(
            nom=f"{'avec' if avec_pont else 'sans'} pont inter-documents",
            paires_candidates=len(ciblage.candidates),
            facteur_reduction=ciblage.facteur_reduction,
            appariements_par_canal={
                canal: len(liste) for canal, liste in sorted(ciblage.par_canal.items())
            },
            rappel_ciblage=f"{len(atteintes)}/{len(atteintes) + len(manquees)}",
            incoherences_manquees=manquees,
        )
        manquees_par_branche[nom] = manquees

    dues = 0
    if vocabulaire is not None and pont is not None:
        par_document: dict[str, list[str]] = {}
        for (doc, _ref), clause_id in correspondance.items():
            par_document.setdefault(doc, []).append(clause_id)
        dues = apport_du_pont_sur_la_cle(par_document, frames, vocabulaire, pont)

    return ResultatAblation(
        avec=branches["avec"],
        sans=branches["sans"],
        paires_cle_dues_au_pont=dues,
        perte_de_rappel=len(manquees_par_branche["sans"]) - len(manquees_par_branche["avec"]),
    )


def _rappel_ciblage(
    ciblage: Ciblage,
    verite: dict[str, Any],
    correspondance: dict[tuple[str, str], str],
) -> tuple[list[str], list[str]]:
    """Les incohérences du périmètre 7 jours que le ciblage met à portée de la cascade.

    Une anomalie mono-clause (I09, I10) n'a aucune paire à cibler : la question devient « la
    clause a-t-elle été analysée », et la réponse est oui dès qu'elle a un contexte. Sans
    cette distinction, la cible 12/12 serait inatteignable par construction.
    """
    atteintes: list[str] = []
    manquees: list[str] = []

    for entree in verite.get("incoherences", []):
        if not entree.get("dans_perimetre_7j"):
            continue
        a = entree.get("clause_a") or {}
        b = entree.get("clause_b")
        identifiant = entree.get("id", "?")

        id_a = correspondance.get((a.get("doc", ""), a.get("ref", "")))
        if b is None:
            ok = id_a is not None and id_a in ciblage.contextes
        else:
            id_b = correspondance.get((b.get("doc", ""), b.get("ref", "")))
            ok = bool(id_a and id_b and ciblage.est_candidate(id_a, id_b))

        (atteintes if ok else manquees).append(identifiant)

    return atteintes, manquees


def formater_ablation(resultat: ResultatAblation, couleur: bool = True) -> str:
    """Rend l'ablation en tableau lisible — c'est le chiffre que le J4 doit produire."""
    gras, fin = ("\033[1m", "\033[0m") if couleur else ("", "")
    lignes = [
        f"{gras}Ablation — apport du pont inter-documents{fin}",
        "",
        f"{'branche':<28} {'candidates':>11} {'facteur':>8} {'rappel':>8}  manquées",
        "-" * 78,
    ]
    for branche in (resultat.avec, resultat.sans):
        lignes.append(
            f"{branche.nom:<28} {branche.paires_candidates:>11} "
            f"{branche.facteur_reduction:>8.4f} {branche.rappel_ciblage:>8}  "
            + (", ".join(branche.incoherences_manquees) or "—")
        )
    lignes += [
        "",
        f"Perte de rappel en retirant le pont : {resultat.perte_de_rappel} incohérence(s) "
        "du périmètre 7 jours.",
        "",
        "Détail par canal :",
    ]
    canaux = sorted(set(resultat.avec.appariements_par_canal) | set(resultat.sans.appariements_par_canal))
    for canal in canaux:
        avec = resultat.avec.appariements_par_canal.get(canal, 0)
        sans = resultat.sans.appariements_par_canal.get(canal, 0)
        lignes.append(f"  {canal:<12} {avec:>4} -> {sans:>4}")
    lignes += [
        "",
        f"⚠️ Le canal CLE est mesuré de façon optimiste dans la branche « sans pont » : sa clé",
        f"   est canonicalisée au CHARGEMENT, que le ciblage traverse ALIAS_DE ou non.",
        f"   Paires du canal CLE qui disparaîtraient sans cette canonicalisation : "
        f"{resultat.paires_cle_dues_au_pont}.",
    ]
    return "\n".join(lignes)
