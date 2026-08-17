"""graphe/arbitrage_alias.py — usage n°1 du J6 : trancher la zone grise des alias.

Hors ligne : transport injecté, pont construit à la main. Ce qu'on vérifie est la
discipline de l'arbitrage — un « oui » peu assuré ne vaut pas mieux qu'un silence, une
panne ne fabrique pas de « non », une arête retenue réélit les classes canoniques.
"""

from __future__ import annotations

import json

import pytest

from cohera import llm
from cohera.graphe import arbitrage_alias
from cohera.graphe.alias import Methode, PaireGrise, Pont
from tests.test_llm_client import TransportCompteur, TransportEnPanne, cache_isole  # noqa: F401


@pytest.fixture
def paires() -> list[PaireGrise]:
    """Les deux paires réellement présentes dans `zone_grise.jsonl` au J6."""
    return [
        PaireGrise(
            concept_a="OBJET:equipements de protection",
            concept_b="OBJET:port des equipements de protection individuelle",
            libelle_a="équipements de protection",
            libelle_b="port des équipements de protection individuelle",
            score=0.856,
        ),
        PaireGrise(
            concept_a="OBJET:minimum sauveteurs secouristes du travail",
            concept_b="OBJET:nombre minimal de sauveteurs secouristes du travail presents",
            libelle_a="minimum sauveteurs secouristes du travail",
            libelle_b="nombre minimal de sauveteurs secouristes du travail présents",
            score=0.852,
        ),
    ]


def reponse(**champs) -> str:
    base = {"alias": True, "confiance": 0.9, "justification": "Même notion."}
    return json.dumps(base | champs, ensure_ascii=False)


# ------------------------------------------------------------------------ le positif


def test_un_alias_confirme_produit_une_arete_de_methode_llm(paires, cache_isole) -> None:
    """L'arête porte `methode = LLM` : c'est ce qui la rend **révisable** dans le rapport.
    Un alias arbitré par un modèle n'a pas le même statut qu'une égalité de surface."""
    transport = TransportCompteur(reponse())
    pont = Pont(zone_grise=list(paires))

    resultat = arbitrage_alias.arbitrer(paires, transport=transport)
    ajoutees = arbitrage_alias.appliquer(pont, paires, resultat)

    assert transport.nb_appels == 2  # un appel par paire, pas un de plus
    assert ajoutees == 2
    assert all(a.methode is Methode.LLM for a in pont.aretes)
    assert pont.zone_grise == []  # la bande est vidée de ce qui a été tranché


def test_deux_appels_pour_deux_paires_c_est_le_budget_annonce(paires, cache_isole) -> None:
    """Le J6 chiffre « 2 appels sur fixtures » pour cet usage. Le test le fige : si la zone
    grise grossit, le budget du juge s'en trouve réduit d'autant, et il faut le voir."""
    transport = TransportCompteur(reponse())
    compteurs = llm.Compteurs()
    arbitrage_alias.arbitrer(paires, transport=transport, compteurs=compteurs)
    assert compteurs.appels_reseau == len(paires) == 2


# ------------------------------------------------------------------------ les négatifs


def test_un_refus_ne_produit_aucune_arete_mais_reste_trace(paires, cache_isole) -> None:
    """Le pendant négatif. La décision est conservée même quand elle est « non » : sans
    cela, on ne saurait pas distinguer « arbitré et rejeté » de « jamais soumis »."""
    transport = TransportCompteur(reponse(alias=False, justification="Portées différentes."))
    pont = Pont(zone_grise=list(paires))

    resultat = arbitrage_alias.arbitrer(paires, transport=transport)
    assert arbitrage_alias.appliquer(pont, paires, resultat) == 0
    assert pont.aretes == []
    assert len(resultat.arbitrages) == 2
    assert all("Portées différentes." in a.justification for a in resultat.arbitrages)
    assert pont.zone_grise == paires  # rien n'a été tranché, la bande est intacte


def test_un_oui_peu_assure_est_refuse(paires, cache_isole) -> None:
    """Risque n°1 d'architecture.md §13 : « alias erronés … faux positifs en cascade ». Un
    alias douteux coûte des dizaines de fausses incohérences ; un alias manqué en coûte une.
    Le plancher de confiance tranche dans ce sens-là."""
    transport = TransportCompteur(reponse(confiance=0.4))
    resultat = arbitrage_alias.arbitrer(paires, transport=transport, confiance_min=0.7)

    assert resultat.aretes_ajoutees == []
    assert all(not a.alias for a in resultat.arbitrages)


def test_une_panne_ne_fabrique_pas_un_refus(paires, cache_isole) -> None:
    """**La distinction qui compte** : un échec d'arbitrage se lit « non tranché », jamais
    « pas alias ». Confondre les deux ferait passer une panne de service pour une décision
    terminologique, et la zone grise disparaîtrait du rapport sans que rien ne l'ait jugée."""
    pont = Pont(zone_grise=list(paires))
    resultat = arbitrage_alias.arbitrer(paires, transport=TransportEnPanne())

    assert resultat.abstentions == 2
    assert all(a.abstention and not a.retenu for a in resultat.arbitrages)
    assert arbitrage_alias.appliquer(pont, paires, resultat) == 0
    assert pont.zone_grise == paires


def test_un_json_irreparable_devient_une_abstention(paires, cache_isole) -> None:
    transport = TransportCompteur("pas du JSON", "toujours pas")
    resultat = arbitrage_alias.arbitrer(paires[:1], transport=transport)
    assert resultat.abstentions == 1
    assert "schéma" in resultat.arbitrages[0].abstention


def test_le_budget_epuise_abstient_au_lieu_de_lever(paires, cache_isole) -> None:
    """Même discipline que le juge : le plafond dégrade, il n'interrompt pas."""
    resultat = arbitrage_alias.arbitrer(
        paires, transport=TransportCompteur(reponse()), budget_disponible=lambda: False
    )
    assert resultat.abstentions == 2
    assert all("plafond" in a.abstention for a in resultat.arbitrages)


# ---------------------------------------------------- l'effet sur le reste du pipeline


def test_une_arete_retenue_reelit_les_classes_canoniques(paires, cache_isole) -> None:
    """**L'arbitrage ne sert à rien s'il n'est pas propagé.** C'est la réélection qui fait
    que deux concepts fusionnés comptent désormais comme un objet partagé — donc ce qui
    peut débloquer une paire à l'étage A. Sans elle, l'arête serait écrite et inerte."""

    class ConceptFactice:
        def __init__(self, concept_id: str, frequence: int) -> None:
            self.concept_id, self.frequence = concept_id, frequence

    class VocabulaireFactice:
        def __init__(self, ids: list[str]) -> None:
            self.concepts = {i: ConceptFactice(i, 1) for i in ids}

    paire = paires[0]
    vocabulaire = VocabulaireFactice([paire.concept_a, paire.concept_b])
    pont = Pont(zone_grise=[paire])

    resultat = arbitrage_alias.arbitrer([paire], transport=TransportCompteur(reponse()))
    arbitrage_alias.appliquer(pont, [paire], resultat, vocabulaire)

    assert pont.canoniques[paire.concept_a] == pont.canoniques[paire.concept_b]


def test_sans_arete_retenue_les_canoniques_ne_bougent_pas(paires, cache_isole) -> None:
    """Le pendant : un refus ne doit pas réécrire les classes. L'idempotence du chargement
    en dépend — `cle_comparaison` est construite sur ces représentants."""
    pont = Pont(zone_grise=list(paires), canoniques={"X": "X"})
    resultat = arbitrage_alias.arbitrer(
        paires, transport=TransportCompteur(reponse(alias=False))
    )
    arbitrage_alias.appliquer(pont, paires, resultat, vocabulaire=None)
    assert pont.canoniques == {"X": "X"}
