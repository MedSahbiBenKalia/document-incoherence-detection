"""Les six vérifications de ``cohera doctor``.

Chaque vérification est une fonction isolée qui renvoie une :class:`Verification` et
n'échappe jamais par une exception : un diagnostic qui plante sur une trace Python
n'apprend rien à qui doit simplement lancer Docker Desktop.

Chacune prouve un fait précis plutôt que la simple présence d'un paquet — les embeddings
doivent produire un vecteur de la bonne dimension, le NLI doit réussir une passe avant.

**Durées.** Neo4j (5 s) et le LLM (30 s) sont bornés par un délai, parce qu'un service
absent peut faire pendre indéfiniment. Les chargements de modèles ne le sont pas : au
premier lancement ils *téléchargent* (~3 Go au total) et une barre de progression
s'affiche. Ce n'est pas un blocage, c'est le prix d'entrée, une seule fois.
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from cohera import reglages


class Verification(BaseModel):
    """Une ligne du tableau de diagnostic."""

    nom: str
    ok: bool
    detail: str = ""
    remede: str = ""


def _echec(nom: str, exc: Exception, remede: str = "") -> Verification:
    """Transforme une exception en ligne rouge, en récupérant son remède s'il en porte un."""
    remede = remede or getattr(exc, "remede", "") or ""
    message = str(exc) or exc.__class__.__name__
    return Verification(nom=nom, ok=False, detail=message, remede=remede)


# ------------------------------------------------------------ 1. configuration d'extraction


def verifier_config_extraction() -> Verification:
    """Les deux configurations du J2 se chargent et respectent leur schéma.

    La moins chère des six — aucun modèle, aucun réseau — donc en premier. Une grandeur
    du registre sans monotonie, ou un lexique déontique mal formé, y échoue immédiatement
    plutôt qu'au milieu d'une extraction (.claude/rules/extraction.md)."""
    nom = "Configuration extraction"
    try:
        from cohera.extraction.config import charger_lexique_extraction, charger_registre_grandeurs

        registre = charger_registre_grandeurs()
        lexique = charger_lexique_extraction()
        return Verification(
            nom=nom,
            ok=True,
            detail=(
                f"{len(registre.grandeurs)} rôle(s) de grandeur · "
                f"{len(lexique.qualification.marqueurs_deontiques)} marqueur(s) déontique(s)"
            ),
        )
    except Exception as exc:
        return _echec(
            nom, exc, "Vérifier config/registre_grandeurs.yaml et config/lexique_qhse.yaml."
        )


# --------------------------------------------------------------------- 2. Neo4j


def verifier_neo4j() -> Verification:
    """Le serveur répond, et on sait déjà quelle syntaxe vectorielle sera employée."""
    from cohera.graphe import compat
    from cohera.graphe.connexion import ErreurNeo4j, verifier_connectivite

    try:
        version_brute = verifier_connectivite()
    except ErreurNeo4j as exc:
        return _echec("Neo4j", exc)
    except Exception as exc:  # driver, DNS, TLS, tout le reste
        return _echec(
            "Neo4j",
            exc,
            "Démarrer Docker Desktop, puis : docker compose up -d",
        )

    try:
        version = compat.analyser_version(version_brute)
        syntaxe = compat.syntaxe_effective(version)
        note = "clause SEARCH" if syntaxe == "search" else "db.index.vector.queryNodes (déprécié)"
        detail = f"{version_brute} · recherche vectorielle : {note}"
    except ValueError:
        detail = f"{version_brute} · version non analysable, syntaxe vectorielle indéterminée"

    return Verification(nom="Neo4j", ok=True, detail=detail)


# --------------------------------------------------------------------- 3. spaCy


def verifier_spacy() -> Verification:
    """Le modèle français est installé et se charge."""
    modele = reglages.charger().spacy.modele
    try:
        import spacy

        nlp = spacy.load(modele)
        nlp("Le port du casque est obligatoire en zone A.")
        version_modele = nlp.meta.get("version", "?")
        return Verification(
            nom=f"spaCy {modele}",
            ok=True,
            detail=f"modèle {version_modele} · spaCy {spacy.__version__}",
        )
    except OSError as exc:
        return _echec(
            f"spaCy {modele}", exc, f"python -m spacy download {modele}"
        )
    except Exception as exc:
        return _echec(f"spaCy {modele}", exc, "pip install -e \".[dev]\"")


# ---------------------------------------------------------------- 4. embeddings


def verifier_embeddings() -> Verification:
    """Le modèle produit bien un vecteur de la dimension attendue.

    C'est la dimension qui compte, pas le chargement : l'index vectoriel Neo4j sera créé
    avec cette valeur, et une incohérence ici ne se verrait qu'au J4, à l'insertion.
    """
    config = reglages.charger().embeddings
    nom = f"Embeddings {config.modele}"
    try:
        from sentence_transformers import SentenceTransformer

        device = reglages.device_effectif()
        debut = time.perf_counter()
        modele = SentenceTransformer(config.modele, device=device)
        vecteur = modele.encode("Le port du casque est obligatoire en zone A.")
        duree = time.perf_counter() - debut

        obtenue = int(vecteur.shape[0])
        if obtenue != config.dimension:
            return Verification(
                nom=nom,
                ok=False,
                detail=f"dimension {obtenue}, attendue {config.dimension}",
                remede=(
                    "Aligner embeddings.dimension dans config/technique.yaml sur le "
                    "modèle réellement utilisé — cette valeur définit l'index vectoriel Neo4j."
                ),
            )

        return Verification(
            nom=nom,
            ok=True,
            detail=f"vecteur {obtenue} d · device {device} · {duree:.1f} s",
        )
    except Exception as exc:
        return _echec(
            nom,
            exc,
            "Vérifier la connexion réseau : le modèle est téléchargé au premier appel (~2,3 Go).",
        )


# ----------------------------------------------------------------------- 5. NLI


def verifier_nli() -> Verification:
    """Le modèle se charge **et** réussit une passe avant : charger seul ne prouve rien."""
    config = reglages.charger().nli
    nom = f"NLI {config.modele}"
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        device = reglages.device_effectif()
        debut = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(config.modele)
        modele = AutoModelForSequenceClassification.from_pretrained(config.modele).to(device)
        modele.eval()

        entrees = tokenizer(
            "Le port du casque est obligatoire en zone A.",
            "Il est recommandé de porter un casque.",
            return_tensors="pt",
            truncation=True,
        ).to(device)
        with torch.no_grad():
            sorties = modele(**entrees)
        duree = time.perf_counter() - debut

        nb_etiquettes = int(sorties.logits.shape[-1])
        etiquettes = ", ".join(modele.config.id2label[i] for i in range(nb_etiquettes))
        return Verification(
            nom=nom,
            ok=True,
            detail=f"passe avant OK · {nb_etiquettes} étiquettes ({etiquettes}) · device {device} · {duree:.1f} s",
        )
    except Exception as exc:
        return _echec(
            nom,
            exc,
            "Vérifier la connexion réseau : le modèle est téléchargé au premier appel (~270 Mo).",
        )


# ----------------------------------------------------------------------- 6. LLM


def verifier_llm(profil: str | None = None) -> Verification:
    """Le profil **actif** répond à un ping dans le délai imparti.

    Aucun repli n'est tenté ici, même si ``llm.repli`` en déclare : un diagnostic qui
    bascule en silence afficherait du vert en masquant un profil cassé.
    """
    from cohera import llm

    try:
        nom_profil, config_profil = reglages.profil_llm(profil)
    except KeyError as exc:
        return _echec(
            "LLM", exc, "Choisir un profil déclaré dans config/technique.yaml (llm.profils)."
        )

    delai = reglages.charger().llm.timeout_s
    nom = f"LLM ({nom_profil})"

    try:
        reponse = llm.ping(profil=nom_profil, timeout_s=delai)
    except llm.ErreurLLM as exc:
        return _echec(nom, exc)
    except Exception as exc:
        return _echec(nom, exc, f"Vérifier llm.profils.{nom_profil} dans config/technique.yaml.")

    if reponse.latence_ms > delai * 1000:
        return Verification(
            nom=nom,
            ok=False,
            detail=f"{config_profil.modele} · {reponse.latence_ms / 1000:.1f} s, au-delà de {delai:.0f} s",
            remede="Modèle plus léger, ou augmenter llm.timeout_s, ou basculer : --llm gemini",
        )

    apercu = reponse.texte.replace("\n", " ")[:30]
    return Verification(
        nom=nom,
        ok=True,
        detail=f"{config_profil.modele} · {reponse.latence_ms:.0f} ms · réponse {apercu!r}",
    )


# ------------------------------------------------------------------- orchestration


def tout_verifier(profil_llm: str | None = None) -> list[Verification]:
    """Les six vérifications, dans l'ordre du tableau."""
    return [
        verifier_config_extraction(),
        verifier_neo4j(),
        verifier_spacy(),
        verifier_embeddings(),
        verifier_nli(),
        verifier_llm(profil_llm),
    ]


def entete_environnement() -> str:
    """Une ligne de contexte au-dessus du tableau : build torch et device retenu."""
    try:
        import torch

        build = f"torch {torch.__version__}"
        cuda = getattr(torch.version, "cuda", None)
        build += f" · CUDA {cuda}" if cuda else " · build CPU"
        disponible = "GPU disponible" if torch.cuda.is_available() else "GPU indisponible"
    except Exception:
        build, disponible = "torch non importable", ""

    device = reglages.device_effectif()
    parties = [p for p in (build, disponible, f"device retenu : {device}") if p]
    return " · ".join(parties)


def formater_tableau(verifications: list[Verification], couleur: bool = True) -> str:
    """Rend le tableau de diagnostic en texte aligné."""
    vert, rouge, gras, fin = ("\033[32m", "\033[31m", "\033[1m", "\033[0m") if couleur else ("",) * 4

    etats = ["OK" if v.ok else "ECHEC" for v in verifications]
    largeur_nom = max(len(v.nom) for v in verifications)
    largeur_etat = max(len(e) for e in etats)

    lignes = [
        f"{gras}{'Vérification'.ljust(largeur_nom)}  {'État'.ljust(largeur_etat)}  Détail{fin}",
        "-" * (largeur_nom + largeur_etat + 40),
    ]
    for verification, etat in zip(verifications, etats):
        teinte = vert if verification.ok else rouge
        lignes.append(
            f"{verification.nom.ljust(largeur_nom)}  "
            f"{teinte}{etat.ljust(largeur_etat)}{fin}  "
            f"{verification.detail}"
        )
        if verification.remede:
            lignes.append(f"{' ' * (largeur_nom + largeur_etat + 4)}-> {verification.remede}")

    return "\n".join(lignes)
