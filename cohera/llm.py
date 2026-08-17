"""Client LLM : un seul transport pour quatre fournisseurs.

LM Studio, Gemini, Groq et OpenRouter exposent tous un endpoint **compatible OpenAI**.
Seuls ``base_url``, ``modele`` et la clé d'API changent d'un profil à l'autre — d'où un
client unique, et zéro ramification par fournisseur dans le code métier.

Basculer se fait à trois niveaux, du plus ponctuel au plus durable ::

    cohera doctor --llm gemini      # cet appel-ci
    $env:COHERA_LLM = "gemini"      # cette session
    # config/technique.yaml : llm.fournisseur

Ce module ne contient que du transport. Les prompts et schémas de sortie propres à
l'extraction vivent dans ``cohera.extraction.llm_client``, ceux du juge dans
``cohera.detection.juge_llm``.

**Cache disque par hash (J6).** Décalqué de ``cohera.embeddings`` : même shardage, même
écriture atomique, même tolérance aux fichiers tronqués. La clé couvre *tout ce qui peut
changer la réponse* — profil, modèle, température, format de sortie, messages — parce
qu'un cache qui ignorerait le modèle rendrait les réponses de l'ancien après un changement
de profil, sans rien signaler.

**Comptage.** :class:`Compteurs` distingue l'appel **réseau** de l'appel **servi par le
cache**. C'est cette distinction qui rend le budget du J6 vérifiable : seul le réseau
coûte, et la seconde exécution du pipeline doit tomber à zéro.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field, ValidationError

from cohera import reglages

# Prompt de vérification : assez court pour qu'un 7B quantifié sur CPU y réponde vite,
# assez contraint pour que la réponse soit vérifiable.
PROMPT_PING = "Réponds uniquement par le mot OK."

#: Longueur de la clé de cache, en caractères hexadécimaux. Aligné sur `embeddings`.
LONGUEUR_CLE = 16


class ErreurLLM(Exception):
    """Échec d'appel au LLM, accompagné du geste qui le corrige.

    Le champ ``remede`` est ce que ``cohera doctor`` affiche en bout de ligne : une
    trace Python n'apprend rien à qui doit juste lancer LM Studio.
    """

    def __init__(self, message: str, remede: str = "") -> None:
        super().__init__(message)
        self.remede = remede


class BudgetEpuise(Exception):
    """Un appel **réseau** était nécessaire, et le plafond est atteint.

    Volontairement **distincte** d'``ErreurLLM`` : une panne de service et un plafond de
    budget appellent des réactions opposées. La panne doit déclencher un coupe-circuit — il
    est inutile de retenter 50 fois un service éteint ; le plafond, lui, n'est pas une
    anomalie et ne dit rien de la santé du service.

    Levée **après** la lecture du cache, jamais avant : un accès mémorisé ne coûte rien et
    doit passer même à budget nul. C'est ce qui rend la seconde exécution du pipeline
    gratuite et son rapport identique au premier.
    """


class ReponseLLM(BaseModel):
    texte: str
    profil: str
    modele: str
    latence_ms: float
    tokens_prompt: int = 0
    tokens_completion: int = 0
    #: `True` si aucun octet n'est passé par le réseau. Ne consomme pas de budget.
    depuis_cache: bool = False


class Compteurs(BaseModel):
    """Ce qu'une exécution a réellement coûté.

    ``appels_reseau`` est la seule grandeur qui compte pour le budget : un accès servi par
    le cache ne paie ni jeton ni latence, et ne doit donc pas rapprocher du plafond.
    """

    appels_reseau: int = 0
    servis_par_cache: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    reparations: int = 0
    echecs: int = 0

    @property
    def total(self) -> int:
        return self.appels_reseau + self.servis_par_cache

    @property
    def taux_cache(self) -> float:
        return self.servis_par_cache / self.total if self.total else 0.0


def _url_completions(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


# ------------------------------------------------------------------ cache disque


def dossier_cache() -> Path:
    """`.cache/llm/` à la racine du dépôt. Créé à la demande, et **monkeypatchable** :
    c'est le point d'injection par lequel les tests évitent de polluer le cache du dépôt."""
    return reglages.racine_projet() / ".cache" / "llm"


def cle_cache(
    messages: list[dict[str, str]],
    *,
    profil: str,
    modele: str,
    temperature: float,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Empreinte stable de tout ce qui détermine la réponse.

    Le modèle **et** le profil entrent dans la clé : basculer de LM Studio à Gemini ne doit
    pas relire les verdicts de l'autre — c'est le genre de panne silencieuse qui ferait
    passer une ablation pour une mesure. La température y entre aussi : à 0,0 et à 0,7 on
    ne pose pas la même question. Le séparateur nul empêche que deux couples différents
    produisent la même concaténation.
    """
    graine = "\0".join(
        (
            profil,
            modele,
            f"{temperature:.4f}",
            json.dumps(response_format, sort_keys=True, ensure_ascii=False) if response_format else "",
            json.dumps(messages, sort_keys=True, ensure_ascii=False),
        )
    ).encode("utf-8")
    return hashlib.sha256(graine).hexdigest()[:LONGUEUR_CLE]


def _chemin_reponse(cle: str, modele: str) -> Path:
    """Shardage sur les deux premiers caractères, comme `embeddings` : un répertoire à
    plusieurs milliers d'entrées est lent à parcourir sous Windows."""
    slug = modele.replace("/", "_").replace("\\", "_").replace(":", "_")
    return dossier_cache() / slug / cle[:2] / f"{cle}.json"


def _lire_cache(cle: str, modele: str) -> ReponseLLM | None:
    chemin = _chemin_reponse(cle, modele)
    if not chemin.is_file():
        return None
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        return ReponseLLM.model_validate(donnees | {"depuis_cache": True})
    except (ValueError, OSError, ValidationError):
        # Fichier tronqué par une interruption : traité comme absent, jamais fatal.
        return None


def _ecrire_cache(cle: str, modele: str, reponse: ReponseLLM) -> None:
    chemin = _chemin_reponse(cle, modele)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # Écriture atomique : un JSON à moitié écrit serait relu comme une réponse valide.
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(
        json.dumps(reponse.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    provisoire.replace(chemin)


def vider_cache_disque(modele: str | None = None) -> int:
    """Efface les réponses mémorisées. Renvoie le nombre de fichiers retirés."""
    import shutil

    cible = dossier_cache()
    if modele:
        cible = cible / modele.replace("/", "_").replace("\\", "_").replace(":", "_")
    if not cible.is_dir():
        return 0
    nombre = sum(1 for _ in cible.rglob("*.json"))
    shutil.rmtree(cible)
    return nombre


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
    transport: Callable[..., ReponseLLM] | None = None,
    utiliser_cache: bool = True,
    compteurs: Compteurs | None = None,
    budget_disponible: Callable[[], bool] | None = None,
) -> ReponseLLM:
    """Un appel de complétion sur le profil actif. Aucun repli : ce qui échoue se voit.

    Lève ``ErreurLLM`` (porteuse d'un remède) sur tout échec — clé manquante, service
    éteint, quota, dépassement de délai.

    ``transport`` remplace l'appel HTTP par un appelable de même signature. C'est le patron
    de ``embeddings.encoder(encodeur=...)`` : il rend « même prompt deux fois, un seul appel
    réseau » testable en une seconde, sans serveur et sans modèle.

    **Le cache est lu avant tout comptage réseau.** Un accès servi par le cache incrémente
    ``servis_par_cache`` et jamais ``appels_reseau`` : c'est ce qui garantit qu'une seconde
    exécution ne consomme aucun budget.

    ``budget_disponible`` est consulté **une fois le cache manqué**, juste avant de sortir
    sur le réseau ; s'il rend ``False``, :class:`BudgetEpuise` est levée. La politique de
    budget reste ainsi chez l'appelant — ce module ne fait que du transport — tout en étant
    appliquée à l'endroit exact où elle a un sens.
    """
    nom, config_profil = reglages.profil_llm(profil)
    delai = timeout_s if timeout_s is not None else reglages.charger().llm.timeout_s

    empreinte = cle_cache(
        messages,
        profil=nom,
        modele=config_profil.modele,
        temperature=temperature,
        response_format=response_format,
    )
    if utiliser_cache:
        memorisee = _lire_cache(empreinte, config_profil.modele)
        if memorisee is not None:
            if compteurs is not None:
                compteurs.servis_par_cache += 1
            return memorisee

    # Le cache a manqué : à partir d'ici, il faudra le réseau. C'est le seul point où le
    # budget a un sens, et c'est donc le seul endroit où on le consulte.
    if budget_disponible is not None and not budget_disponible():
        raise BudgetEpuise(f"plafond atteint avant un appel au profil {nom}")

    # Cadencement : après le cache et le budget, avant le réseau. Un accès mémorisé
    # n'attend donc jamais, et la seconde exécution reste instantanée.
    if config_profil.pause_entre_appels_s > 0:
        time.sleep(config_profil.pause_entre_appels_s)

    if transport is not None:
        reponse = transport(
            messages,
            profil=nom,
            modele=config_profil.modele,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        if compteurs is not None:
            compteurs.appels_reseau += 1
            compteurs.tokens_prompt += reponse.tokens_prompt
            compteurs.tokens_completion += reponse.tokens_completion
        if utiliser_cache:
            _ecrire_cache(empreinte, config_profil.modele, reponse)
        return reponse

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

    # `usage` est optionnel dans la spécification : LM Studio l'omet selon les versions.
    usage = donnees.get("usage") or {}
    resultat = ReponseLLM(
        texte=texte.strip(),
        profil=nom,
        modele=config_profil.modele,
        latence_ms=latence_ms,
        tokens_prompt=int(usage.get("prompt_tokens") or 0),
        tokens_completion=int(usage.get("completion_tokens") or 0),
    )

    if compteurs is not None:
        compteurs.appels_reseau += 1
        compteurs.tokens_prompt += resultat.tokens_prompt
        compteurs.tokens_completion += resultat.tokens_completion
    if utiliser_cache:
        _ecrire_cache(empreinte, config_profil.modele, resultat)
    return resultat


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
        utiliser_cache=False,  # un diagnostic qui relit un cache ne diagnostique rien
    )


# --------------------------------------------------------------- sortie JSON contrainte


class StatutJson(BaseModel):
    """Le résultat d'un appel JSON, **jamais une exception**.

    ``objet`` vaut ``None`` quand ni l'appel ni la réparation n'ont produit de JSON
    conforme. L'appelant traite ce cas comme une abstention ; il ne le rattrape pas dans un
    ``try``. C'est la contrepartie du garde-fou n°5 d'architecture.md §4.4 : « boucle de
    réparation bornée à 1 essai, sinon clause marquée EXTRACTION_INCERTAINE ».
    """

    objet: Any = None
    reparé: bool = False
    motif: str = ""
    brut: str = ""

    @property
    def ok(self) -> bool:
        return self.objet is not None


#: Consigne de réparation. Volontairement sèche : on ne renégocie pas le fond, on redemande
#: la forme. Un modèle à qui l'on réexplique la tâche produit souvent un autre contenu.
CONSIGNE_REPARATION = (
    "Ta réponse précédente n'était pas un JSON valide conforme au schéma demandé. "
    "Renvoie EXACTEMENT le même contenu, corrigé, en JSON strict et rien d'autre : "
    "pas de texte avant, pas de texte après, pas de balises de code."
)


def _extraire_json(texte: str) -> Any:
    """Analyse le texte en JSON, en tolérant les enrobages les plus courants.

    Un modèle non contraint encadre volontiers son objet de ```json … ``` ou d'une phrase
    de politesse. Récupérer cela ici évite de dépenser une réparation — donc un appel
    réseau, donc du budget — pour un défaut purement cosmétique.
    """
    depouille = texte.strip()
    if depouille.startswith("```"):
        depouille = depouille.split("```")[1] if "```" in depouille[3:] else depouille[3:]
        if depouille.lstrip().lower().startswith("json"):
            depouille = depouille.lstrip()[4:]
    depouille = depouille.strip()
    try:
        return json.loads(depouille)
    except ValueError:
        pass
    # Dernier recours : le plus grand objet accolé entre la première `{` et la dernière `}`.
    debut, fin = depouille.find("{"), depouille.rfind("}")
    if debut != -1 and fin > debut:
        try:
            return json.loads(depouille[debut : fin + 1])
        except ValueError:
            return None
    return None


def _epurer(noeud: Any) -> Any:
    """Retire `title` et `description` d'un schéma JSON, récursivement.

    Pydantic y verse les docstrings du modèle : des pages de prose française, accents
    compris, dans un objet qui sera compilé en grammaire de décodage. Inutile pour
    contraindre la forme, et coûteux en jetons de prompt.
    """
    if isinstance(noeud, dict):
        return {c: _epurer(v) for c, v in noeud.items() if c not in ("title", "description")}
    if isinstance(noeud, list):
        return [_epurer(v) for v in noeud]
    return noeud


def schema_reponse(nom: str, modele: type[BaseModel], *, strict: bool = True) -> dict[str, Any]:
    """Le ``response_format`` d'un modèle pydantic, au format OpenAI ``json_schema``.

    Le mode strict d'OpenAI impose que **toutes** les propriétés soient dans ``required`` et
    qu'``additionalProperties`` vaille ``false`` ; un schéma pydantic ne le fait pas seul,
    parce que nos champs ont tous une valeur par défaut.
    """
    schema = _epurer(modele.model_json_schema())
    if strict:
        schema["required"] = sorted(schema.get("properties", {}))
        schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "json_schema": {"name": nom, "strict": strict, "schema": schema},
    }


def completer_json(
    messages: list[dict[str, str]],
    modele_sortie: type[BaseModel],
    *,
    nom_schema: str = "reponse",
    profil: str | None = None,
    temperature: float = 0.2,
    compteurs: Compteurs | None = None,
    **kwargs: Any,
) -> StatutJson:
    """Un appel dont la sortie est validée contre ``modele_sortie``. **Ne lève jamais.**

    Le format de sortie suit ``ProfilLLM.format_sortie`` : décodage contraint par JSON
    Schema (Gemini), ``json_object`` (Groq, OpenRouter), ou **rien du tout** — c'est le cas
    mesuré du profil ``local``, où le moteur de grammaire refuse tout schéma. Moins le
    fournisseur contraint, plus la boucle de réparation travaille.

    **Une seule tentative de réparation**, comme le prescrit §4.4. Au-delà, statut
    ``EXTRACTION_INCERTAINE`` — l'appelant décide, personne ne relance.

    ``ErreurLLM`` **remonte** : c'est une panne de transport, pas un défaut de format, et
    l'appelant doit pouvoir la distinguer pour déclencher son coupe-circuit.
    """
    _, config_profil = reglages.profil_llm(profil)
    format_sortie: dict[str, Any] | None = None
    if config_profil.format_sortie == "json_schema":
        format_sortie = schema_reponse(nom_schema, modele_sortie)
    elif config_profil.format_sortie == "json_object":
        format_sortie = {"type": "json_object"}

    def tenter(conversation: list[dict[str, str]]) -> tuple[Any, str]:
        reponse = completer(
            conversation,
            profil=profil,
            temperature=temperature,
            response_format=format_sortie,
            compteurs=compteurs,
            **kwargs,
        )
        brut = _extraire_json(reponse.texte)
        if brut is None:
            return None, reponse.texte
        try:
            return modele_sortie.model_validate(brut), reponse.texte
        except ValidationError:
            return None, reponse.texte

    objet, brut = tenter(messages)
    if objet is not None:
        return StatutJson(objet=objet, brut=brut)

    if compteurs is not None:
        compteurs.reparations += 1
    reparation = [*messages, {"role": "assistant", "content": brut},
                  {"role": "user", "content": CONSIGNE_REPARATION}]
    objet, brut = tenter(reparation)
    if objet is not None:
        return StatutJson(objet=objet, reparé=True, brut=brut)

    if compteurs is not None:
        compteurs.echecs += 1
    return StatutJson(motif="EXTRACTION_INCERTAINE", brut=brut)
