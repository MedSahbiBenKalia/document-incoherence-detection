"""Client LLM : un seul transport pour quatre fournisseurs.

LM Studio, Gemini, Groq et OpenRouter exposent tous un endpoint **compatible OpenAI**.
Seuls ``base_url``, ``modele`` et la clé d'API changent d'un profil à l'autre — d'où un
client unique, et zéro ramification par fournisseur dans le code métier.

Basculer se fait à trois niveaux, du plus ponctuel au plus durable ::

    cohera doctor --llm gemini      # cet appel-ci
    $env:COHERA_LLM = "gemini"      # cette session
    # config/technique.yaml : llm.fournisseur

Ce module ne contient que du transport. Les prompts et schémas de sortie propres à
l'extraction vivent dans ``cohera.extraction.llm_client``.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel

from cohera import reglages

# Prompt de vérification : assez court pour qu'un 7B quantifié sur CPU y réponde vite,
# assez contraint pour que la réponse soit vérifiable.
PROMPT_PING = "Réponds uniquement par le mot OK."


class ErreurLLM(Exception):
    """Échec d'appel au LLM, accompagné du geste qui le corrige.

    Le champ ``remede`` est ce que ``cohera doctor`` affiche en bout de ligne : une
    trace Python n'apprend rien à qui doit juste lancer LM Studio.
    """

    def __init__(self, message: str, remede: str = "") -> None:
        super().__init__(message)
        self.remede = remede


class ReponseLLM(BaseModel):
    texte: str
    profil: str
    modele: str
    latence_ms: float


def _url_completions(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _diagnostiquer_statut(statut: int, profil: str, modele: str, cle_api_env: str | None) -> ErreurLLM:
    """Traduit un code HTTP en message + remède, plutôt qu'en `raise_for_status()` brut."""
    if statut in (401, 403):
        variable = cle_api_env or "(aucune)"
        return ErreurLLM(
            f"Authentification refusée ({statut}) par le profil {profil}.",
            f"Vérifier la valeur de {variable} dans .env — clé absente, expirée ou invalide.",
        )
    if statut == 404:
        return ErreurLLM(
            f"Modèle ou endpoint introuvable (404) sur le profil {profil} : {modele}.",
            "Vérifier `modele` et `base_url` dans config/technique.yaml. En local, "
            "vérifier que le modèle est bien chargé dans LM Studio.",
        )
    if statut == 429:
        return ErreurLLM(
            f"Quota atteint (429) sur le profil {profil}.",
            "Attendre la fenêtre de quota, ou basculer de profil : cohera doctor --llm local",
        )
    return ErreurLLM(
        f"Réponse HTTP {statut} du profil {profil}.",
        "Consulter les journaux du fournisseur.",
    )


def completer(
    messages: list[dict[str, str]],
    *,
    profil: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    timeout_s: float | None = None,
    response_format: dict[str, Any] | None = None,
) -> ReponseLLM:
    """Un appel de complétion sur le profil actif. Aucun repli : ce qui échoue se voit.

    Lève ``ErreurLLM`` (porteuse d'un remède) sur tout échec — clé manquante, service
    éteint, quota, dépassement de délai.
    """
    nom, config_profil = reglages.profil_llm(profil)
    delai = timeout_s if timeout_s is not None else reglages.charger().llm.timeout_s

    cle = reglages.secret(config_profil.cle_api_env)
    if config_profil.cle_api_env and not cle:
        raise ErreurLLM(
            f"Le profil {nom} exige une clé d'API, et {config_profil.cle_api_env} est vide.",
            f"Copier .env.example vers .env et y renseigner {config_profil.cle_api_env}.",
        )

    entetes = {"Content-Type": "application/json"}
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"

    corps: dict[str, Any] = {
        "model": config_profil.modele,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        corps["max_tokens"] = max_tokens
    if response_format is not None:
        corps["response_format"] = response_format

    debut = time.perf_counter()
    try:
        reponse = httpx.post(
            _url_completions(config_profil.base_url),
            json=corps,
            headers=entetes,
            timeout=delai,
        )
    except httpx.TimeoutException as exc:
        raise ErreurLLM(
            f"Aucune réponse du profil {nom} en {delai:.0f} s.",
            "Modèle trop lourd pour la machine, ou service saturé. Réduire le modèle, "
            "augmenter llm.timeout_s, ou basculer de profil (--llm).",
        ) from exc
    except httpx.ConnectError as exc:
        remede = (
            "Lancer LM Studio, charger un modèle, et démarrer le serveur local "
            f"(attendu sur {config_profil.base_url})."
            if config_profil.cle_api_env is None
            else f"Vérifier la connectivité réseau vers {config_profil.base_url}."
        )
        raise ErreurLLM(f"Connexion impossible au profil {nom}.", remede) from exc

    latence_ms = (time.perf_counter() - debut) * 1000

    if reponse.status_code != 200:
        raise _diagnostiquer_statut(
            reponse.status_code, nom, config_profil.modele, config_profil.cle_api_env
        )

    try:
        donnees = reponse.json()
        texte = donnees["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ErreurLLM(
            f"Réponse inexploitable du profil {nom} : format inattendu.",
            "Le fournisseur n'est peut-être pas compatible OpenAI sur cet endpoint.",
        ) from exc

    return ReponseLLM(
        texte=texte.strip(), profil=nom, modele=config_profil.modele, latence_ms=latence_ms
    )


def completer_avec_repli(
    messages: list[dict[str, str]], **kwargs: Any
) -> ReponseLLM:
    """Comme :func:`completer`, mais parcourt ``llm.repli`` si le profil actif échoue.

    Fonction **distincte**, et non un drapeau de :func:`completer`, précisément pour que
    ``cohera doctor`` ne puisse pas basculer par accident : un repli silencieux pendant
    un diagnostic afficherait du vert en masquant un profil cassé.
    """
    profils = [reglages.nom_profil_llm(kwargs.pop("profil", None))] + reglages.charger().llm.repli
    derniere: ErreurLLM | None = None

    for nom in profils:
        try:
            return completer(messages, profil=nom, **kwargs)
        except ErreurLLM as exc:
            derniere = exc

    assert derniere is not None  # la liste contient toujours au moins le profil actif
    raise derniere


def ping(profil: str | None = None, timeout_s: float | None = None) -> ReponseLLM:
    """Appel trivial pour prouver que le profil actif répond, et en combien de temps."""
    return completer(
        [{"role": "user", "content": PROMPT_PING}],
        profil=profil,
        temperature=0.0,
        max_tokens=8,
        timeout_s=timeout_s,
    )
