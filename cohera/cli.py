"""Interface en ligne de commande de COHERA.

    cohera doctor                    vérifie config d'extraction, Neo4j, spaCy, embeddings, NLI, LLM
    cohera corpus verifier           segmente le corpus et contrôle les invariants L0
    cohera extraire --jeu fixtures   extrait la Clause Frame de chaque clause (L1, règles)
    cohera graphe charger            applique le schéma et charge le corpus dans Neo4j (L2)
    cohera graphe alias              affiche le pont inter-documents et ses hypothèses
    cohera cibler --jeu fixtures     4 canaux, fusion RRF, comparabilité, budgets (L3)
    cohera evaluer --jeu fixtures    compare rapport.json à la vérité terrain
    cohera torch --backend cpu       bascule la roue PyTorch
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from enum import Enum
from pathlib import Path

import typer

from cohera import diagnostic, reglages

app = typer.Typer(
    help="COHERA — détection d'incohérences inter-documents QHSE.",
    no_args_is_help=True,
    add_completion=False,
)


class Backend(str, Enum):
    cuda = "cuda"
    cpu = "cpu"


def _utf8() -> None:
    """Les messages sont en français : que les accents survivent à la console Windows."""
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")


def _couleur() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _abandonner(message: str, remede: str = "") -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    if remede:
        typer.secho(f"-> {remede}", err=True)
    raise typer.Exit(code=1)


# ------------------------------------------------------------------------- doctor


@app.command()
def doctor(
    llm: str = typer.Option(
        None,
        "--llm",
        help="Profil LLM à tester pour cet appel : local, gemini, groq, openrouter.",
    ),
    device: str = typer.Option(
        None, "--device", help="Force le device torch pour cet appel : auto, cpu, cuda."
    ),
) -> None:
    """Vérifie les cinq dépendances du pipeline. Sort en code 1 si une seule échoue."""
    _utf8()
    if device:
        os.environ["COHERA_DEVICE"] = device

    try:
        reglages.charger()
    except Exception as exc:
        _abandonner(str(exc), "Vérifier config/technique.yaml.")

    typer.echo(diagnostic.entete_environnement())
    typer.echo("")

    verifications = diagnostic.tout_verifier(profil_llm=llm)
    typer.echo(diagnostic.formater_tableau(verifications, couleur=_couleur()))

    echecs = [v for v in verifications if not v.ok]
    typer.echo("")
    if echecs:
        typer.echo(f"{len(echecs)} vérification(s) en échec sur {len(verifications)}.")
        raise typer.Exit(code=1)
    typer.echo(f"Les {len(verifications)} vérifications passent.")


# ------------------------------------------------------------------------- corpus

corpus_app = typer.Typer(help="Inspection du corpus et de la segmentation L0.", no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")


@corpus_app.command("verifier")
def corpus_verifier(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    document: str = typer.Option(None, "--document", help="Ne détailler qu'un document : D1, D2."),
    sortie_json: bool = typer.Option(False, "--json", help="Sortie machine plutôt que tableau."),
    muet: bool = typer.Option(False, "--muet", help="Ne sortir que le verdict, sans le tableau."),
) -> None:
    """Segmente le corpus et contrôle les trois invariants du J1.

    Le compte de clauses, l'alignement des offsets, et la présence de toutes les clauses
    citées par la vérité terrain. C'est aussi la commande qui donne la correspondance
    « numéro de paragraphe → clause_id » annoncée par label.json.
    """
    _utf8()
    from cohera.evaluation.metriques import charger_verite
    from cohera.ingestion import segmenter_jeu

    try:
        segmentations = segmenter_jeu(jeu)
    except (KeyError, FileNotFoundError) as exc:
        _abandonner(str(exc), "Vérifier config/corpus.yaml.")

    try:
        verite = charger_verite(jeu)
    except FileNotFoundError:
        verite = {}

    controles = _controler_segmentation(segmentations, verite)

    if sortie_json:
        typer.echo(json.dumps(controles, ensure_ascii=False, indent=2, default=str))
    else:
        if not muet:
            for doc_id, segmentation in segmentations.items():
                if document and doc_id != document:
                    continue
                typer.echo(_tableau_des_clauses(segmentation))
                typer.echo("")
        typer.echo(_verdict(controles, couleur=_couleur()))

    if controles["echecs"]:
        raise typer.Exit(code=1)


def _controler_segmentation(segmentations: dict, verite: dict) -> dict:
    attendus = {d["id"]: d.get("nb_clauses_attendu") for d in verite.get("documents", [])}
    documents, echecs = [], []

    for doc_id, segmentation in segmentations.items():
        ecarts = segmentation.ecarts_offsets()
        obtenu, attendu = len(segmentation.clauses), attendus.get(doc_id)

        documents.append(
            {
                "doc_id": doc_id,
                "code": segmentation.document.code,
                "clauses": obtenu,
                "attendu": attendu,
                "ecarts_offsets": ecarts,
            }
        )
        if attendu is not None and obtenu != attendu:
            echecs.append(f"{doc_id} : {obtenu} clauses, {attendu} attendues.")
        if ecarts:
            echecs.append(f"{doc_id} : {len(ecarts)} offset(s) désalignés.")

    manquantes = _refs_absentes(segmentations, verite)
    if manquantes:
        echecs.append(f"{len(manquantes)} référence(s) de la vérité terrain sans clause.")

    return {
        "jeu": verite.get("corpus", ""),
        "documents": documents,
        "refs_manquantes": manquantes,
        "correspondance": {
            f"{doc_id} §{clause.ref}": clause.clause_id
            for doc_id, segmentation in segmentations.items()
            for clause in segmentation.clauses
        },
        "echecs": echecs,
    }


def _refs_absentes(segmentations: dict, verite: dict) -> list[str]:
    """Références citées par label.json qu'aucune clause ne porte — le J4 ne pourrait pas
    les apparier."""
    entrees = (
        verite.get("incoherences", [])
        + verite.get("contre_exemples", [])
        + verite.get("limites_connues", [])
    )
    absentes = []
    for entree in entrees:
        for cote in ("clause_a", "clause_b"):
            reference = entree.get(cote)
            if not reference:
                continue
            segmentation = segmentations.get(reference["doc"])
            if segmentation is None or not segmentation.par_ref(reference["ref"]):
                absentes.append(f"{entree['id']} → {reference['doc']} §{reference['ref']}")
    return absentes


def _tableau_des_clauses(segmentation) -> str:
    document = segmentation.document
    lignes = [
        f"{document.doc_id} — {document.code} ({document.type}, niveau "
        f"{document.niveau_hierarchique}) — {len(segmentation.clauses)} clauses",
        "",
        f"{'clause_id':<16} {'ref':<6} {'orig':<8} {'a':<2} texte_source",
        "-" * 100,
    ]
    for clause in segmentation.clauses:
        texte = clause.texte_source.replace("\n", " ")
        if len(texte) > 60:
            texte = texte[:57] + "..."
        lignes.append(
            f"{clause.clause_id:<16} {clause.ref:<6} {clause.origine.value:<8} "
            f"{'*' if clause.autonomise else ' ':<2} {texte}"
        )
    return "\n".join(lignes)


def _verdict(controles: dict, couleur: bool) -> str:
    lignes = []
    for entree in controles["documents"]:
        attendu = entree["attendu"]
        marque = "OK " if attendu is None or entree["clauses"] == attendu else "ÉCART"
        cible = f" / {attendu} attendues" if attendu is not None else ""
        lignes.append(
            f"{marque:<6} {entree['doc_id']} : {entree['clauses']} clauses{cible}, "
            f"{len(entree['ecarts_offsets'])} offset(s) désaligné(s)"
        )
        for ecart in entree["ecarts_offsets"][:5]:
            lignes.append(f"       {ecart}")

    for manquante in controles["refs_manquantes"]:
        lignes.append(f"ÉCART  référence sans clause : {manquante}")

    lignes.append("")
    if controles["echecs"]:
        resume = f"{len(controles['echecs'])} contrôle(s) en échec."
        lignes.append(typer.style(resume, fg=typer.colors.RED) if couleur else resume)
        lignes += [f"  - {echec}" for echec in controles["echecs"]]
        lignes.append("")
        lignes.append(
            "Ne pas corriger le corpus ni label.json : chercher l'écart dans la "
            "segmentation (bloc non détecté, paragraphe fusionné, orphelin qualifié)."
        )
    else:
        resume = "Segmentation conforme : comptes, offsets et références."
        lignes.append(typer.style(resume, fg=typer.colors.GREEN) if couleur else resume)
    return "\n".join(lignes)


# ----------------------------------------------------------------------- extraire

_CHAMPS_COUVERTURE = ("modalite", "quantites", "conditions", "references", "validite", "derogation")


@app.command()
def extraire(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    document: str = typer.Option(None, "--document", help="Ne détailler qu'un document : D1, D2."),
    sortie_json: bool = typer.Option(False, "--json", help="Sortie machine plutôt que tableau."),
    muet: bool = typer.Option(False, "--muet", help="Ne sortir que le bilan, sans le détail."),
    sortie: Path = typer.Option(None, "--sortie", help="Écrit les Clause Frames en JSON à ce chemin."),
) -> None:
    """Extrait la Clause Frame de chaque clause par les règles du J2 (aucun appel LLM).

    Cinq extracteurs indépendants (grandeurs, modalité/force/négation, références,
    conditions, validité/dérogation), fusionnés en une frame par clause. Ce que les
    règles laissent `null` est le travail du J6 (étage LLM) — cette commande ne l'anticipe
    pas.
    """
    _utf8()
    from cohera.extraction.regles import extraire_toutes
    from cohera.ingestion import segmenter_jeu

    try:
        segmentations = segmenter_jeu(jeu)
    except (KeyError, FileNotFoundError) as exc:
        _abandonner(str(exc), "Vérifier config/corpus.yaml.")

    frames = extraire_toutes(segmentations)

    if sortie_json:
        typer.echo(json.dumps(_serialiser(frames), ensure_ascii=False, indent=2))
    else:
        if not muet:
            for doc_id, segmentation in segmentations.items():
                if document and doc_id != document:
                    continue
                typer.echo(_tableau_de_couverture(segmentation, frames))
                typer.echo("")
        typer.echo(_bilan_extraction(frames, couleur=_couleur()))

    if sortie:
        sortie.write_text(json.dumps(_serialiser(frames), ensure_ascii=False, indent=2), encoding="utf-8")
        typer.echo(f"Écrit : {sortie}")


def _serialiser(frames: dict) -> dict:
    return {clause_id: frame.model_dump(mode="json") for clause_id, frame in frames.items()}


def _compte_par_champ(frames: list, champ: str) -> int:
    return sum(1 for frame in frames if frame.source_extraction.get(champ) == "REGLE")


def _tableau_de_couverture(segmentation, frames: dict) -> str:
    document = segmentation.document
    frames_du_doc = [frames[clause.clause_id] for clause in segmentation.clauses]
    lignes = [
        f"{document.doc_id} — {document.code} — {len(frames_du_doc)} clauses",
        "",
        f"{'champ':<12} rempli par règles",
        "-" * 32,
    ]
    for champ in _CHAMPS_COUVERTURE:
        lignes.append(f"{champ:<12} {_compte_par_champ(frames_du_doc, champ)}")
    return "\n".join(lignes)


def _bilan_extraction(frames: dict, couleur: bool) -> str:
    toutes = list(frames.values())
    detail = ", ".join(f"{champ} {_compte_par_champ(toutes, champ)}" for champ in _CHAMPS_COUVERTURE)
    resume = f"{len(toutes)} clauses extraites — {detail}"
    return typer.style(resume, fg=typer.colors.GREEN) if couleur else resume


# ------------------------------------------------------------------------- graphe

graphe_app = typer.Typer(help="Chargement du graphe Neo4j et pont inter-documents.", no_args_is_help=True)
app.add_typer(graphe_app, name="graphe")


def _construire_pont(jeu: str):
    """Segmente, extrait, construit le vocabulaire et le pont. Renvoie le quadruplet."""
    from cohera.extraction.regles import extraire_toutes
    from cohera.graphe.alias import construire_pont
    from cohera.graphe.concepts import extraire_vocabulaire
    from cohera.ingestion import segmenter_jeu

    segmentations = segmenter_jeu(jeu)
    frames = extraire_toutes(segmentations)
    vocabulaire = extraire_vocabulaire(segmentations, frames)
    return segmentations, frames, vocabulaire, construire_pont(vocabulaire)


@graphe_app.command("charger")
def graphe_charger(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    verifier_idempotence: bool = typer.Option(
        False, "--idempotence", help="Charge deux fois et compare les comptages."
    ),
) -> None:
    """Applique le schéma et charge le corpus dans Neo4j — MERGE, jamais CREATE."""
    _utf8()
    from cohera.graphe.alias import ecrire_zone_grise
    from cohera.graphe.chargeur import charger
    from cohera.graphe.connexion import ErreurNeo4j

    try:
        segmentations, frames, vocabulaire, pont = _construire_pont(jeu)
    except (KeyError, FileNotFoundError) as exc:
        _abandonner(str(exc), "Vérifier config/corpus.yaml.")

    try:
        premier = charger(segmentations, frames, vocabulaire, pont)
    except ErreurNeo4j as exc:
        _abandonner(str(exc), exc.remede)

    typer.echo(_tableau_bilan(premier))
    chemin = ecrire_zone_grise(pont)
    typer.echo(f"\nZone grise écrite : {chemin} ({len(pont.zone_grise)} paire(s))")

    if verifier_idempotence:
        second = charger(segmentations, frames, vocabulaire, pont)
        identique = premier.noeuds == second.noeuds and premier.aretes == second.aretes
        typer.echo("")
        if identique:
            typer.secho(
                "Idempotence vérifiée : second chargement, comptages identiques.",
                fg=typer.colors.GREEN if _couleur() else None,
            )
        else:
            typer.secho("ÉCHEC d'idempotence — le second chargement diverge :", fg="red", err=True)
            for cle in sorted(set(premier.noeuds) | set(second.noeuds)):
                if premier.noeuds.get(cle) != second.noeuds.get(cle):
                    typer.echo(f"  nœud {cle} : {premier.noeuds.get(cle)} -> {second.noeuds.get(cle)}")
            for cle in sorted(set(premier.aretes) | set(second.aretes)):
                if premier.aretes.get(cle) != second.aretes.get(cle):
                    typer.echo(f"  arête {cle} : {premier.aretes.get(cle)} -> {second.aretes.get(cle)}")
            raise typer.Exit(code=1)


@graphe_app.command("alias")
def graphe_alias(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    sortie_json: bool = typer.Option(False, "--json", help="Sortie machine plutôt que tableau."),
) -> None:
    """Affiche le pont inter-documents : alias, zone grise, vetos.

    Ce sont les « hypothèses d'alignement » du rapport (J7) : chaque arête est révisable, et
    c'est le premier levier de réglage en cas de dérive de précision.
    """
    _utf8()
    _, _, _, pont = _construire_pont(jeu)

    if sortie_json:
        typer.echo(json.dumps(pont.model_dump(mode="json", exclude={"cosinus"}), ensure_ascii=False, indent=2))
        return

    typer.echo(f"{len(pont.aretes)} alias · {len(pont.zone_grise)} en zone grise · "
               f"{len(pont.vetos)} veto(s) · {len(pont.cosinus)} couples examinés")
    typer.echo("")
    typer.echo(f"{'méthode':<9} {'score':>6}  paire")
    typer.echo("-" * 80)
    for arete in sorted(pont.aretes, key=lambda a: (a.methode.value, -a.score)):
        typer.echo(f"{arete.methode.value:<9} {arete.score:>6.3f}  {arete.libelle_a} = {arete.libelle_b}")

    typer.echo("")
    typer.echo("Zone grise (arbitrage LLM au J6) :")
    for paire in pont.zone_grise:
        typer.echo(f"  {paire.score:>6.3f}  {paire.libelle_a} ~ {paire.libelle_b}")

    typer.echo("")
    typer.echo("Vetos de la liste noire (niveau qui aurait accepté) :")
    for veto in pont.vetos:
        typer.echo(f"  {veto.score:>6.3f}  {veto.libelle_a} / {veto.libelle_b}  -> {veto.niveau_qui_aurait_accepte}")


def _tableau_bilan(bilan) -> str:
    lignes = [f"{'nœuds':<20} n", "-" * 30]
    lignes += [f"{label:<20} {n}" for label, n in sorted(bilan.noeuds.items())]
    lignes += ["", f"{'arêtes':<20} n", "-" * 30]
    lignes += [f"{type_:<20} {n}" for type_, n in sorted(bilan.aretes.items())]
    lignes += ["", f"total : {bilan.total_noeuds} nœuds, {bilan.total_aretes} arêtes"]
    return "\n".join(lignes)


# -------------------------------------------------------------------------- cibler


@app.command()
def cibler(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    rapport: Path = typer.Option(
        Path("rapport.json"), "--rapport", help="Où écrire le rapport de ciblage."
    ),
    sans_pont: bool = typer.Option(
        False, "--sans-pont", help="Ablation : ignorer les alias inter-documents."
    ),
    ablation: bool = typer.Option(
        False, "--ablation", help="Rejouer avec ET sans le pont, et chiffrer l'écart."
    ),
    sortie_json: bool = typer.Option(False, "--json", help="Sortie machine plutôt que tableau."),
) -> None:
    """Cible les paires de clauses à vérifier : 4 canaux, fusion RRF, comparabilité, budgets.

    Suppose le graphe déjà chargé (`cohera graphe charger`) : le ciblage lit le graphe, il ne
    le construit pas. Écrit les `PAIRE_CANDIDATE` — MERGE, jamais CREATE — puis remplit
    `rapport.json`, sur lequel `cohera evaluer` calcule le rappel du ciblage.
    """
    _utf8()
    from cohera.ciblage import cibler as executer_ciblage, identifiant_execution, materialiser
    from cohera.graphe.connexion import ErreurNeo4j
    from cohera.graphe.connexion import session as ouvrir_session

    try:
        segmentations, frames, vocabulaire, pont = _construire_pont(jeu)
    except (KeyError, FileNotFoundError) as exc:
        _abandonner(str(exc), "Vérifier config/corpus.yaml.")

    try:
        with ouvrir_session() as session:
            if ablation:
                _executer_ablation(session, jeu, segmentations, frames, vocabulaire, pont)
                return

            resultat = executer_ciblage(session, frames, avec_pont=not sans_pont)
            ecrites = materialiser(session, resultat, identifiant_execution())
    except ErreurNeo4j as exc:
        _abandonner(str(exc), exc.remede)

    if not resultat.contextes:
        _abandonner(
            "Le graphe ne contient aucune clause : rien à cibler.",
            "Charger le corpus d'abord : cohera graphe charger",
        )

    chemin = _ecrire_rapport_ciblage(rapport, jeu, segmentations, resultat)

    if sortie_json:
        typer.echo(json.dumps(_resume_ciblage(resultat), ensure_ascii=False, indent=2))
    else:
        typer.echo(_tableau_ciblage(resultat, couleur=_couleur()))
        typer.echo("")
        typer.echo(f"{ecrites} PAIRE_CANDIDATE écrites — rapport : {chemin}")


def _resume_ciblage(resultat) -> dict:
    return {
        "paires_theoriques": resultat.paires_theoriques,
        "appariements_par_canal": {c: len(v) for c, v in sorted(resultat.par_canal.items())},
        "fusionnees": len(resultat.fusionnees),
        "ecartees": len(resultat.ecartees),
        "troncatures": len(resultat.troncatures),
        "paires_candidates": len(resultat.candidates),
        "facteur_reduction": round(resultat.facteur_reduction, 4),
    }


def _tableau_ciblage(resultat, couleur: bool) -> str:
    lignes = [f"{'canal':<14} appariements", "-" * 30]
    lignes += [
        f"{canal:<14} {len(liste)}" for canal, liste in sorted(resultat.par_canal.items())
    ]
    lignes += [
        "",
        f"{'union des canaux':<28} {len(resultat.fusionnees)}",
        f"{'écartées (éligibilité, comparabilité)':<28} {len(resultat.ecartees)}",
        f"{'tronquées (budgets)':<28} {len(resultat.troncatures)}",
        "",
    ]
    resume = (
        f"{len(resultat.candidates)} paires candidates sur {resultat.paires_theoriques} "
        f"théoriques — facteur de réduction {resultat.facteur_reduction:.4f}"
    )
    lignes.append(typer.style(resume, fg=typer.colors.GREEN) if couleur else resume)

    # Les motifs de rejet sont une information de qualité, pas un détail : on en montre un
    # échantillon plutôt que de les taire (.claude/rules/detection.md).
    if resultat.ecartees:
        lignes += ["", "Échantillon des paires écartées :"]
        for ecartee in resultat.ecartees[:5]:
            lignes.append(f"  [{ecartee.filtre}] {ecartee.clause_a} / {ecartee.clause_b}")
    return "\n".join(lignes)


def _ecrire_rapport_ciblage(chemin: Path, jeu: str, segmentations: dict, resultat) -> Path:
    """Remplit le contrat d'évaluation : clauses analysées, paires candidates, statistiques."""
    from datetime import date

    from cohera.restitution.rapport_json import (
        DocumentResume,
        PaireCandidate,
        Rapport,
        RefClause,
        Statistiques,
        ecrire_rapport,
    )

    contextes = resultat.contextes

    def reference(clause_id: str) -> RefClause:
        contexte = contextes.get(clause_id)
        return RefClause(
            doc=contexte.doc_id if contexte else "",
            ref=contexte.ref if contexte else "",
            clause_id=clause_id,
        )

    rapport = Rapport(
        corpus=jeu,
        date_execution=date.today(),
        documents=[
            DocumentResume(
                id=doc_id,
                code=segmentation.document.code,
                fichier=segmentation.document.fichier,
                nb_clauses=len(segmentation.clauses),
            )
            for doc_id, segmentation in segmentations.items()
        ],
        statistiques=Statistiques(
            paires_theoriques=resultat.paires_theoriques,
            paires_candidates=len(resultat.candidates),
            facteur_reduction=resultat.facteur_reduction,
        ),
        clauses_analysees=[reference(clause_id) for clause_id in sorted(contextes)],
        paires_candidates=[
            PaireCandidate(
                clause_a=reference(paire.clause_a),
                clause_b=reference(paire.clause_b),
                canaux=[canal.value for canal in paire.canaux],
                score_fusion=paire.score_rrf,
            )
            for paire in resultat.candidates
        ],
    )
    return ecrire_rapport(rapport, chemin)


def _executer_ablation(session, jeu: str, segmentations: dict, frames, vocabulaire, pont) -> None:
    from cohera.evaluation.ablations import ablation_pont, formater_ablation
    from cohera.evaluation.metriques import charger_verite

    correspondance = {
        (doc_id, clause.ref): clause.clause_id
        for doc_id, segmentation in segmentations.items()
        for clause in segmentation.clauses
    }
    resultat = ablation_pont(
        session, frames, charger_verite(jeu), correspondance, vocabulaire, pont
    )
    typer.echo(formater_ablation(resultat, couleur=_couleur()))


# ------------------------------------------------------------------------ evaluer


@app.command()
def evaluer(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de vérité terrain sous corpus/."),
    rapport: Path = typer.Option(
        Path("rapport.json"), "--rapport", help="Rapport à évaluer. Absent = rapport vide."
    ),
    sortie_json: bool = typer.Option(False, "--json", help="Sortie machine plutôt que tableau."),
    strict: bool = typer.Option(
        False, "--strict", help="Sort en code 1 si un critère chiffré du plan 7 jours est manqué."
    ),
) -> None:
    """Compare rapport.json à la vérité terrain : précision, rappel, F1, FP, rappel du ciblage."""
    _utf8()
    from cohera.evaluation import metriques
    from cohera.restitution.rapport_json import charger_rapport

    try:
        verite = metriques.charger_verite(jeu)
    except FileNotFoundError as exc:
        _abandonner(str(exc))

    collisions = metriques.cles_en_collision(verite)
    if collisions:
        typer.secho(
            "Vérité terrain ambiguë — deux entrées partagent une clé d'appariement :", fg="yellow", err=True
        )
        for collision in collisions:
            typer.secho(f"  {collision}", fg="yellow", err=True)

    resultat = metriques.evaluer(charger_rapport(rapport), verite, jeu=jeu)

    if sortie_json:
        typer.echo(json.dumps(resultat.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        if not rapport.is_file():
            typer.secho(
                f"{rapport} est absent : évaluation sur rapport vide (ligne de base).",
                fg="yellow",
            )
            typer.echo("")
        typer.echo(metriques.formater_resultat(resultat, couleur=_couleur()))

    manquees = resultat.cibles_manquees
    if strict and manquees:
        typer.echo("")
        typer.secho(
            f"{len(manquees)} critère(s) chiffré(s) manqué(s) : "
            + ", ".join(c.nom for c in manquees),
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)


# -------------------------------------------------------------------------- torch


@app.command()
def torch(
    backend: Backend = typer.Option(..., "--backend", help="Roue PyTorch à installer."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Affiche la commande sans l'exécuter."),
) -> None:
    """Bascule la roue PyTorch entre CUDA et CPU.

    À ne sortir que pour changer de machine. Au quotidien, la roue CUDA tourne aussi sur
    CPU : COHERA_DEVICE=cpu compare les deux sans rien réinstaller.
    """
    _utf8()
    fichier = reglages.racine_projet() / "requirements" / f"torch-{backend.value}.txt"
    if not fichier.is_file():
        _abandonner(f"Fichier de dépendances introuvable : {fichier}")

    commande = [
        sys.executable, "-m", "pip", "install", "--force-reinstall", "-r", str(fichier)
    ]
    typer.echo(" ".join(commande))

    if dry_run:
        typer.echo("(--dry-run : rien n'a été exécuté)")
        return

    code = subprocess.run(commande, check=False).returncode
    if code != 0:
        raise typer.Exit(code=code)

    typer.echo("")
    typer.echo("Vérifier le résultat : cohera doctor")


if __name__ == "__main__":
    app()
