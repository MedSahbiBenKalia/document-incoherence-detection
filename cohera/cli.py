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
    from cohera.graphe.conditions import construire_algebre, ecrire_file_attente
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

    # L'algèbre des conditions est déjà matérialisée par `charger` ; on la reconstruit ici
    # — fonction pure, quelques millisecondes — pour en écrire la file d'attente, que le J6
    # arbitrera au LLM comme il arbitrera la zone grise des alias.
    algebre = construire_algebre(frames)
    chemin = ecrire_file_attente(algebre)
    typer.echo(
        f"Algèbre des conditions : {len(algebre.conditions)} condition(s) distincte(s), "
        f"{len(algebre.aretes)} arête(s) {algebre.par_relation}"
    )
    typer.echo(
        f"File d'attente J6 écrite : {chemin} ({len(algebre.indeterminees)} paire(s))"
    )

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


@app.command()
def detecter(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    rapport: Path = typer.Option(
        Path("rapport.json"), "--rapport", help="Où écrire le rapport complet."
    ),
    profil_llm: str = typer.Option(
        None, "--llm", help="Profil LLM pour l'étage C : local, gemini, groq, openrouter."
    ),
    sans_etage_c: bool = typer.Option(
        False, "--sans-etage-c", help="Ablation : étage A seul, aucun appel LLM."
    ),
    sans_arbitrage: bool = typer.Option(
        False, "--sans-arbitrage", help="Ne pas arbitrer la zone grise des alias."
    ),
    budget: int = typer.Option(
        None, "--budget", help="Plafond d'appels réseau. Défaut : config/detection.yaml."
    ),
    sortie_json: bool = typer.Option(False, "--json", help="Sortie machine plutôt que tableau."),
) -> None:
    """Cascade complète : arbitrage des alias, ciblage, étage A symbolique, étage C juge.

    Suppose le graphe déjà chargé (`cohera graphe charger`). Écrit `rapport.json` avec les
    constatations, les **abstentions nommées**, les hypothèses d'alias et les compteurs LLM.

    **Sort toujours en code 0 avec un rapport complet**, même si le plafond de budget est
    atteint ou si le LLM est injoignable : ces deux cas dégradent le rapport, ils ne
    l'interrompent pas. Un code non nul signale une erreur d'usage — corpus absent, profil
    inconnu, graphe vide.
    """
    _utf8()
    from cohera.ciblage import cibler as executer_ciblage
    from cohera.detection.cascade import detecter as executer_cascade
    from cohera.detection.objets import objets_canoniques
    from cohera.graphe.arbitrage_alias import arbitrer_la_zone_grise
    from cohera.graphe.conditions import construire_algebre
    from cohera.graphe.connexion import ErreurNeo4j
    from cohera.graphe.connexion import session as ouvrir_session

    if profil_llm:
        os.environ["COHERA_LLM"] = profil_llm

    try:
        segmentations, frames, vocabulaire, pont = _construire_pont(jeu)
    except (KeyError, FileNotFoundError) as exc:
        _abandonner(str(exc), "Vérifier config/corpus.yaml.")

    compteurs = None
    arbitrage = None
    if not sans_etage_c and not sans_arbitrage:
        from cohera import llm as transport_llm

        compteurs = transport_llm.Compteurs()
        try:
            arbitrage, _ = arbitrer_la_zone_grise(
                pont, vocabulaire=vocabulaire, compteurs=compteurs
            )
        except KeyError as exc:  # profil LLM inconnu : faute d'usage, pas une panne
            _abandonner(str(exc), "Profils déclarés dans config/technique.yaml (llm.profils).")

    try:
        with ouvrir_session() as session:
            ciblage = executer_ciblage(session, frames)
    except ErreurNeo4j as exc:
        _abandonner(str(exc), exc.remede)

    if not ciblage.contextes:
        _abandonner(
            "Le graphe ne contient aucune clause : rien à détecter.",
            "Charger le corpus d'abord : cohera graphe charger",
        )

    clauses = {c.clause_id: c for s in segmentations.values() for c in s.clauses}
    textes = {c.clause_id: c.texte_source for c in clauses.values()}
    algebre = construire_algebre(frames)

    detection = executer_cascade(ciblage, frames, textes, vocabulaire, pont, algebre)

    juge = None
    if not sans_etage_c:
        from cohera.detection.juge_llm import juger

        objets = {
            clause_id: objets_canoniques(clause_id, vocabulaire, pont) for clause_id in clauses
        }
        niveaux = {
            doc_id: segmentation.document.niveau_hierarchique
            for doc_id, segmentation in segmentations.items()
            if getattr(segmentation.document, "niveau_hierarchique", None) is not None
        }
        # Le score de fusion décide de l'ORDRE de soumission : si le plafond mord, il mord
        # les paires que le ciblage juge les moins prometteuses, pas la fin de l'alphabet.
        scores = {
            frozenset((paire.clause_a, paire.clause_b)): paire.score_rrf
            for paire in ciblage.candidates
        }
        juge = juger(
            detection, clauses, frames, textes, algebre, objets,
            niveaux=niveaux, scores=scores, budget=budget, compteurs=compteurs,
        )

    chemin = _ecrire_rapport_detection(
        rapport, jeu, segmentations, ciblage, detection, juge, arbitrage,
        frames=frames, vocabulaire=vocabulaire, pont=pont,
    )

    if sortie_json:
        typer.echo(json.dumps(_resume_detection(detection, juge), ensure_ascii=False, indent=2))
    else:
        typer.echo(_tableau_detection(detection, juge, arbitrage, couleur=_couleur()))
        typer.echo("")
        typer.echo(f"rapport : {chemin}")


def _resume_detection(detection, juge) -> dict:
    resume = {
        "paires_examinees": detection.paires_examinees,
        "clauses_examinees": detection.clauses_examinees,
        "constatations": len(detection.constatations),
        "specialisations": len(detection.specialisations),
        "escalades": len(detection.escalades),
        "abstentions": len(detection.abstentions),
        "muets": len(detection.muets),
    }
    if juge is not None:
        resume["etage_c"] = {
            "paires_soumises": juge.paires_soumises,
            "appels_reseau": juge.compteurs.appels_reseau,
            "servis_par_cache": juge.compteurs.servis_par_cache,
            "verdicts_annules": juge.verdicts_annules,
            "taux_annulation": round(juge.taux_annulation, 4),
            "non_verifiees_budget": juge.non_verifiees_budget,
            "non_verifiees_service": juge.non_verifiees_service,
            "coupe_circuit": juge.coupe_circuit,
        }
    return resume


def _tableau_detection(detection, juge, arbitrage, couleur: bool) -> str:
    lignes = [
        f"{'constatations':<24} {len(detection.constatations)}",
        f"{'spécialisations':<24} {len(detection.specialisations)}",
        f"{'escalades restantes':<24} {len(detection.escalades)}",
        f"{'abstentions':<24} {len(detection.abstentions)}",
        f"{'muets (rejets motivés)':<24} {len(detection.muets)}",
    ]

    if arbitrage is not None:
        retenus = len(arbitrage.aretes_ajoutees)
        lignes += [
            "",
            f"zone grise : {len(arbitrage.arbitrages)} paires arbitrées, "
            f"{retenus} alias retenus, {arbitrage.abstentions} abstentions",
        ]

    if juge is not None:
        lignes += [
            "",
            f"{'étage C — soumises':<24} {juge.paires_soumises}",
            f"{'appels réseau':<24} {juge.compteurs.appels_reseau}",
            f"{'servis par le cache':<24} {juge.compteurs.servis_par_cache}",
            f"{'verdicts annulés':<24} {juge.verdicts_annules} "
            f"({juge.taux_annulation:.1%} des réponses)",
        ]
        # Une dégradation ne casse pas la commande, mais elle ne doit pas passer inaperçue.
        # Budget et panne de service sont distingués : l'un se corrige en payant, l'autre non.
        for nombre, cause in (
            (juge.non_verifiees_budget, "plafond de budget atteint"),
            (juge.non_verifiees_service, "service injoignable, coupe-circuit"),
        ):
            if nombre:
                alerte = (
                    f"⚠ {nombre} paires NON VÉRIFIÉES ({cause}) — "
                    f"nommées dans le rapport, pas rejetées"
                )
                lignes.append(typer.style(alerte, fg=typer.colors.YELLOW) if couleur else alerte)
        if juge.echecs_transport:
            alerte = f"⚠ {juge.echecs_transport} échecs de transport"
            lignes.append(typer.style(alerte, fg=typer.colors.YELLOW) if couleur else alerte)

    return "\n".join(lignes)


def _ecrire_rapport_detection(
    chemin: Path,
    jeu: str,
    segmentations: dict,
    ciblage,
    detection,
    juge,
    arbitrage,
    frames=None,
    vocabulaire=None,
    pont=None,
) -> Path:
    """Le rapport complet : ciblage, constatations, abstentions, alias, compteurs.

    Les constatations sont **consolidées** avant écriture (architecture.md §8.2) : c'est ce
    qui range la moitié mono-clause d'un double constat sous sa paire, au lieu de la laisser
    passer pour une seconde trouvaille.
    """
    from cohera import reglages
    from cohera.consolidation.constatations import regrouper
    from cohera.consolidation.criticite import ordonner
    from cohera.restitution.rapport_json import (
        Abstention,
        Constatation,
        CoteClause,
        HypotheseAlias,
        RefClause,
        StatistiquesLLM,
        charger_rapport,
        ecrire_rapport,
    )

    # Le rapport de ciblage porte déjà documents, clauses analysées et statistiques : on le
    # reconstruit à l'identique plutôt que d'en dupliquer la logique, puis on le relit pour
    # y greffer ce que la détection ajoute.
    rapport = charger_rapport(_ecrire_rapport_ciblage(chemin, jeu, segmentations, ciblage))

    clauses = {c.clause_id: c for s in segmentations.values() for c in s.clauses}

    def cote(clause_id: str | None, preuve: str | None) -> CoteClause | None:
        if clause_id is None:
            return None
        clause = clauses.get(clause_id)
        return CoteClause(
            doc=clause.doc_id if clause else "",
            ref=clause.ref if clause else "",
            clause_id=clause_id,
            preuve=preuve or "",
            texte_source=clause.texte_source if clause else None,
        )

    def reference(clause_id: str | None) -> RefClause | None:
        if clause_id is None:
            return None
        clause = clauses.get(clause_id)
        return RefClause(
            doc=clause.doc_id if clause else "",
            ref=clause.ref if clause else "",
            clause_id=clause_id,
        )

    def cite_une_norme(clause_a: str, clause_b: str | None) -> bool:
        """L'une des deux clauses invoque-t-elle un référentiel externe ?

        Déclenche le multiplicateur « exigence externe » de §8.3. Lu dans les `Reference`
        de type NORME des Clause Frames — la même source qu'`A5`, et non l'arête
        `CITE_NORME` du graphe, pour que le rapport reste constructible hors Neo4j.
        """
        if frames is None:
            return False
        from cohera.extraction.frames import TypeReference

        return any(
            reference.type is TypeReference.NORME
            for clause_id in (clause_a, clause_b)
            if clause_id is not None and clause_id in frames
            for reference in frames[clause_id].references
        )

    def cle_partagee(clause_a: str, clause_b: str | None) -> str:
        """La clé de comparaison de §5.8 quand les deux clauses en ont une **commune**.

        Vide sinon : c'est le second terme de la clé de regroupement de §8.2, et une clé
        partielle ne doit jamais regrouper. Vide aussi quand le vocabulaire n'est pas
        fourni — un rapport reste alors lisible, il ne regroupe simplement pas.
        """
        if clause_b is None or frames is None or vocabulaire is None or pont is None:
            return ""
        from cohera.graphe.chargeur import cle_comparaison

        gauche = cle_comparaison(clause_a, frames, vocabulaire, pont)
        droite = cle_comparaison(clause_b, frames, vocabulaire, pont)
        return gauche if gauche and gauche == droite else ""

    # Consolidation, puis ordre de lecture : regrouper d'abord — cela retire des lignes —,
    # ordonner ensuite, sur ce qui reste (architecture.md §8.2 puis §8.3).
    niveaux = {
        document.id: document.niveau_hierarchique
        for document in rapport.documents
        if document.niveau_hierarchique is not None
    }
    rapport.constatations = ordonner(
        regrouper(
            [
                Constatation(
                    id=f"{verdict.detecteur}-{index:03d}",
                    type=verdict.type_taxonomie or verdict.type.value,
                    clause_a=cote(verdict.clause_a, verdict.preuve_a),
                    clause_b=cote(verdict.clause_b, verdict.preuve_b),
                    gravite=verdict.gravite,
                    detecteur=verdict.detecteur,
                    etage=verdict.etage,
                    confiance=verdict.confiance,
                    explication=verdict.explication,
                    cle_comparaison=cle_partagee(verdict.clause_a, verdict.clause_b),
                    plus_permissive=verdict.plus_permissive or "",
                    cite_norme_externe=cite_une_norme(verdict.clause_a, verdict.clause_b),
                )
                for index, verdict in enumerate(detection.constatations, start=1)
            ]
        ),
        niveaux,
    )

    rapport.abstentions = [
        Abstention(
            clause_a=reference(verdict.clause_a),
            clause_b=reference(verdict.clause_b),
            motif=verdict.motif.value,
            explication=verdict.explication,
            etage=verdict.etage,
        )
        for verdict in detection.abstentions
    ]

    # Les hypothèses d'alignement du rapport, ce sont TOUS les alias du pont — pas seulement
    # les deux que le LLM a arbitrés. Un alias EXACT ou LEXIQUE est tout aussi révisable
    # (architecture.md §13, R1) : c'est lui qui a permis de rapprocher deux clauses, et le
    # taire ferait passer une hypothèse pour un fait.
    if pont is not None:
        rapport.hypotheses_alias = [
            HypotheseAlias(
                libelle_a=arete.libelle_a,
                libelle_b=arete.libelle_b,
                methode=arete.methode.value,
                score_vectoriel=arete.score,
                retenu=True,
                confiance=arete.score,
                justification=f"Alias posé par la méthode {arete.methode.value}.",
            )
            for arete in sorted(pont.aretes, key=lambda a: (a.methode.value, -a.score))
        ]

    if arbitrage is not None:
        rapport.hypotheses_alias += [
            HypotheseAlias(
                libelle_a=a.libelle_a, libelle_b=a.libelle_b,
                score_vectoriel=a.score_vectoriel, retenu=a.retenu,
                confiance=a.confiance, justification=a.justification or a.abstention,
            )
            for a in arbitrage.arbitrages
        ]

    # Rubrique 4 : les conflits apparents qui sont couverts par une dérogation valide (N05).
    if frames is not None:
        from cohera.consolidation.derogations import derogations_en_vigueur
        from cohera.ingestion import date_reference

        rapport.date_reference = date_reference(jeu)
        rapport.derogations_en_vigueur = derogations_en_vigueur(
            frames, clauses, rapport.date_reference
        )

    if juge is not None:
        from cohera.detection import config_detection

        nom_profil, config_profil = reglages.profil_llm()
        rapport.statistiques_llm = StatistiquesLLM(
            profil=nom_profil,
            modele=config_profil.modele,
            appels_reseau=juge.compteurs.appels_reseau,
            servis_par_cache=juge.compteurs.servis_par_cache,
            tokens_prompt=juge.compteurs.tokens_prompt,
            tokens_completion=juge.compteurs.tokens_completion,
            reparations=juge.compteurs.reparations,
            budget_max=config_detection.max_appels_juge(),
            paires_soumises=juge.paires_soumises,
            verdicts_annules=juge.verdicts_annules,
            taux_annulation=round(juge.taux_annulation, 4),
            non_verifiees_budget=juge.non_verifiees_budget,
            non_verifiees_service=juge.non_verifiees_service,
            echecs_transport=juge.echecs_transport,
            coupe_circuit=juge.coupe_circuit,
        )

    return ecrire_rapport(rapport, chemin)


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
                niveau_hierarchique=getattr(
                    segmentation.document, "niveau_hierarchique", None
                ),
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


# --------------------------------------------------------------------- incrementer


@app.command()
def incrementer(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de référence."),
    derive: str = typer.Option("incremental", "--derive", help="Jeu dérivé à rejouer."),
    reference: Path = typer.Option(
        Path("rapport.json"), "--reference", help="Rapport de référence à comparer."
    ),
    sortie: Path = typer.Option(
        Path("rapport_incremental.json"), "--sortie", help="Où écrire le rapport rejoué."
    ),
    llm: str = typer.Option(None, "--llm", help="Profil LLM pour l'étage C."),
) -> None:
    """Scénario incrémental : une clause change, on relance, on voit ce qui se résout.

    Modifie une clause **dans une copie** du corpus — `corpus/fixtures/` est en lecture
    seule —, recharge le graphe, rejoue la cascade, et compare au rapport de référence.
    Toute constatation présente avant et absente après passe au statut `RESOLUE`.

    ⚠️ Le graphe est **rendu à son état de référence** en fin de commande, y compris si elle
    échoue en chemin : les `clause_id` du jeu dérivé sont ceux du jeu source, si bien que le
    chargement écrase les textes de D1. C'est l'idempotence du chargement, vérifiée depuis
    le J3, qui rend cet aller-retour sûr.
    """
    _utf8()
    import time

    from cohera.consolidation.constatations import regrouper  # noqa: F401  (contrat du rapport)
    from cohera.evaluation import metriques
    from cohera.graphe.chargeur import charger
    from cohera.graphe.connexion import ErreurNeo4j
    from cohera.restitution.rapport_json import StatutConstatation, charger_rapport

    if llm:
        os.environ["COHERA_LLM"] = llm

    if not reference.is_file():
        _abandonner(
            f"{reference} est absent : il n'y a rien à comparer.",
            "Produire le rapport de référence d'abord : cohera detecter --jeu fixtures",
        )
    avant = charger_rapport(reference)

    depart = time.perf_counter()
    try:
        contexte_derive = _construire_pont(derive)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        _abandonner(str(exc), "Vérifier la déclaration du jeu dérivé dans config/corpus.yaml.")

    try:
        _charger_et_detecter(derive, contexte_derive, sortie, llm)
        duree = time.perf_counter() - depart
    finally:
        # Rendre le graphe à son état de référence, quoi qu'il arrive en chemin.
        try:
            segmentations, frames, vocabulaire, pont = _construire_pont(jeu)
            charger(segmentations, frames, vocabulaire, pont)
        except (ErreurNeo4j, KeyError, FileNotFoundError) as exc:
            typer.secho(
                f"⚠ Le graphe n'a PAS été rendu à son état de référence : {exc}\n"
                f"-> relancer : cohera graphe charger --jeu {jeu}",
                fg="red",
                err=True,
            )

    apres = charger_rapport(sortie)
    resolues, nouvelles = _comparer_rapports(avant, apres)

    # Les constatations résolues ne DISPARAISSENT pas du rapport incrémental : elles y
    # figurent au statut RESOLUE. Une correction qui s'efface du rapport ne se démontre pas.
    apres.constatations += [
        constatation.model_copy(update={"statut": StatutConstatation.RESOLUE})
        for constatation in resolues
    ]
    from cohera.restitution.rapport_json import ecrire_rapport

    ecrire_rapport(apres, sortie)

    llm_apres = apres.statistiques_llm
    appels = llm_apres.appels_reseau if llm_apres is not None else 0

    typer.echo("")
    typer.echo(f"{'constatations avant':<28} {len(avant.constatations)}")
    typer.echo(f"{'constatations après':<28} {len(apres.constatations) - len(resolues)}")
    typer.echo(f"{'RÉSOLUES':<28} {len(resolues)}")
    for constatation in resolues:
        libelle = constatation.clause_a.libelle() + (
            f" ↔ {constatation.clause_b.libelle()}" if constatation.clause_b else ""
        )
        typer.secho(f"  ✓ {libelle} ({constatation.type})", fg=typer.colors.GREEN if _couleur() else None)
    if nouvelles:
        typer.echo(f"{'nouvelles':<28} {len(nouvelles)}")
        for constatation in nouvelles:
            typer.echo(f"  + {constatation.clause_a.libelle()}")

    typer.echo("")
    typer.echo(f"{'appels LLM':<28} {appels}")
    typer.echo(f"{'durée':<28} {duree:.1f} s")

    verite = metriques.charger_verite(jeu)
    identifiants = _incoherences_resolues(resolues, verite)
    if identifiants:
        typer.echo("")
        typer.echo(f"Incohérence(s) de la vérité terrain résolue(s) : {', '.join(identifiants)}")


def _charger_et_detecter(jeu: str, contexte, sortie: Path, llm: str | None) -> None:
    """Charge le jeu dérivé dans le graphe et y rejoue la cascade complète."""
    from cohera.ciblage import cibler as executer_ciblage
    from cohera.detection.cascade import detecter as executer_cascade
    from cohera.detection.objets import objets_canoniques
    from cohera.graphe.chargeur import charger
    from cohera.graphe.conditions import construire_algebre
    from cohera.graphe.connexion import ErreurNeo4j
    from cohera.graphe.connexion import session as ouvrir_session

    segmentations, frames, vocabulaire, pont = contexte

    try:
        charger(segmentations, frames, vocabulaire, pont)
        with ouvrir_session() as session:
            ciblage = executer_ciblage(session, frames)
    except ErreurNeo4j as exc:
        _abandonner(str(exc), exc.remede)

    clauses = {c.clause_id: c for s in segmentations.values() for c in s.clauses}
    textes = {cid: c.texte_source for cid, c in clauses.items()}
    algebre = construire_algebre(frames)
    detection = executer_cascade(ciblage, frames, textes, vocabulaire, pont, algebre)

    from cohera.detection.juge_llm import juger

    objets = {cid: objets_canoniques(cid, vocabulaire, pont) for cid in clauses}
    niveaux = {
        doc_id: segmentation.document.niveau_hierarchique
        for doc_id, segmentation in segmentations.items()
        if getattr(segmentation.document, "niveau_hierarchique", None) is not None
    }
    scores = {
        frozenset((p.clause_a, p.clause_b)): p.score_rrf for p in ciblage.candidates
    }
    juge = juger(
        detection, clauses, frames, textes, algebre, objets,
        niveaux=niveaux, scores=scores, budget=None, compteurs=None,
    )

    _ecrire_rapport_detection(
        sortie, jeu, segmentations, ciblage, detection, juge, None,
        frames=frames, vocabulaire=vocabulaire, pont=pont,
    )


def _comparer_rapports(avant, apres) -> tuple[list, list]:
    """Constatations disparues et apparues entre deux exécutions.

    L'appariement se fait sur le couple de clauses, comme dans le harnais : c'est le même
    problème de fond qui est suivi d'une exécution à l'autre, pas le même identifiant — les
    identifiants sont réattribués à chaque run.
    """
    from cohera.evaluation.metriques import cle_constatation

    cles_avant = {cle_constatation(c): c for c in avant.constatations}
    cles_apres = {cle_constatation(c): c for c in apres.constatations}

    resolues = [c for cle, c in cles_avant.items() if cle not in cles_apres]
    nouvelles = [c for cle, c in cles_apres.items() if cle not in cles_avant]
    return resolues, nouvelles


def _incoherences_resolues(resolues: list, verite: dict) -> list[str]:
    """Les identifiants de `label.json` que ces constatations résolues portaient."""
    from cohera.evaluation.metriques import cle_constatation, cle_entree

    index = {
        cle_entree(e): e.get("id", "?")
        for e in verite.get("incoherences", [])
        if cle_entree(e) is not None
    }
    return sorted(
        {index[cle_constatation(c)] for c in resolues if cle_constatation(c) in index}
    )


# ---------------------------------------------------------------------- historique


@app.command()
def historique(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de vérité terrain sous corpus/."),
    chemin: Path = typer.Option(
        Path("evaluation/historique.csv"), "--sortie", help="Où écrire la table."
    ),
    rapports: list[str] = typer.Option(
        None,
        "--rapport",
        help="Répétable : chemin=jour=profil[=appels_llm=duree_s]. Les deux derniers champs "
        "sont le COÛT RÉEL de l'exécution d'origine, à donner quand le rejeu est servi par "
        "le cache — la ligne est alors marquée « journal ».",
    ),
) -> None:
    """Écrit `evaluation/historique.csv` — une ligne par exécution depuis le J4.

    La ligne **J4** est remesurée en rejouant le ciblage seul ; les lignes des rapports sont
    lues dans les rapports eux-mêmes. Rien n'est recopié du Journal sauf ce qui n'est pas
    reproductible sans repayer les appels, et la colonne `source` le dit.

    Idempotent : rejouer la commande remplace les lignes au lieu de les empiler.
    """
    _utf8()
    import time

    from cohera.ciblage import cibler as executer_ciblage
    from cohera.evaluation import historique as table
    from cohera.evaluation.metriques import charger_verite
    from cohera.graphe.connexion import ErreurNeo4j
    from cohera.graphe.connexion import session as ouvrir_session
    from cohera.restitution.rapport_json import charger_rapport

    try:
        segmentations, frames, _vocabulaire, _pont = _construire_pont(jeu)
        verite = charger_verite(jeu)
    except (KeyError, FileNotFoundError) as exc:
        _abandonner(str(exc), "Vérifier config/corpus.yaml.")

    lignes = []

    # J4 — le ciblage seul, remesuré. Aucune constatation : c'est l'état où le rappel du
    # ciblage est déjà 12/12 alors que le rappel du système vaut encore 0.
    try:
        with ouvrir_session() as session:
            depart = time.perf_counter()
            ciblage = executer_ciblage(session, frames)
            duree = time.perf_counter() - depart
    except ErreurNeo4j as exc:
        _abandonner(str(exc), exc.remede)

    attendues = sum(
        1 for e in verite.get("incoherences", []) if e.get("dans_perimetre_7j")
    )
    ciblees = sum(
        1
        for e in verite.get("incoherences", [])
        if e.get("dans_perimetre_7j")
        and _est_ciblee(e, ciblage, segmentations)
    )
    lignes.append(
        table.ligne_depuis_bareme(
            jour="J4",
            configuration="ciblage seul (aucune détection)",
            paires_candidates=len(ciblage.candidates),
            rappel_ciblage=f"{ciblees}/{attendues}",
            vrais_positifs=0,
            faux_positifs=0,
            attendues=attendues,
            precision=0.0,
            duree_s=duree,
        )
    )

    for specification in rapports or []:
        morceaux = str(specification).split("=")
        fichier = Path(morceaux[0])
        jour = morceaux[1] if len(morceaux) > 1 else "J7"
        profil = morceaux[2] if len(morceaux) > 2 else "—"
        if not fichier.is_file():
            typer.secho(f"Ignoré, absent : {fichier}", fg="yellow", err=True)
            continue

        ligne = table.ligne_depuis_rapport(
            charger_rapport(fichier),
            verite,
            jour=jour,
            configuration=f"pipeline complet ({fichier.name})",
            profil=profil,
        )

        # Un rejeu servi par le cache coûte 0 appel — vrai pour ce rejeu, trompeur sur ce que
        # l'exécution d'origine a coûté. Quand le coût réel est donné, il remplace le chiffre
        # du rejeu.
        #
        # ⚠️ Seul le nombre d'APPELS fait basculer la ligne en « journal », et seulement s'il
        # diffère de ce que le rapport a enregistré : c'est le chiffre qui distingue « rejoué
        # depuis le cache » de « a réellement coûté cela ». La durée, elle, est toujours
        # chronométrée hors du rapport — la fournir n'est jamais une transcription.
        if len(morceaux) > 3 and morceaux[3]:
            if str(ligne["appels_llm"]) != morceaux[3]:
                ligne["appels_llm"] = morceaux[3]
                ligne["source"] = "journal"
        if len(morceaux) > 4 and morceaux[4]:
            ligne["duree_s"] = morceaux[4]

        lignes.append(ligne)

    ecrit = table.consigner(chemin, lignes)

    typer.echo(f"{len(lignes)} ligne(s) consignée(s) — {ecrit}")
    typer.echo("")
    for ligne in table.lire(ecrit):
        typer.echo(
            f"  {ligne['jour']:<4} {ligne['configuration']:<42} "
            f"{ligne['profil']:<7} cand.{ligne['paires_candidates']:>4} "
            f"ciblage {ligne['rappel_ciblage']:>6} rappel {ligne['rappel']:>6} "
            f"préc. {ligne['precision']:>5} FP {ligne['faux_positifs']:>2} "
            f"LLM {ligne['appels_llm']:>3} [{ligne['source']}]"
        )


def _est_ciblee(entree: dict, ciblage, segmentations: dict) -> bool:
    """Une incohérence est-elle à portée de la cascade après ciblage ?

    Une anomalie mono-clause n'a aucune paire : la question devient « la clause a-t-elle été
    analysée », exactement comme dans `evaluation/ablations.py`.
    """
    correspondance = {
        (doc_id, clause.ref): clause.clause_id
        for doc_id, segmentation in segmentations.items()
        for clause in segmentation.clauses
    }
    a = entree.get("clause_a") or {}
    id_a = correspondance.get((a.get("doc", ""), a.get("ref", "")))
    b = entree.get("clause_b")
    if b is None:
        return id_a is not None and id_a in ciblage.contextes
    id_b = correspondance.get((b.get("doc", ""), b.get("ref", "")))
    return bool(id_a and id_b and ciblage.est_candidate(id_a, id_b))


# ----------------------------------------------------------------------- ablation


@app.command()
def ablation(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    sortie_json: bool = typer.Option(False, "--json", help="Sortie machine plutôt que tableau."),
    historique: Path = typer.Option(
        Path("evaluation/historique.csv"), "--historique", help="Où consigner les lignes."
    ),
    sans_historique: bool = typer.Option(
        False, "--sans-historique", help="Ne pas écrire dans historique.csv."
    ),
) -> None:
    """Les trois ablations du plan §J7 : `--sans-alias`, `--sans-canal5`, `--sans-etage-c`.

    Rejoue le ciblage et l'étage A dans chaque configuration et chiffre l'écart à la
    référence. `--sans-etage-c` n'est pas une branche à part : **toutes** les branches
    tournent à étage A seul, si bien que la référence de ce tableau *est* le système sans
    étage C.

    Aucun appel réseau : c'est précisément pourquoi les branches sont mesurées sans le juge.
    """
    _utf8()
    from cohera.evaluation.ablations import ablations_du_j7, formater_ablations_j7
    from cohera.evaluation.metriques import charger_verite
    from cohera.graphe.connexion import ErreurNeo4j
    from cohera.graphe.connexion import session as ouvrir_session

    try:
        segmentations, frames, vocabulaire, pont = _construire_pont(jeu)
    except (KeyError, FileNotFoundError) as exc:
        _abandonner(str(exc), "Vérifier config/corpus.yaml.")

    correspondance = {
        (doc_id, clause.ref): clause.clause_id
        for doc_id, segmentation in segmentations.items()
        for clause in segmentation.clauses
    }

    try:
        with ouvrir_session() as session:
            resultat = ablations_du_j7(
                session, frames, segmentations, vocabulaire, pont,
                charger_verite(jeu), correspondance,
            )
    except ErreurNeo4j as exc:
        _abandonner(str(exc), exc.remede)

    if sortie_json:
        typer.echo(json.dumps(resultat.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        typer.echo(formater_ablations_j7(resultat, couleur=_couleur()))

    if not sans_historique:
        from cohera.evaluation.historique import consigner_ablations

        chemin = consigner_ablations(historique, resultat)
        typer.echo("")
        typer.echo(f"Historique : {chemin}")


# ------------------------------------------------------------------------ rapport

#: Le motif du choix de profil, affiché en tête du rapport HTML. Il n'y a pas de gagnant :
#: aucun profil n'atteint les deux critères durs, et le lecteur doit voir l'arbitrage.
_MOTIF_PROFIL = (
    "Profil retenu pour la précision : sur ce corpus il rend un F1 supérieur (0,75 contre "
    "0,65 dans le périmètre) et deux fois moins de constatations fausses. Le profil distant "
    "atteint un meilleur rappel — 10 incohérences sur 12 contre 9 — au prix de trois fois "
    "plus de faux positifs. Aucun des deux n'atteint les deux critères à la fois."
)


@app.command()
def rapport(
    jeu: str = typer.Option("fixtures", "--jeu", help="Jeu de documents sous corpus/."),
    source: Path = typer.Option(
        Path("rapport.json"), "--source", help="Rapport JSON à mettre en forme."
    ),
    html: Path = typer.Option(Path("rapport.html"), "--html", help="Où écrire la page HTML."),
    ablation_profils: Path = typer.Option(
        None, "--profils", help="JSON du tableau d'ablation A/B à intégrer en en-tête."
    ),
) -> None:
    """Met `rapport.json` en forme : une page HTML autonome à quatre rubriques.

    **La vérification des preuves littérales est bloquante.** Si une seule citation du
    rapport n'existe pas dans son texte source, rien n'est écrit et la commande sort en
    code 1 : c'est le premier critère d'acceptation du J7, et l'invariant #3 du projet
    appliqué au document que l'auditeur lira.
    """
    _utf8()
    from cohera.restitution import preuves as controle
    from cohera.restitution import rapport_html
    from cohera.restitution.rapport_json import charger_rapport

    if not source.is_file():
        _abandonner(
            f"{source} est absent : il n'y a rien à mettre en forme.",
            "Produire le rapport d'abord : cohera detecter --jeu fixtures",
        )

    contenu = charger_rapport(source)

    bilan = controle.verifier(contenu)
    typer.echo(controle.formater_bilan(bilan, couleur=_couleur()))
    if not bilan.conforme:
        typer.echo("")
        _abandonner(
            f"{len(bilan.echecs)} preuve(s) non littérale(s) : aucun rapport n'est publié.",
            "Corriger le détecteur fautif, ou vérifier que texte_source accompagne la preuve.",
        )

    profils = []
    if ablation_profils and ablation_profils.is_file():
        profils = json.loads(ablation_profils.read_text(encoding="utf-8"))

    chemin = rapport_html.ecrire(
        html,
        rapport_html.rendre(
            contenu,
            bilan_preuves=bilan,
            ablation_profils=profils,
            motif_du_profil=_MOTIF_PROFIL,
        ),
    )

    typer.echo("")
    typer.echo(
        f"{len(contenu.constatations)} constatation(s) · "
        f"{len(contenu.hypotheses_alias)} hypothèse(s) d'alignement · "
        f"{len(contenu.abstentions)} zone(s) non couverte(s) · "
        f"{len(contenu.derogations_en_vigueur)} dérogation(s) en vigueur"
    )
    typer.echo(f"HTML écrit : {chemin}")


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
