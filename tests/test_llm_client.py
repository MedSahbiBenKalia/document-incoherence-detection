"""llm.py — cache disque par hash, compteurs, réparation bornée, bascule de profil.

**Aucun test ici ne touche le réseau.** Le transport est injecté, exactement comme
`test_embeddings.py` injecte un encodeur : c'est ce qui rend « même prompt deux fois, un
seul appel réseau » vérifiable en une seconde, sans serveur et sans modèle.

Le cache est systématiquement redirigé vers `tmp_path` : aucun test ne pollue le `.cache/`
du dépôt, et aucun ne dépend de ce qu'une exécution précédente y aurait laissé.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from cohera import llm, reglages


# ------------------------------------------------------------------------ le harnais


class TransportCompteur:
    """Transport factice : réponses scriptées, et il retient ce qu'on lui a demandé.

    Sur le modèle d'`EncodeurCompteur` de `test_embeddings.py`. Il enregistre le profil et
    le modèle vus à chaque appel, ce qui permet de prouver la bascule A→B sans réseau.
    """

    def __init__(self, *reponses: str) -> None:
        self.reponses = list(reponses) or ["OK"]
        self.appels: list[dict] = []

    def __call__(self, messages, *, profil, modele, temperature, max_tokens, response_format):
        self.appels.append(
            {
                "messages": messages, "profil": profil, "modele": modele,
                "temperature": temperature, "response_format": response_format,
            }
        )
        texte = self.reponses[min(len(self.appels) - 1, len(self.reponses) - 1)]
        return llm.ReponseLLM(
            texte=texte, profil=profil, modele=modele, latence_ms=1.0,
            tokens_prompt=11, tokens_completion=7,
        )

    @property
    def nb_appels(self) -> int:
        return len(self.appels)


class TransportEnPanne:
    """Transport qui échoue toujours — le service éteint, vu depuis le code appelant."""

    def __init__(self) -> None:
        self.nb_appels = 0

    def __call__(self, *args, **kwargs):
        self.nb_appels += 1
        raise llm.ErreurLLM("service injoignable", "Lancer LM Studio.")


@pytest.fixture
def cache_isole(tmp_path, monkeypatch):
    """Redirige le cache disque vers `tmp_path`."""
    monkeypatch.setattr(llm, "dossier_cache", lambda: tmp_path / "llm")
    return tmp_path


class Verdict(BaseModel):
    verdict: str
    confiance: float


# ------------------------------------------------------------------ le cache par hash


def test_meme_prompt_deux_fois_un_seul_appel_reseau(cache_isole) -> None:
    """**Le critère du J6** : « Même prompt envoyé deux fois → un seul appel réseau ».

    C'est ce qui rend le budget tenable et le scénario incrémental du J7 crédible : la
    seconde exécution du pipeline ne doit rien coûter."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "Deux clauses divergent-elles ?"}]
    compteurs = llm.Compteurs()

    premiere = llm.completer(messages, transport=transport, compteurs=compteurs)
    seconde = llm.completer(messages, transport=transport, compteurs=compteurs)

    assert transport.nb_appels == 1
    assert compteurs.appels_reseau == 1
    assert compteurs.servis_par_cache == 1
    assert premiere.texte == seconde.texte
    assert not premiere.depuis_cache and seconde.depuis_cache


def test_un_acces_servi_par_le_cache_ne_consomme_pas_de_budget(cache_isole) -> None:
    """Le budget se compte en appels **réseau**. Sans cette distinction, une seconde
    exécution atteindrait le plafond sans avoir rien dépensé, et marquerait à tort des
    paires en NON_VERIFIEE_BUDGET."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "x"}]
    compteurs = llm.Compteurs()

    for _ in range(5):
        llm.completer(messages, transport=transport, compteurs=compteurs)

    assert compteurs.appels_reseau == 1
    assert compteurs.servis_par_cache == 4
    assert compteurs.total == 5
    assert compteurs.taux_cache == pytest.approx(0.8)


def test_les_tokens_ne_sont_comptes_que_sur_le_reseau(cache_isole) -> None:
    """Un jeton servi par le cache n'a été facturé par personne."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "x"}]
    compteurs = llm.Compteurs()

    llm.completer(messages, transport=transport, compteurs=compteurs)
    llm.completer(messages, transport=transport, compteurs=compteurs)

    assert (compteurs.tokens_prompt, compteurs.tokens_completion) == (11, 7)


@pytest.mark.parametrize(
    "champ, valeur",
    [("temperature", 0.9), ("response_format", {"type": "json_object"})],
)
def test_la_cle_distingue_ce_qui_change_la_reponse(cache_isole, champ, valeur) -> None:
    """Température et format de sortie changent la réponse : ils doivent changer la clé.

    Sinon un appel à T=0,0 servirait la réponse mémorisée d'un appel à T=0,9."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "x"}]

    llm.completer(messages, transport=transport)
    llm.completer(messages, transport=transport, **{champ: valeur})

    assert transport.nb_appels == 2


def test_la_cle_distingue_les_profils_et_les_modeles() -> None:
    """**La panne silencieuse qu'on refuse.** Basculer de LM Studio à Gemini ne doit pas
    relire les verdicts de l'autre : ce serait une ablation qui mesure le mauvais modèle
    sans rien signaler. Même raison que le nom du modèle dans la clé d'`embeddings`."""
    messages = [{"role": "user", "content": "x"}]
    base = dict(temperature=0.2, response_format=None)

    cles = {
        llm.cle_cache(messages, profil="local", modele="mistral-7b", **base),
        llm.cle_cache(messages, profil="gemini", modele="mistral-7b", **base),
        llm.cle_cache(messages, profil="local", modele="gemini-2.5-flash", **base),
    }
    assert len(cles) == 3


def test_un_fichier_de_cache_tronque_est_traite_comme_absent(cache_isole) -> None:
    """Une interruption en cours d'écriture ne doit pas faire échouer l'exécution suivante.
    Même politique que le cache d'embeddings : illisible = absent, jamais fatal."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "x"}]
    llm.completer(messages, transport=transport)

    for fichier in (cache_isole / "llm").rglob("*.json"):
        fichier.write_text("{ tronqu", encoding="utf-8")

    assert llm.completer(messages, transport=transport).texte == "OK"
    assert transport.nb_appels == 2


def test_le_cache_peut_etre_desactive(cache_isole) -> None:
    """`utiliser_cache=False` : ce que fait `ping`, pour qu'un diagnostic diagnostique."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "x"}]

    llm.completer(messages, transport=transport, utiliser_cache=False)
    llm.completer(messages, transport=transport, utiliser_cache=False)

    assert transport.nb_appels == 2


# ------------------------------------------------------- sortie JSON et réparation


def test_un_json_valide_du_premier_coup_ne_declenche_pas_de_reparation(cache_isole) -> None:
    transport = TransportCompteur(json.dumps({"verdict": "COHERENT", "confiance": 0.8}))
    compteurs = llm.Compteurs()

    statut = llm.completer_json(
        [{"role": "user", "content": "x"}], Verdict, transport=transport, compteurs=compteurs
    )

    assert statut.ok and not statut.reparé
    assert statut.objet.verdict == "COHERENT"
    assert compteurs.reparations == 0
    assert transport.nb_appels == 1


def test_json_invalide_puis_reparation_reussie(cache_isole) -> None:
    """La boucle de réparation d'architecture.md §4.4, bornée à **un** essai."""
    transport = TransportCompteur(
        "je pense que oui",
        json.dumps({"verdict": "INCOHERENCE", "confiance": 0.9}),
    )
    compteurs = llm.Compteurs()

    statut = llm.completer_json(
        [{"role": "user", "content": "x"}], Verdict, transport=transport, compteurs=compteurs
    )

    assert statut.ok and statut.reparé
    assert statut.objet.verdict == "INCOHERENCE"
    assert compteurs.reparations == 1
    assert transport.nb_appels == 2


def test_json_invalide_deux_fois_donne_extraction_incertaine_sans_exception(cache_isole) -> None:
    """**Critère du J6** : « JSON invalide injecté → réparation puis EXTRACTION_INCERTAINE,
    aucune exception ne remonte ».

    Le statut est une valeur de retour, pas une exception : l'appelant traite l'échec comme
    une abstention et poursuit son parcours de paires."""
    transport = TransportCompteur("n'importe quoi", "toujours pas du JSON")
    compteurs = llm.Compteurs()

    statut = llm.completer_json(
        [{"role": "user", "content": "x"}], Verdict, transport=transport, compteurs=compteurs
    )

    assert not statut.ok
    assert statut.objet is None
    assert statut.motif == "EXTRACTION_INCERTAINE"
    assert compteurs.reparations == 1 and compteurs.echecs == 1
    assert transport.nb_appels == 2  # un essai, une réparation, et on s'arrête


def test_la_reparation_est_bornee_a_un_seul_essai(cache_isole) -> None:
    """Le pendant négatif du test précédent : jamais de troisième appel. Sans cette borne,
    un modèle qui bavarde consommerait le budget entier sur une seule paire."""
    transport = TransportCompteur("pas du JSON")
    llm.completer_json([{"role": "user", "content": "x"}], Verdict, transport=transport)
    assert transport.nb_appels == 2


def test_un_json_enrobe_de_balises_de_code_est_recupere_sans_reparation(cache_isole) -> None:
    """Un modèle non contraint encadre volontiers son objet de ```json … ```. Dépenser une
    réparation — donc un appel réseau, donc du budget — pour cela serait du gaspillage."""
    transport = TransportCompteur(
        '```json\n{"verdict": "INDECIDABLE", "confiance": 0.5}\n```'
    )
    compteurs = llm.Compteurs()

    statut = llm.completer_json(
        [{"role": "user", "content": "x"}], Verdict, transport=transport, compteurs=compteurs
    )

    assert statut.ok and statut.objet.verdict == "INDECIDABLE"
    assert compteurs.reparations == 0 and transport.nb_appels == 1


def test_une_panne_de_transport_remonte_et_n_est_pas_confondue_avec_un_defaut_de_format(
    cache_isole,
) -> None:
    """`ErreurLLM` traverse `completer_json` : c'est une panne de service, pas un JSON mal
    formé. Le juge doit pouvoir les distinguer — l'une déclenche son coupe-circuit,
    l'autre non."""
    transport = TransportEnPanne()
    with pytest.raises(llm.ErreurLLM):
        llm.completer_json([{"role": "user", "content": "x"}], Verdict, transport=transport)
    assert transport.nb_appels == 1  # pas de réparation sur une panne


# --------------------------------------------------------------------- le budget


def test_le_budget_est_consulte_apres_le_cache_et_non_avant(cache_isole) -> None:
    """**L'ordre est le fond du garde-fou n°5**, pas un détail d'implémentation.

    Un accès servi par le cache ne coûte rien : il doit passer **même à budget nul**. Si le
    plafond était lu avant le cache, la seconde exécution du pipeline marquerait toutes les
    paires en NON_VERIFIEE_BUDGET sans avoir rien dépensé, et deux rapports du même corpus
    différeraient."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "x"}]

    llm.completer(messages, transport=transport)  # remplit le cache

    servi = llm.completer(messages, transport=transport, budget_disponible=lambda: False)
    assert servi.depuis_cache and servi.texte == "OK"
    assert transport.nb_appels == 1


def test_le_budget_epuise_bloque_un_appel_reseau(cache_isole) -> None:
    """Le pendant : sur un cache manqué, le plafond interdit la sortie réseau."""
    transport = TransportCompteur("OK")
    with pytest.raises(llm.BudgetEpuise):
        llm.completer(
            [{"role": "user", "content": "jamais vu"}],
            transport=transport, budget_disponible=lambda: False,
        )
    assert transport.nb_appels == 0


def test_budget_epuise_n_est_pas_une_erreur_llm(cache_isole) -> None:
    """Deux situations, deux réactions opposées : une panne doit déclencher un
    coupe-circuit, un plafond ne dit rien de la santé du service. Les confondre ferait
    couper le circuit à chaque fin de budget."""
    assert not issubclass(llm.BudgetEpuise, llm.ErreurLLM)


# ------------------------------------------------------------- la bascule de profil


def test_la_bascule_de_profil_tient_dans_une_variable_d_environnement(
    cache_isole, monkeypatch
) -> None:
    """**Critère du J6** : « bascule de profil A→B par une seule variable d'environnement,
    aucun changement de code ».

    Le même appel, inchangé, part sur un autre fournisseur et un autre modèle. On l'observe
    par ce que voit le transport, pas par ce que dit la configuration."""
    transport = TransportCompteur("OK")
    messages = [{"role": "user", "content": "x"}]

    monkeypatch.setenv("COHERA_LLM", "local")
    llm.completer(messages, transport=transport)

    monkeypatch.setenv("COHERA_LLM", "groq")
    llm.completer(messages, transport=transport)

    profils = [appel["profil"] for appel in transport.appels]
    modeles = [appel["modele"] for appel in transport.appels]
    assert profils == ["local", "groq"]
    assert modeles[0] != modeles[1]
    assert modeles == [
        reglages.charger().llm.profils["local"].modele,
        reglages.charger().llm.profils["groq"].modele,
    ]


@pytest.mark.parametrize(
    "profil, attendu",
    [
        ("gemini", "json_schema"),
        ("groq", "json_object"),
        # ⚠️ Mesuré au J6, et c'est un écart à architecture.md §4.4 : LM Studio + ce GGUF
        # rejettent TOUT schéma en HTTP 400 (« Unexpected empty grammar stack ») et
        # refusent aussi json_object. Il ne reste que le texte libre, et c'est la boucle
        # de réparation qui porte la contrainte de forme. Le détail est dans
        # `config/technique.yaml`, profil `local`.
        ("local", None),
    ],
)
def test_le_format_de_sortie_suit_le_profil(cache_isole, monkeypatch, profil, attendu) -> None:
    """`ProfilLLM.format_sortie` était `json_schema: bool` et jamais lu avant le J6. La
    mesure a montré qu'il fallait **trois** valeurs et non deux : contraindre par schéma,
    contraindre par `json_object`, ou ne rien pouvoir contraindre du tout."""
    monkeypatch.setenv("COHERA_LLM", profil)
    transport = TransportCompteur(json.dumps({"verdict": "COHERENT", "confiance": 0.5}))
    llm.completer_json([{"role": "user", "content": "x"}], Verdict, transport=transport)

    format_vu = transport.appels[0]["response_format"]
    if attendu is None:
        assert format_vu is None
    else:
        assert format_vu["type"] == attendu


def test_le_schema_strict_est_epure_et_complet(cache_isole) -> None:
    """Deux exigences opposées sur le même objet.

    Le mode strict d'OpenAI impose `required` sur toutes les propriétés et
    `additionalProperties: false` — qu'un schéma pydantic ne produit pas seul, nos champs
    ayant tous une valeur par défaut. À l'inverse, les `title`/`description` que pydantic
    tire des docstrings n'ont rien à faire dans une grammaire de décodage : c'est de la
    prose française, accents compris, facturée en jetons de prompt."""
    schema = llm.schema_reponse("v", Verdict)["json_schema"]["schema"]

    assert schema["required"] == ["confiance", "verdict"]
    assert schema["additionalProperties"] is False
    serialise = json.dumps(schema)
    assert "title" not in serialise and "description" not in serialise


def test_un_profil_inconnu_se_voit_immediatement(monkeypatch) -> None:
    """Le pendant négatif : une faute de frappe dans COHERA_LLM ne doit pas se dégrader en
    repli silencieux. Comportement déjà en place dans `reglages`, figé ici parce que la
    bascule par variable d'environnement devient un critère du J6."""
    monkeypatch.setenv("COHERA_LLM", "gemni")
    with pytest.raises(KeyError, match="gemni"):
        llm.completer([{"role": "user", "content": "x"}], transport=TransportCompteur())
