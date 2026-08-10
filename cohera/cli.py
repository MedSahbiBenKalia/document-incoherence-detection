"""Interface en ligne de commande de COHERA.

    cohera doctor                   vérifie Neo4j, spaCy, embeddings, NLI, LLM
    cohera evaluer --jeu fixtures   compare rapport.json à la vérité terrain
    cohera torch --backend cpu      bascule la roue PyTorch
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
