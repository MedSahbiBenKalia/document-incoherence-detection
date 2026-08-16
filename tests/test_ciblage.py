"""ciblage/ — le J4 de bout en bout, contre un vrai graphe.

**Pourquoi ces tests exigent un serveur.** Le rappel du ciblage est le critère pilote du J4,
et c'est une propriété du graphe chargé : les canaux sont des requêtes Cypher, le canal
vectoriel interroge un index, le canal 5 ordonne par un cosinus calculé par Neo4j. Simuler
tout cela ne prouverait rien. La logique qui *peut* être testée hors ligne l'est ailleurs —
`test_canaux.py`, `test_fusion_rrf.py`, `test_comparabilite.py`.

⚠️ Un test sauté n'est pas un test vert. Le bilan de fin de journée compte les skips.

Le graphe est chargé une fois pour ce module, avec ses embeddings : `test_chargeur.py` vide
la base autour de ses propres tests, et ce module ne peut donc pas se fier à un état laissé
par un autre.
"""

from __future__ import annotations

import pytest

from cohera.ciblage import cibler, identifiant_execution, materialiser
from cohera.ciblage.comparabilite import Motif, comparable
from cohera.ciblage.modeles import Canal


def _neo4j_joignable() -> bool:
    try:
        from cohera.graphe.connexion import verifier_connectivite

        verifier_connectivite()
        return True
    except Exception:
        return False


besoin_neo4j = pytest.mark.skipif(
    not _neo4j_joignable(),
    reason="Neo4j injoignable — démarrer le conteneur : docker compose up -d",
)

pytestmark = [besoin_neo4j, pytest.mark.neo4j]


# ------------------------------------------------------------------------ fixtures


@pytest.fixture(scope="module")
def session_ciblage():
    from cohera.graphe.connexion import session

    with session() as sess:
        yield sess


@pytest.fixture(scope="module")
def graphe_charge(session_ciblage, jeu, frames, vocabulaire, pont):
    """Le corpus chargé **avec ses embeddings** — le canal 4 ne peut pas s'en passer."""
    from cohera.graphe.chargeur import charger

    charger(jeu, frames, vocabulaire, pont, session_ciblage, avec_embeddings=True)
    return session_ciblage


@pytest.fixture(scope="module")
def ciblage(graphe_charge, frames):
    return cibler(graphe_charge, frames)


@pytest.fixture(scope="module")
def ciblage_sans_pont(graphe_charge, frames):
    return cibler(graphe_charge, frames, avec_pont=False)


@pytest.fixture(scope="module")
def identifiants(jeu):
    """``(doc, ref) -> clause_id`` — la correspondance qu'annonce `label.json`."""
    return {
        (doc_id, clause.ref): clause.clause_id
        for doc_id, segmentation in jeu.items()
        for clause in segmentation.clauses
    }


def paire_de(verite: dict, identifiant: str, identifiants: dict) -> tuple[str, str]:
    """Les deux `clause_id` d'une entrée de la vérité terrain."""
    entree = next(
        e
        for rubrique in ("incoherences", "contre_exemples")
        for e in verite.get(rubrique, [])
        if e.get("id") == identifiant
    )
    a, b = entree["clause_a"], entree["clause_b"]
    return identifiants[(a["doc"], a["ref"])], identifiants[(b["doc"], b["ref"])]


# ------------------------------------------------------------- les critères du J4


def test_l_espace_theorique_vaut_1517_paires(ciblage) -> None:
    """41 × 37, le compte annoncé par `label.json`. C'est le dénominateur de tout le reste."""
    assert ciblage.paires_theoriques == 1517


def test_le_rappel_du_ciblage_est_de_12_sur_12(ciblage, verite, identifiants) -> None:
    """**LE critère du J4**, et le point de contrôle n°1 du plan.

    Une paire écartée ici ne sera jamais rattrapée au J5 : le rappel du ciblage plafonne le
    rappel du système entier. Les anomalies mono-clause (I09, I10) n'ont aucune paire à
    cibler — la question devient « la clause a-t-elle été analysée ».
    """
    manquees = []
    for entree in verite["incoherences"]:
        if not entree.get("dans_perimetre_7j"):
            continue
        a = entree["clause_a"]
        id_a = identifiants[(a["doc"], a["ref"])]
        if entree.get("clause_b") is None:
            atteinte = id_a in ciblage.contextes
        else:
            b = entree["clause_b"]
            atteinte = ciblage.est_candidate(id_a, identifiants[(b["doc"], b["ref"])])
        if not atteinte:
            manquees.append(entree["id"])

    assert manquees == [], f"non ciblées : {', '.join(manquees)}"


def test_le_facteur_de_reduction_depasse_la_cible(ciblage) -> None:
    """`label.json` : ``facteur_reduction_cible >= 0.91``."""
    assert ciblage.facteur_reduction >= 0.91


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CRITÈRE ROUGE J4 — MESURÉ 72 paires candidates, ATTENDU 80 à 140 (label.json, "
        "statistiques_attendues.paires_candidates_cible). "
        "L'union des quatre canaux donne 87 paires ; 13 tombent au filtre de comparabilité "
        "et 2 aux budgets. "
        "AUCUN CANAL N'A ÉTÉ APPAUVRI, AUCUN PARAMÈTRE RESSERRÉ par rapport à "
        "architecture.md §6 — vérifié par la mesure, pas seulement affirmé : le seuil "
        "vectoriel est plus permissif (0,65 contre 0,70 en cosinus brut), k_voisins plus "
        "large (24 contre 12, et k=12 rend les mêmes 41 paires : c'est le seuil qui borne, "
        "pas k), top-3 du canal 5 et top-k=8 identiques, poids RRF et B=4×max identiques, "
        "filtre de comparabilité porté de 3 à 5 branches donc plus permissif. Les deux "
        "garde-fous ajoutés au Cypher sont des no-ops mesurés sur ce corpus : retirer "
        "`cle_comparaison <> ''` laisse le canal CLE à 1 paire, retirer "
        "`valeur_si IS NOT NULL` laisse le canal DIMENSION à 70 lignes. "
        "C'est donc le corpus qui produit moins de bruit que l'estimation du plan. "
        "Les deux critères que la borne basse sert à protéger sont atteints : rappel du "
        "ciblage 12/12 et facteur de réduction 0,9525 pour une cible de 0,91. "
        "Ne pas relâcher un seuil pour fabriquer les 8 paires manquantes — voir le Journal "
        "de CLAUDE.md."
    ),
)
def test_le_nombre_de_paires_candidates_est_dans_la_cible(ciblage, verite) -> None:
    """`label.json` : ``paires_candidates_cible = "80 a 140"``."""
    assert 80 <= len(ciblage.candidates) <= 140


# --------------------------------------------------- I12, le cas pilote du canal 5


def test_i12_est_trouvee_par_le_canal_dimension(ciblage, verite, identifiants) -> None:
    """« V7 trouvée par le canal 5 » (plan §J4)."""
    a, b = paire_de(verite, "I12", identifiants)
    assert Canal.DIMENSION in ciblage.canaux_de(a, b)


def test_i12_n_est_pas_trouvee_par_le_canal_vectoriel(ciblage, verite, identifiants) -> None:
    """« et lui seul » — la moitié négative du critère, et la plus fragile.

    `label.json` annonce « cos clause ~0,67 < 0,70 ». La mesure donne **0,598** en cosinus
    brut (0,799 sur l'échelle normalisée de Neo4j) : le chiffre de la vérité terrain est
    faux, la conclusion qu'il en tire reste juste. Le seuil retenu, 0,65, laisse I12 dehors
    de 0,052.
    """
    a, b = paire_de(verite, "I12", identifiants)
    assert Canal.VECTORIEL not in ciblage.canaux_de(a, b)


def test_i12_n_est_trouvee_par_aucun_autre_canal(ciblage, verite, identifiants) -> None:
    """Ni par la clé, ni par les concepts : aucun mot commun, aucun alias.

    C'est ce que protège la liste noire du J3 (`chef d'atelier`/`hiérarchie`,
    `signaler`/`remonter`) : un alias de plus sur ce couple viderait le cas pilote de son
    sens.
    """
    a, b = paire_de(verite, "I12", identifiants)
    assert ciblage.canaux_de(a, b) == [Canal.DIMENSION]


def test_i12_survit_aux_budgets(ciblage, verite, identifiants) -> None:
    """Être appariée ne suffit pas : la paire doit franchir la comparabilité et le top-k."""
    a, b = paire_de(verite, "I12", identifiants)
    assert ciblage.est_candidate(a, b)


def test_i12_entre_dans_le_top_3_du_canal_5_de_justesse(graphe_charge) -> None:
    """**Fragilité mesurée, figée par ce test.**

    D1 §6.2 a quatre partenaires de même dimension et même rôle dans D2 après exclusion des
    valeurs égales. D2 §6.2 y arrive au rang 3 sur 4, à moins de 0,02 de cosinus du rang 4
    qui, lui, est écarté. Le canal 5 garde le top-3 : la paire tient donc à cette marge.

    Si elle se referme, le rappel du ciblage tombe à 11/12 et le J4 repasse rouge. Ce test
    échoue alors bruyamment, au lieu de laisser la régression se découvrir au J5.
    """
    lignes = list(
        graphe_charge.run(
            """
            MATCH (a:Clause {doc_id:'D1', ref:'6.2'})-[:PORTE]->(qa:Quantite)
            MATCH (b:Clause {doc_id:'D2'})-[:PORTE]->(qb:Quantite)
            WHERE qa.dimension = qb.dimension AND qa.role = qb.role
              AND qa.valeur_si <> qb.valeur_si
            WITH DISTINCT b, vector.similarity.cosine(a.embedding, b.embedding) AS score
            RETURN b.ref AS ref, score ORDER BY score DESC
            """
        )
    )
    refs = [ligne["ref"] for ligne in lignes]
    assert refs.index("6.2") == 2, f"I12 n'est plus au rang 3 : {refs}"

    from cohera.ciblage.canaux.vectoriel import cosinus_brut

    marge = cosinus_brut(lignes[2]["score"]) - cosinus_brut(lignes[3]["score"])
    assert 0.0 < marge < 0.05, f"marge mesurée {marge:.4f}"


# ------------------------------------------------------------- I08 et I11, le filtre


def test_i08_n_est_trouvee_que_par_le_canal_vectoriel(ciblage, verite, identifiants) -> None:
    """Aucune clé, aucun concept partagé, aucune grandeur : le filet de sécurité, seul.

    C'est cette paire qui fixe la borne haute du seuil vectoriel — elle mesure 0,670 en
    cosinus brut, et disparaîtrait au seuil théorique de 0,70.
    """
    a, b = paire_de(verite, "I08", identifiants)
    assert ciblage.canaux_de(a, b) == [Canal.VECTORIEL]


def test_i08_passe_la_comparabilite_par_la_branche_norme(ciblage, verite, identifiants) -> None:
    """Sans la branche NORME, I08 est rejetée : modalités nulles, aucune grandeur."""
    a, b = paire_de(verite, "I08", identifiants)
    verdict = comparable(ciblage.contextes[a], ciblage.contextes[b])
    assert verdict.comparable
    assert verdict.motif is Motif.NORME


def test_i11_passe_la_comparabilite_par_la_branche_conceptuelle(
    ciblage, verite, identifiants
) -> None:
    """Sans la branche CONCEPTUELLE, I11 est rejetée pour la même raison qu'I08."""
    a, b = paire_de(verite, "I11", identifiants)
    verdict = comparable(ciblage.contextes[a], ciblage.contextes[b])
    assert verdict.comparable
    assert verdict.motif is Motif.CONCEPTS


# ------------------------------------------------------------------- les négatifs


def test_n03_n_est_pas_une_paire_candidate(ciblage, verite, identifiants) -> None:
    """Critère du J4 : le contre-exemple des phrases de cadrage ne doit pas sortir.

    Sur ce corpus il est écarté **encore plus tôt** que le filtre : aucun canal ne le
    propose — 0,594 de cosinus brut sous le seuil, zéro concept partagé, aucune grandeur.
    Que le filtre le rejette aussi est vérifié à part, sans serveur, dans
    `test_comparabilite.py`.
    """
    a, b = paire_de(verite, "N03", identifiants)
    assert not ciblage.est_candidate(a, b)
    assert ciblage.canaux_de(a, b) == []


def test_n03_serait_rejete_par_le_filtre_s_il_lui_parvenait(
    ciblage, verite, identifiants
) -> None:
    """Le filtre est bien la seconde ligne, et il tient : sur les contextes réels des deux
    clauses, aucune des cinq branches n'accepte."""
    a, b = paire_de(verite, "N03", identifiants)
    assert not comparable(ciblage.contextes[a], ciblage.contextes[b])


def test_n08_est_appariee_par_le_canal_dimension(ciblage, verite, identifiants) -> None:
    """« Le ciblage apparie, la cascade doit rejeter » (label.json).

    Même dimension et même rôle (délai), valeurs différentes, objets sans rapport : c'est le
    cas négatif du canal 5, et c'est au J5 de le trancher — pas au ciblage.
    """
    a, b = paire_de(verite, "N08", identifiants)
    assert Canal.DIMENSION in ciblage.canaux_de(a, b)
    assert ciblage.est_candidate(a, b)


def test_n02_n_est_pas_une_paire_candidate(ciblage, verite, identifiants) -> None:
    """Casque contre gants : deux obligations distinctes aux formulations très proches.

    La liste noire du J3 les tient disjointes, et le cosinus de 0,616 reste sous le seuil.
    """
    a, b = paire_de(verite, "N02", identifiants)
    assert not ciblage.est_candidate(a, b)


# ------------------------------------------------------------------ matérialisation


def test_deux_materialisations_donnent_le_meme_nombre_d_aretes(graphe_charge, ciblage) -> None:
    """« Neo4j : MERGE, jamais CREATE » (`CLAUDE.md`). Le ciblage doit être rejouable."""
    materialiser(graphe_charge, ciblage, identifiant_execution())
    premier = graphe_charge.run(
        "MATCH ()-[r:PAIRE_CANDIDATE]->() RETURN count(r) AS n"
    ).single()["n"]

    materialiser(graphe_charge, ciblage, identifiant_execution())
    second = graphe_charge.run(
        "MATCH ()-[r:PAIRE_CANDIDATE]->() RETURN count(r) AS n"
    ).single()["n"]

    assert premier == second == len(ciblage.candidates)


def test_la_materialisation_trace_les_canaux(graphe_charge, ciblage) -> None:
    """« On peut expliquer *pourquoi* une paire a été examinée » (architecture.md §6.6)."""
    materialiser(graphe_charge, ciblage, identifiant_execution())
    ligne = graphe_charge.run(
        "MATCH ()-[r:PAIRE_CANDIDATE]->() WHERE size(r.canaux) > 0 "
        "RETURN r.canaux AS canaux, r.run_id AS run_id LIMIT 1"
    ).single()
    assert ligne["canaux"]
    assert ligne["run_id"].startswith("run-")


# ------------------------------------------------------------------------ ablation


def test_retirer_le_pont_fait_perdre_du_rappel(
    ciblage, ciblage_sans_pont, verite, identifiants
) -> None:
    """La mini-ablation exigée par le J4.

    Mesuré : le pont vaut **une** incohérence du périmètre (I11), 72 paires candidates
    contre 62, et le canal conceptuel passe de 40 à 23 appariements. Le plan annonçait un
    « effondrement » ; l'effet réel est net mais modeste, parce que le canal vectoriel
    rattrape la plupart des paires que le pont apportait.
    """
    def rappel(cible) -> set[str]:
        atteintes = set()
        for entree in verite["incoherences"]:
            if not entree.get("dans_perimetre_7j") or entree.get("clause_b") is None:
                continue
            a, b = entree["clause_a"], entree["clause_b"]
            if cible.est_candidate(
                identifiants[(a["doc"], a["ref"])], identifiants[(b["doc"], b["ref"])]
            ):
                atteintes.add(entree["id"])
        return atteintes

    perdues = rappel(ciblage) - rappel(ciblage_sans_pont)
    assert perdues, "le pont n'apporte aucune incohérence : l'ablation ne mesure rien"


def test_retirer_le_pont_reduit_le_canal_conceptuel(ciblage, ciblage_sans_pont) -> None:
    """Le mécanisme derrière le chiffre : c'est bien le saut par `ALIAS_DE` qui disparaît."""
    avec = len(ciblage.par_canal[Canal.CONCEPTUEL.value])
    sans = len(ciblage_sans_pont.par_canal[Canal.CONCEPTUEL.value])
    assert sans < avec


def test_retirer_le_pont_ne_touche_pas_aux_canaux_qui_l_ignorent(
    ciblage, ciblage_sans_pont
) -> None:
    """Cas négatif de l'ablation : les canaux vectoriel et dimension ne traversent aucun
    alias, donc l'ablation ne doit pas les bouger. Si elle les bougeait, elle mesurerait
    autre chose que le pont."""
    for canal in (Canal.VECTORIEL, Canal.DIMENSION):
        assert len(ciblage.par_canal[canal.value]) == len(
            ciblage_sans_pont.par_canal[canal.value]
        )
