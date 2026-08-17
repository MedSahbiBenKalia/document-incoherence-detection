"""detection/juge_llm.py — l'étage C, ses deux garde-fous, son budget.

**Aucun test ici ne touche le réseau ni ne charge Neo4j.** Le transport est injecté, et la
`Detection` est construite à la main : ce qu'on vérifie est la *logique* du juge — filtre
contraint, abstention, budget, coupe-circuit — et elle se teste hors ligne. Le périmètre
réel sur les 72 paires candidates, lui, exige le pipeline entier : il est dans
`test_cascade.py`, avec le marqueur `neo4j`.

Les deux tests qui comptent le plus sont ici :
* « preuve inventée → verdict annulé » — n°4 des cinq tests du plan ;
* « INDECIDABLE remonte dans le rapport » — le garde-fou n°4 d'architecture.md §7.4.
"""

from __future__ import annotations

import json

import pytest

from cohera import llm
from cohera.detection import config_detection, juge_llm
from cohera.detection.cascade import Detection
from cohera.detection.juge_llm import PaireAJuger, SortieJuge, juger, paires_a_juger
from cohera.detection.modeles import Motif, TypeVerdict, Verdict
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.conditions import construire_algebre
from cohera.ingestion.modeles import Clause
from tests.test_llm_client import TransportCompteur, TransportEnPanne, cache_isole  # noqa: F401


# ------------------------------------------------------------------------ un corpus nain


TEXTE_A = "L'anomalie est signalée au chef d'atelier sous 24 heures."
TEXTE_B = "Les écarts sont remontés à la hiérarchie dans la semaine."


@pytest.fixture
def monde():
    """Deux clauses, deux frames vides, une algèbre — de quoi exercer le juge seul."""
    clauses = {
        "A": Clause(clause_id="A", doc_id="D1", ref="6.2", ordre=1, texte_source=TEXTE_A,
                    texte_autonome=TEXTE_A, offset=(0, len(TEXTE_A))),
        "B": Clause(clause_id="B", doc_id="D2", ref="6.2", ordre=1, texte_source=TEXTE_B,
                    texte_autonome=TEXTE_B, offset=(0, len(TEXTE_B))),
    }
    frames = {"A": ClauseFrame(clause_id="A"), "B": ClauseFrame(clause_id="B")}
    return {
        "clauses": clauses,
        "frames": frames,
        "textes": {"A": TEXTE_A, "B": TEXTE_B},
        "algebre": construire_algebre(frames),
        "objets": {"A": {"anomalie"}, "B": {"ecart"}},
    }


def detection_avec_escalade() -> Detection:
    """Une `Detection` portant une seule paire escaladée — le cas nominal du J6."""
    detection = Detection(paires_examinees=1)
    detection.escalades.append(
        Verdict(detecteur="A2", type=TypeVerdict.CONTRADICTION,
                motif=Motif.OBJETS_SANS_RECOUVREMENT, clause_a="A", clause_b="B",
                explication="même rôle, valeurs différentes, objets sans recouvrement")
    )
    return detection


def reponse(**champs) -> str:
    base = {
        "verdict": "INCOHERENCE", "type": "NUMERIQUE",
        "preuve_a": "sous 24 heures", "preuve_b": "dans la semaine",
        "relation_portees": "IDENTIQUE", "clause_fautive": "B",
        "explication": "Deux délais incompatibles pour le même signalement.",
        "confiance": 0.9,
    }
    return json.dumps(base | champs, ensure_ascii=False)


def _juger(monde, detection, transport, **kwargs):
    return juger(
        detection, monde["clauses"], monde["frames"], monde["textes"],
        monde["algebre"], monde["objets"], transport=transport, **kwargs
    )


# ============================ GARDE-FOU N°1 — LE FILTRE CONTRAINT ============================


def test_une_preuve_inventee_annule_le_verdict_et_produit_une_abstention(
    monde, cache_isole
) -> None:
    """**Test n°4 des cinq qui comptent** (`docs/plan-1-semaine.md` §3) : « Mock renvoyant
    une preuve inventée → verdict annulé, paire en abstention ».

    Ce qu'il empêche : « un LLM qui hallucine une citation pollue le rapport ». Le modèle
    affirme ici une INCOHERENCE parfaitement plausible, avec une citation qui n'existe dans
    aucun des deux textes. Le verdict doit être **annulé**, pas rétrogradé : à la différence
    d'un détecteur symbolique, un LLM peut mentir sur sa preuve."""
    detection = detection_avec_escalade()
    transport = TransportCompteur(reponse(preuve_a="sous 48 heures"))

    resultat = _juger(monde, detection, transport)

    verdict = resultat.verdicts[0]
    assert verdict.type is TypeVerdict.INDECIDABLE
    assert verdict.motif is Motif.PREUVE_INVENTEE
    assert not verdict.ferme
    assert verdict.est_abstention
    assert detection.constatations == []          # rien n'a pollué le rapport
    assert detection.abstentions == [verdict]     # et la paire est visible
    assert resultat.verdicts_annules == 1
    assert resultat.taux_annulation == pytest.approx(1.0)


def test_le_filtre_contraint_verifie_les_DEUX_cotes(monde, cache_isole) -> None:
    """Une preuve juste d'un côté ne rachète pas une preuve inventée de l'autre."""
    transport = TransportCompteur(reponse(preuve_b="sous quinzaine"))
    resultat = _juger(monde, detection_avec_escalade(), transport)
    assert resultat.verdicts[0].motif is Motif.PREUVE_INVENTEE


@pytest.mark.parametrize("manquante", ["preuve_a", "preuve_b"])
def test_une_preuve_absente_vaut_une_preuve_inventee(monde, cache_isole, manquante) -> None:
    """Un verdict sans citation n'est pas plus recevable qu'un verdict mal cité —
    invariant #3 de `CLAUDE.md` : « aucun verdict sans preuve littérale »."""
    transport = TransportCompteur(reponse(**{manquante: ""}))
    resultat = _juger(monde, detection_avec_escalade(), transport)
    assert resultat.verdicts[0].motif is Motif.PREUVE_INVENTEE


def test_le_pendant_positif_une_preuve_litterale_conserve_le_verdict(
    monde, cache_isole
) -> None:
    """**Le négatif du garde-fou** (`CLAUDE.md` : un détecteur = un test positif ET un
    négatif). Sans ce test, un filtre qui annulerait TOUT passerait le test précédent.

    Les deux extraits sont ici des sous-chaînes exactes : le verdict tient, il est ferme,
    il devient une constatation, et il porte l'étage qui l'a produit."""
    detection = detection_avec_escalade()
    resultat = _juger(monde, detection, TransportCompteur(reponse()))

    verdict = resultat.verdicts[0]
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert verdict.motif is Motif.VERDICT_DU_JUGE
    assert verdict.ferme and verdict.est_constatation
    assert verdict.etage == "C"
    assert verdict.preuve_a in TEXTE_A and verdict.preuve_b in TEXTE_B
    assert verdict.plus_permissive == "B"
    assert detection.constatations == [verdict]
    assert resultat.verdicts_annules == 0


# ============================== GARDE-FOU N°2 — L'ABSTENTION ==============================


def test_indecidable_est_une_sortie_legitime_qui_remonte(monde, cache_isole) -> None:
    """Garde-fou n°4 d'architecture.md §7.4 : « un système d'audit qui abstient 8 % est
    infiniment plus utile qu'un système qui tranche à tort 8 % ».

    L'abstention n'est ni un rejet ni une erreur : elle est rangée, nommée, et elle porte
    l'explication du modèle."""
    detection = detection_avec_escalade()
    transport = TransportCompteur(
        reponse(verdict="INDECIDABLE", explication="Les deux objets semblent différents.")
    )

    resultat = _juger(monde, detection, transport)

    verdict = resultat.verdicts[0]
    assert verdict.type is TypeVerdict.INDECIDABLE
    assert verdict.motif is Motif.ABSTENTION_DU_JUGE
    assert verdict.est_abstention
    assert "objets semblent différents" in verdict.explication
    assert detection.abstentions == [verdict]
    assert resultat.verdicts_annules == 0  # une abstention n'est PAS une annulation


def test_un_verdict_peu_confiant_devient_une_abstention(monde, cache_isole) -> None:
    """Le LLM n'est jamais seul décisionnaire d'un verdict grave (§7.4, R2 de §13). Sous le
    plancher de confiance, il informe mais n'affirme pas."""
    transport = TransportCompteur(reponse(confiance=0.3))
    resultat = _juger(monde, detection_avec_escalade(), transport)

    verdict = resultat.verdicts[0]
    assert verdict.type is TypeVerdict.INDECIDABLE and not verdict.ferme
    assert "sous le plancher" in verdict.explication


def test_un_verdict_hors_vocabulaire_ne_devient_pas_une_constatation(
    monde, cache_isole
) -> None:
    """Vocabulaire fermé (§4.4, garde-fou n°4). « INCOHERENT » n'est pas « INCOHERENCE » :
    le modèle n'a pas répondu à la question posée, on s'abstient au lieu de deviner."""
    transport = TransportCompteur(reponse(verdict="INCOHERENT"))
    resultat = _juger(monde, detection_avec_escalade(), transport)

    assert resultat.verdicts[0].type is TypeVerdict.INDECIDABLE
    assert resultat.verdicts[0].motif is Motif.EXTRACTION_INCERTAINE


def test_coherent_clot_la_paire_sans_rien_affirmer(monde, cache_isole) -> None:
    """C'est le verdict attendu sur N08 : le juge conclut à la compatibilité. La paire n'est
    ni une constatation ni une abstention — elle est close, avec sa raison."""
    detection = detection_avec_escalade()
    transport = TransportCompteur(
        reponse(verdict="COHERENT", explication="Les objets n'ont aucun rapport.")
    )
    resultat = _juger(monde, detection, transport)

    assert resultat.verdicts[0].type is TypeVerdict.COHERENT
    assert detection.constatations == [] and detection.abstentions == []
    assert resultat.verdicts[0] in detection.muets


# ================================= LE BUDGET, EN EXÉCUTION =================================


def detection_a_n_paires(n: int) -> tuple[Detection, dict, dict, dict, dict]:
    """`n` paires escaladées, chacune avec ses clauses — pour éprouver le plafond.

    Les textes portent leur indice : sans cela les `n` prompts seraient **byte-identiques**
    et le cache servirait tout après le premier appel, ce qui masquerait complètement le
    comportement du plafond. Le piège vaut d'être nommé — c'est le cache qui a raison.
    """
    detection = Detection(paires_examinees=n)
    clauses, frames, textes, objets = {}, {}, {}, {}
    for i in range(n):
        a, b = f"A{i:03d}", f"B{i:03d}"
        for identifiant, doc, modele in ((a, "D1", TEXTE_A), (b, "D2", TEXTE_B)):
            texte = f"{modele[:-1]} (cas {i})."
            clauses[identifiant] = Clause(
                clause_id=identifiant, doc_id=doc, ref=f"6.{i}", ordre=i,
                texte_source=texte, texte_autonome=texte, offset=(0, len(texte)),
            )
            frames[identifiant] = ClauseFrame(clause_id=identifiant)
            textes[identifiant] = texte
            objets[identifiant] = {"anomalie"}
        detection.escalades.append(
            Verdict(detecteur="A2", type=TypeVerdict.CONTRADICTION,
                    motif=Motif.OBJETS_SANS_RECOUVREMENT, clause_a=a, clause_b=b)
        )
    return detection, clauses, frames, textes, objets


def test_le_plafond_degrade_le_rapport_et_n_interrompt_jamais_le_run(cache_isole) -> None:
    """**Garde-fou n°5 d'architecture.md §7.4** : « paires marquées NON_VERIFIEE_BUDGET,
    jamais silencieusement rejetées ».

    Le point vérifié n'est pas que le plafond compte juste — c'est qu'il **dégrade** :
    aucune exception, le parcours va jusqu'au bout, et chaque paire non vérifiée est
    NOMMÉE. Un run qui s'interromprait à la 3ᵉ paire sur 10 ne dirait pas seulement moins
    de choses : il ne dirait pas *lesquelles* il n'a pas dites."""
    detection, clauses, frames, textes, objets = detection_a_n_paires(10)
    transport = TransportCompteur(reponse())

    resultat = juger(
        detection, clauses, frames, textes, construire_algebre(frames), objets,
        transport=transport, budget=3,
    )

    assert transport.nb_appels == 3
    assert resultat.compteurs.appels_reseau == 3
    assert resultat.paires_soumises == 3
    assert resultat.non_verifiees_budget == 7
    assert len(resultat.verdicts) == 10          # toutes les paires ont un sort

    non_verifiees = [v for v in resultat.verdicts if v.motif is Motif.NON_VERIFIEE_BUDGET]
    assert len(non_verifiees) == 7
    assert all(v.clause_a and v.clause_b for v in non_verifiees)   # nommées, pas comptées
    assert all(v in detection.abstentions for v in non_verifiees)


def test_le_plafond_se_lit_avant_l_appel_et_le_cache_ne_le_consomme_pas(
    cache_isole,
) -> None:
    """La seconde exécution ne doit rien coûter — donc n'atteindre aucun plafond, donc ne
    marquer aucune paire en NON_VERIFIEE_BUDGET. C'est ce qui rend le rapport rejouable."""
    detection, clauses, frames, textes, objets = detection_a_n_paires(4)
    algebre = construire_algebre(frames)
    transport = TransportCompteur(reponse())

    premier = juger(detection, clauses, frames, textes, algebre, objets, transport=transport)
    assert premier.non_verifiees_budget == 0
    assert transport.nb_appels == 4

    detection2, *_ = detection_a_n_paires(4)
    second = juger(
        detection2, clauses, frames, textes, algebre, objets,
        transport=transport, budget=0,
    )
    assert transport.nb_appels == 4                       # zéro appel réseau de plus
    assert second.compteurs.servis_par_cache == 4
    assert second.non_verifiees_budget == 0               # malgré un budget de 0
    assert second.paires_soumises == 4


def test_une_panne_de_service_devient_une_abstention_et_declenche_le_coupe_circuit(
    cache_isole,
) -> None:
    """Sans coupe-circuit, un LM Studio éteint coûte 57 × `timeout_s` (~28 min) avant de
    rendre la main, pour zéro information. Avec, le juge cesse d'appeler après 3 échecs
    consécutifs et marque tout le reste d'un coup — le run se termine, le rapport est écrit,
    rien de ce qui a déjà été payé n'est perdu."""
    detection, clauses, frames, textes, objets = detection_a_n_paires(10)
    transport = TransportEnPanne()

    resultat = juger(
        detection, clauses, frames, textes, construik := construire_algebre(frames), objets,
        transport=transport,
    )

    assert transport.nb_appels == config_detection.echecs_consecutifs_max() == 3
    assert resultat.coupe_circuit
    assert resultat.echecs_transport == 3
    assert len(resultat.verdicts) == 10
    assert all(v.est_abstention for v in resultat.verdicts)
    assert all(v.motif is Motif.LLM_INJOIGNABLE for v in resultat.verdicts)
    assert detection.constatations == []


def test_un_json_irreparable_ne_fait_pas_tomber_le_run(monde, cache_isole) -> None:
    """La troisième panne possible, traitée comme les deux autres : une abstention motivée.
    Le statut `EXTRACTION_INCERTAINE` remonte de `completer_json` sans exception."""
    transport = TransportCompteur("pas du JSON", "toujours pas")
    resultat = _juger(monde, detection_avec_escalade(), transport)

    assert resultat.verdicts[0].motif is Motif.EXTRACTION_INCERTAINE
    assert resultat.verdicts[0].est_abstention
    assert transport.nb_appels == 2  # un essai, une réparation


# ==================================== LE PÉRIMÈTRE ====================================


def _detection_de_motifs(*motifs: Motif) -> Detection:
    detection = Detection()
    for i, motif in enumerate(motifs):
        detection.muets.append(
            Verdict(detecteur="A2", type=TypeVerdict.AUCUNE, motif=motif,
                    clause_a="A", clause_b="B")
        )
    return detection


def test_une_paire_conclue_ne_repart_pas_au_juge(monde) -> None:
    """Invariant #4 : le détecteur le moins cher traite le cas. Repayer un appel LLM sur une
    paire qu'A2 a conclue en comparant deux entiers serait exactement l'inverse."""
    detection = Detection()
    detection.constatations.append(
        Verdict(detecteur="A2", type=TypeVerdict.CONTRADICTION, motif=Motif.VALEURS_DIVERGENTES,
                clause_a="A", clause_b="B", ferme=True)
    )
    assert paires_a_juger(detection, monde["frames"], monde["algebre"]) == []


@pytest.mark.parametrize(
    "motif", [Motif.VALEURS_EGALES, Motif.ECART_DE_FORCE_NUL, Motif.PORTEES_DISJOINTES]
)
def test_un_motif_fermant_clot_la_paire(monde, motif: Motif) -> None:
    """Le symbolique a POSITIVEMENT établi la compatibilité : N06 (12 mois = 1 an), N09
    (même force des deux côtés), N04 (portées disjointes). Rien à demander au LLM."""
    detection = _detection_de_motifs(motif)
    assert paires_a_juger(detection, monde["frames"], monde["algebre"]) == []


@pytest.mark.parametrize(
    "motif",
    [Motif.PAS_DE_GRANDEUR_COMPARABLE, Motif.MODALITE_ABSENTE, Motif.MODALITE_NON_PRESCRIPTIVE],
)
def test_un_silence_faute_de_donnees_envoie_la_paire_au_juge(monde, motif: Motif) -> None:
    """**C'est I11**, et c'est la raison d'être de cet étage. « Arrêtée immédiatement »
    contre « intervient après validation » : ni modalité ni grandeur, donc trois verdicts
    AUCUNE et un rangement dans `muets`, pas dans `escalades`.

    Prendre `Detection.escalades` à la lettre l'écarterait par construction — exactement ce
    que la consigne du J6 refuse. Le tri se fait sur le motif : « je n'ai pas de donnée »
    n'est pas « j'ai établi la compatibilité »."""
    detection = _detection_de_motifs(motif)
    paires = paires_a_juger(detection, monde["frames"], monde["algebre"])
    assert [(p.clause_a, p.clause_b) for p in paires] == [("A", "B")]
    assert paires[0].amont is None
    assert paires[0].motif_amont == "AUCUN_SIGNAL_SYMBOLIQUE"


def test_une_escalade_porte_son_signal_amont_jusqu_au_prompt(monde) -> None:
    """Le « SIGNAL AMONT » d'architecture.md §7.4 : le juge ne redécouvre pas ce que le
    pipeline sait déjà, il en dispose."""
    detection = detection_avec_escalade()
    paires = paires_a_juger(detection, monde["frames"], monde["algebre"])

    assert paires[0].motif_amont == "OBJETS_SANS_RECOUVREMENT"
    contexte = juge_llm.contexte_de_paire(
        paires[0], monde["clauses"], monde["frames"], monde["algebre"], monde["objets"]
    )
    assert "OBJETS_SANS_RECOUVREMENT" in contexte
    assert "OBJETS EN COMMUN     : AUCUN" in contexte
    assert TEXTE_A in contexte and TEXTE_B in contexte


def test_l_anomalie_mono_clause_n_est_jamais_soumise(monde) -> None:
    """I09 et I10 n'ont pas de seconde clause : A5 a conclu seul, sans comparaison. Les
    soumettre au juge serait payer un appel pour une question qui n'existe pas."""
    detection = Detection()
    detection.constatations.append(
        Verdict(detecteur="A5", type=TypeVerdict.CONTRADICTION, motif=Motif.REFERENCE_CASSEE,
                clause_a="A", clause_b=None, ferme=True)
    )
    assert paires_a_juger(detection, monde["frames"], monde["algebre"]) == []


def test_l_ordre_de_soumission_est_stable(cache_isole) -> None:
    """Deux exécutions doivent soumettre les mêmes paires dans le même ordre : sinon le
    plafond couperait ailleurs et deux rapports du même corpus différeraient."""
    detection, _, frames, _, _ = detection_a_n_paires(6)
    algebre = construire_algebre(frames)
    premier = [(p.clause_a, p.clause_b) for p in paires_a_juger(detection, frames, algebre)]
    second = [(p.clause_a, p.clause_b) for p in paires_a_juger(detection, frames, algebre)]
    assert premier == second == sorted(premier)


def test_l_ordre_de_soumission_suit_le_score_rrf_et_non_l_alphabet(cache_isole) -> None:
    """⭐ **Le bug du premier run du J6, figé ici.**

    Les paires étaient triées par identifiant de clause. Le plafond de budget coupait donc
    la liste à un endroit alphabétique, et I03 (D1 §9.2, en fin d'alphabet) n'a jamais été
    soumise — alors que la décision de la journée était précisément d'élargir le périmètre
    « pour qu'aucune cible ne soit écartée par construction ».

    Le tri suit désormais le score de fusion du ciblage : si le plafond mord, il mord les
    paires que le ciblage juge les moins prometteuses. Ici la paire alphabétiquement
    dernière porte le meilleur score, et doit donc passer en premier."""
    detection, _, frames, _, _ = detection_a_n_paires(4)
    algebre = construire_algebre(frames)

    # Score décroissant dans l'ordre alphabétique INVERSE : si le tri suivait encore les
    # identifiants, l'ordre obtenu serait exactement l'inverse de l'ordre attendu.
    scores = {
        frozenset((f"A{i:03d}", f"B{i:03d}")): score
        for i, score in enumerate((0.10, 0.40, 0.70, 0.99))
    }

    ordre = [p.clause_a for p in paires_a_juger(detection, frames, algebre, scores)]
    assert ordre == ["A003", "A002", "A001", "A000"]


def test_sans_score_l_ordre_reste_stable_et_deterministe(cache_isole) -> None:
    """Le pendant : un score absent ne doit pas rendre l'ordre imprévisible. On retombe sur
    les identifiants, qui ont le seul mérite d'être stables d'une exécution à l'autre."""
    detection, _, frames, _, _ = detection_a_n_paires(4)
    algebre = construire_algebre(frames)
    ordre = [p.clause_a for p in paires_a_juger(detection, frames, algebre, {})]
    assert ordre == sorted(ordre)


def test_le_budget_coupe_la_queue_de_la_liste_et_non_une_cible(cache_isole) -> None:
    """La conséquence qui compte, mesurée de bout en bout : à budget serré, ce sont bien les
    paires de plus faible score qui repartent en NON_VERIFIEE_BUDGET."""
    detection, clauses, frames, textes, objets = detection_a_n_paires(4)
    scores = {frozenset((f"A{i:03d}", f"B{i:03d}")): (4 - i) / 10 for i in range(4)}

    resultat = juger(
        detection, clauses, frames, textes, construire_algebre(frames), objets,
        scores=scores, transport=TransportCompteur(reponse()), budget=2,
    )

    non_verifiees = {
        v.clause_a for v in resultat.verdicts if v.motif is Motif.NON_VERIFIEE_BUDGET
    }
    assert non_verifiees == {"A002", "A003"}  # les deux plus faibles scores
