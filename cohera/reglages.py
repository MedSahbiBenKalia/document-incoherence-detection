"""Chargement de la configuration technique : YAML, `.env`, surcharge par l'environnement.

Ordre de priorité, du plus fort au plus faible :

1. argument explicite de la CLI (``--llm gemini``, ``--device cpu``) ;
2. variable d'environnement (``COHERA_LLM``, ``COHERA_DEVICE``) ;
3. valeur de ``config/technique.yaml``.

Les secrets ne transitent jamais par le YAML : celui-ci ne porte que le *nom* de la
variable d'environnement qui contient la valeur (``mot_de_passe_env``, ``cle_api_env``).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- chemins


def racine_projet() -> Path:
    """Racine du dépôt : le parent du paquet ``cohera``."""
    return Path(__file__).resolve().parent.parent


def chemin_config() -> Path:
    """Emplacement de ``technique.yaml``, surchargeable par ``COHERA_CONFIG``."""
    surcharge = os.environ.get("COHERA_CONFIG")
    if surcharge:
        return Path(surcharge)
    return racine_projet() / "config" / "technique.yaml"


# ----------------------------------------------------------------------------- .env


def charger_dotenv(chemin: Path | None = None) -> int:
    """Charge ``.env`` dans l'environnement du processus. Renvoie le nombre de clés posées.

    Une variable déjà présente dans l'environnement n'est **jamais** écrasée : ce qui est
    passé explicitement au shell doit gagner sur un fichier oublié.

    Quinze lignes plutôt qu'une dépendance à ``python-dotenv`` — le format qu'on a
    besoin de lire ici tient en trois règles.
    """
    chemin = chemin or (racine_projet() / ".env")
    if not chemin.is_file():
        return 0

    posees = 0
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle = cle.strip()
        valeur = valeur.strip().strip('"').strip("'")
        if cle and cle not in os.environ:
            os.environ[cle] = valeur
            posees += 1
    return posees


def secret(nom_variable: str | None) -> str | None:
    """Lit un secret dans l'environnement, après avoir chargé ``.env`` si besoin.

    Renvoie ``None`` si le nom est ``None`` (profil sans clé, comme LM Studio) ou si la
    variable est absente ou vide.
    """
    if not nom_variable:
        return None
    charger_dotenv()
    valeur = os.environ.get(nom_variable, "").strip()
    return valeur or None


# --------------------------------------------------------------------------- schémas


class ProfilLLM(BaseModel):
    """Un fournisseur LLM. Les quatre parlent le protocole OpenAI : seuls ces champs changent."""

    base_url: str
    modele: str
    cle_api_env: str | None = None
    json_schema: bool = False


class ConfigLLM(BaseModel):
    fournisseur: str = "local"
    timeout_s: float = 30.0
    repli: list[str] = Field(default_factory=list)
    profils: dict[str, ProfilLLM] = Field(default_factory=dict)


class ConfigNeo4j(BaseModel):
    uri: str = "bolt://localhost:7687"
    utilisateur: str = "neo4j"
    mot_de_passe_env: str = "NEO4J_PASSWORD"
    base: str = "neo4j"
    timeout_s: float = 5.0
    syntaxe_vectorielle: Literal["auto", "search", "procedure"] = "auto"


class ConfigSpacy(BaseModel):
    modele: str = "fr_core_news_lg"


class ConfigEmbeddings(BaseModel):
    modele: str = "BAAI/bge-m3"
    dimension: int = 1024


class ConfigNLI(BaseModel):
    modele: str = "cmarkea/distilcamembert-base-nli"


class Reglages(BaseModel):
    device: str = "auto"
    neo4j: ConfigNeo4j = Field(default_factory=ConfigNeo4j)
    spacy: ConfigSpacy = Field(default_factory=ConfigSpacy)
    embeddings: ConfigEmbeddings = Field(default_factory=ConfigEmbeddings)
    nli: ConfigNLI = Field(default_factory=ConfigNLI)
    llm: ConfigLLM = Field(default_factory=ConfigLLM)


# -------------------------------------------------------------------------- chargement


@lru_cache(maxsize=4)
def charger(chemin: Path | None = None) -> Reglages:
    """Charge et valide ``technique.yaml``. Mis en cache : le fichier n'est lu qu'une fois."""
    charger_dotenv()
    chemin = chemin or chemin_config()
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Configuration technique introuvable : {chemin}\n"
            "Attendu : config/technique.yaml à la racine du dépôt."
        )
    brut = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    return Reglages.model_validate(brut)


# ------------------------------------------------------------------- config métier


@lru_cache(maxsize=16)
def charger_config(nom: str) -> dict:
    """Charge un YAML métier de ``config/`` : ``charger_config("segmentation")``.

    Distinct de :func:`charger`, qui ne lit que ``technique.yaml`` et le valide contre un
    schéma pydantic. Ici le contenu est ouvert — seuils, lexiques, monotonies — et c'est
    l'appelant qui sait ce qu'il attend. Ce qui compte est qu'aucune de ces valeurs ne
    vive dans un ``.py``.
    """
    chemin = racine_projet() / "config" / f"{nom}.yaml"
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Configuration métier introuvable : {chemin}\n"
            f"Attendu : config/{nom}.yaml à la racine du dépôt."
        )
    return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}


# ---------------------------------------------------------------------- les bascules


def device_effectif(demande: str | None = None) -> str:
    """Résout ``auto`` en ``cuda`` ou ``cpu``, en interrogeant torch.

    La roue CUDA tourne parfaitement sur CPU : ``COHERA_DEVICE=cpu`` compare les deux
    sans rien réinstaller. C'est la bascule de tous les jours ; la bascule de roue
    (``cohera torch --backend``) ne sert qu'aux machines sans GPU.
    """
    choix = (demande or os.environ.get("COHERA_DEVICE") or charger().device or "auto").lower()

    if choix != "auto":
        return choix

    try:
        import torch  # import différé : ~2 s, inutile pour la plupart des commandes

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def nom_profil_llm(demande: str | None = None) -> str:
    """Nom du profil LLM actif : argument CLI, puis ``COHERA_LLM``, puis le YAML."""
    return demande or os.environ.get("COHERA_LLM") or charger().llm.fournisseur


def profil_llm(demande: str | None = None) -> tuple[str, ProfilLLM]:
    """Renvoie ``(nom, profil)`` du fournisseur actif.

    Lève ``KeyError`` avec la liste des profils connus si le nom demandé n'existe pas —
    une faute de frappe dans ``--llm`` doit se voir immédiatement, pas se dégrader en
    repli silencieux.
    """
    config = charger().llm
    nom = nom_profil_llm(demande)
    if nom not in config.profils:
        connus = ", ".join(sorted(config.profils)) or "(aucun)"
        raise KeyError(f"Profil LLM inconnu : {nom!r}. Profils déclarés : {connus}")
    return nom, config.profils[nom]
