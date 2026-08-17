"""detection/cascade.py — le J5 de bout en bout, contre un vrai graphe.

**Ce module porte les critères chiffrés de la journée** : précision = 1,00 et zéro faux
positif sur les 7 contre-exemples du périmètre. Ils sont des propriétés du pipeline entier —
ciblage compris — et les simuler ne prouverait rien. La logique qui *peut* être testée hors
ligne l'est ailleurs : `test_a1.py`, `test_a2.py`, `test_a5.py`, `test_portees.py`,
`test_conditions_algebre.py`, `test_detection_modeles.py`.

⚠️ Un test sauté n'est pas un test vert. Le bilan de fin de journée compte les skips.
"""

from __future__ import annotations

import pytest

from cohera.ciblage import cibler
from cohera.detection.cascade import detecter
from cohera.detection.modeles import Motif, TypeVerdict
from tests.conftest import entree_de, paire_de


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
def session_cascade():
    from cohera.graphe.connexion import session

    with session() as sess:
        yield sess


@pytest.fixture(scope="module")
def graphe_charge(session_cascade, jeu, frames, vocabulaire, pont):
    from cohera.graphe.chargeur import charger

    charger(jeu, frames, vocabulaire, pont, session_cascade, avec_embeddings=True)
    return session_cascade


@pytest.fixture(scope="module")
def detection(graphe_charge, frames, textes, vocabulaire, pont, algebre):
    ciblage = cibler(graphe_charge, frames)
    return detecter(ciblage, frames, textes, vocabulaire, pont, algebre)


def _refs(verite: dict, identifiants: dict) -> dict[frozenset, str]:
    """``{clause_a, clause_b} -> identifiant de la vérité terrain``."""
    table: dict[frozenset, str] = {}
    for rubrique in ("incoherences", "contre_exemples"):
        for entree in verite[rubrique]:
            a = entree["clause_a"]
            id_a = identifiants.get((a["doc"], a["ref"]))
            b = entree.get("clause_b")
            id_b = identifiants.get((b["doc"], b["ref"])) if b else None
            table[frozenset((id_a, id_b))] = entree["id"]
            # Une anomalie mono-clause peut être constatée sur l'une ou l'autre clause.
            if id_b is not None:
                table.setdefault(frozenset((id_a, None)), entree["id"])
                table.setdefault(frozenset((id_b, None)), entree["id"])
    return table


# ------------------------------------------ LE CRITÈRE DU J5 : zéro faux positif


def test_zero_faux_positif_sur_les_sept_contre_exemples(
    detection, verite, identifiants
) -> None:
    """**Le critère dur de la journée.** Les 7 contre-exemples du périmètre
    (`dans_perimetre_7j: true`) : N01, N02, N03, N04, N06, N08, N09.

    Chacun a par ailleurs son test unitaire nommé, qui dit *pourquoi* il ne sort pas — la
    disjonction spatiale pour N04, l'égalité après normalisation SI pour N06, l'écart de
    force nul pour N02 et N09, le recouvrement d'objets pour N08, la spécialisation pour
    N01. Ici on vérifie seulement, de bout en bout, qu'aucun ne devient une constatation.
    """
    du_perimetre = [
        e for e in verite["contre_exemples"] if e.get("dans_perimetre_7j")
    ]
    assert {e["id"] for e in du_perimetre} == {
        "N01", "N02", "N03", "N04", "N06", "N08", "N09"
    }, "la liste des contre-exemples du périmètre a changé dans label.json"

    fautes = []
    for entree in du_perimetre:
        a, b = paire_de(verite, entree["id"], identifiants)
        faute = detection.constatation_sur(a, b)
        if faute is not None:
            fautes.append(f"{entree['id']} ({faute.detecteur} {faute.motif.value})")

    assert fautes == [], f"faux positifs : {', '.join(fautes)}"


def test_la_precision_vaut_un(detection, verite, identifiants) -> None:
    """**Le second critère dur.** Toute constatation rendue correspond à une entrée de
    `label.json` — mesuré sur les 11 constatations, pas sur un échantillon.

    Y compris I17 (D1 §10.2, dérogation orpheline vers PR-QSE-02), hors périmètre 7 jours et
    attendue du détecteur A8 : A5 l'attrape par sa règle « renvoi non résolu », ce qui est un
    vrai positif trouvé plus tôt, pas un faux positif."""
    connues = _refs(verite, identifiants)
    inconnues = [
        f"{v.detecteur} {v.clause_a}<->{v.clause_b} : {v.explication}"
        for v in detection.constatations
        if frozenset((v.clause_a, v.clause_b)) not in connues
    ]
    assert inconnues == [], "constatations absentes de label.json :\n" + "\n".join(inconnues)
    assert len(detection.constatations) == 11


# --------------------------------------------------- ce qui sort, et ce qui escalade


def test_l_etage_a_conclut_sur_huit_des_neuf_incoherences_qu_il_devait_traiter(
    detection, verite, identifiants
) -> None:
    """**Le bilan de rappel du J5, et le critère rouge qu'il contient.**

    Neuf des douze incohérences du périmètre sont annoncées à `etage_attendu: "A"` par
    `label.json` : I01, I02, I04, I08, I09, I10, I12, I14, I15. La cascade en conclut
    **huit**. La neuvième est I12, qui escalade faute d'objet canonique partagé — le prix
    du garde-fou de précision, mesuré, documenté dans `config/detection.yaml` et consigné
    en rouge au Journal de `CLAUDE.md`.

    Les trois autres (I03, I05, I11) sont annoncées à l'étage C et escaladent bien."""
    attendues_a, conclues, manquees = [], [], []
    for entree in verite["incoherences"]:
        if not entree.get("dans_perimetre_7j") or entree.get("etage_attendu") != "A":
            continue
        attendues_a.append(entree["id"])
        a = entree["clause_a"]
        id_a = identifiants[(a["doc"], a["ref"])]
        b = entree.get("clause_b")
        id_b = identifiants[(b["doc"], b["ref"])] if b else None
        if detection.constatation_sur(id_a, id_b) is not None:
            conclues.append(entree["id"])
        else:
            manquees.append(entree["id"])

    assert sorted(attendues_a) == ["I01", "I02", "I04", "I08", "I09", "I10", "I12", "I14", "I15"]
    assert manquees == ["I12"], f"manquées à l'étage A : {manquees}"
    assert len(conclues) == 8


@pytest.mark.parametrize("cas", ["I03", "I05", "I11"])
def test_les_incoherences_de_l_etage_c_escaladent_bien(
    detection, verite, identifiants, cas: str
) -> None:
    """Le pendant du test précédent : ce que `label.json` place à l'étage C ne doit ni
    sortir en constatation — ce serait de la chance — ni disparaître sans trace.

    I11 est le seul cas qui ne produit aucun verdict du tout : aucune grandeur, aucun
    conflit déontique, aucune norme. C'est précisément ce que dit `label.json` — « seul le
    sens permet de trancher, c'est le cas qui justifie l'étage C »."""
    a, b = paire_de(verite, cas, identifiants)
    assert entree_de(verite, cas)["etage_attendu"] == "C"
    assert detection.constatation_sur(a, b) is None

    fermes = [v for v in detection.verdicts_de(a, b) if v.ferme]
    assert fermes == [], f"{cas} conclue fermement alors qu'elle relève de l'étage C"


def test_i12_escalade_avec_son_motif_et_non_en_silence(
    detection, verite, identifiants
) -> None:
    """⚠️ **LE CRITÈRE ROUGE DU J5.** `label.json` attend I12 à l'étage A, détecteur A2.

    Elle escalade, et le test l'exige explicite : le verdict existe, il porte son type et
    son motif, il part au J6. Un rejet silencieux serait une perte ; une escalade motivée
    n'en est pas une. Voir `config/detection.yaml` §preuve pour la mesure, et le Journal de
    `CLAUDE.md` pour la consignation."""
    a, b = paire_de(verite, "I12", identifiants)
    assert entree_de(verite, "I12")["etage_attendu"] == "A"

    escalades = [v for v in detection.escalades if frozenset((v.clause_a, v.clause_b)) == frozenset((a, b))]
    assert [v.motif for v in escalades] == [Motif.OBJETS_SANS_RECOUVREMENT]
    assert escalades[0].type is TypeVerdict.CONTRADICTION


def test_n01_est_listee_en_specialisation_et_non_perdue(
    detection, verite, identifiants
) -> None:
    """Une spécialisation n'est ni une incohérence ni un non-événement : `label.json`
    l'attend en `SPECIALISATION`, et le rapport devra la montrer comme telle."""
    a, b = paire_de(verite, "N01", identifiants)
    assert entree_de(verite, "N01")["attendu"] == "SPECIALISATION"

    specialisations = [
        v for v in detection.specialisations
        if frozenset((v.clause_a, v.clause_b)) == frozenset((a, b))
    ]
    assert len(specialisations) == 1
    assert specialisations[0].ferme


def test_la_cascade_n_examine_que_les_paires_candidates(detection, graphe_charge, frames) -> None:
    """Invariant #2 : rien de cher avant le ciblage. Les 78 clauses passent la revue
    mono-clause d'A5 — qui ne compare rien — mais seules les 72 paires candidates du J4 sont
    jugées, sur 1517 théoriques."""
    assert detection.paires_examinees == 72
    assert detection.clauses_examinees == 78


def test_aucun_rejet_n_est_silencieux(detection) -> None:
    """`.claude/rules/detection.md` : « toute paire écartée par un filtre est journalisée
    avec son motif ». Chaque verdict muet en porte un, et chaque escalade aussi."""
    for verdict in detection.muets + detection.escalades:
        assert verdict.motif is not None
        assert verdict.explication or verdict.type is not TypeVerdict.AUCUNE


def test_toute_constatation_porte_une_preuve_litterale(detection, textes) -> None:
    """Invariant #3, vérifié sur le résultat réel et pas seulement sur des cas fabriqués."""
    from cohera.detection.modeles import verifier_preuves

    for verdict in detection.constatations:
        assert verdict.preuve_a is not None
        assert verifier_preuves(verdict, textes), verdict.explication


# ------------------------------------------------------- l'algèbre dans le graphe


def test_les_aretes_d_algebre_sont_dans_le_graphe(graphe_charge) -> None:
    """Le chargement écrit bien RECOUVRE / INCLUS_DANS / DISJOINT_DE, et la disjonction de
    N04 y figure nommément."""
    comptes = {
        ligne["type"]: ligne["n"]
        for ligne in graphe_charge.run(
            "MATCH (:Condition)-[r]->(:Condition) RETURN type(r) AS type, count(*) AS n"
        )
    }
    assert comptes == {"INCLUS_DANS": 5, "RECOUVRE": 1, "DISJOINT_DE": 3}

    disjonction = graphe_charge.run(
        "MATCH (a:Condition)-[r:DISJOINT_DE]-(b:Condition) "
        "WHERE a.concept_cible = 'zone A' AND b.concept_cible = 'zone de stockage' "
        "RETURN r.regle AS regle"
    ).single()
    assert disjonction["regle"] == "SPATIAL_FRERES"


# ------------------------------------------------- J6 : le périmètre de l'étage C


@pytest.fixture(scope="module")
def perimetre_juge(detection, frames, algebre):
    """Les paires que le J6 soumettra au LLM, sur le vrai corpus."""
    from cohera.detection.juge_llm import paires_a_juger

    return paires_a_juger(detection, frames, algebre)


def test_le_perimetre_du_juge_tient_dans_le_budget(perimetre_juge) -> None:
    """**Le périmètre de l'étage C**, mesuré sur le pipeline entier : 57 paires, plus 2
    appels d'arbitrage de la zone grise, soit 59 appels nominaux.

    Le plafond a été porté de 60 à 200 après mesure. À 60, il mordait en exécution — 60
    appels pour 34 paires seulement, parce que le profil local ne contraint pas son
    décodage et que chaque réparation coûte un appel — et 13 paires, dont I03, n'étaient
    jamais soumises. Le plafond mesurait alors la faiblesse du modèle, pas celle du corpus.
    La marge couvre désormais deux appels par paire.

    ⚠️ **Écart au plan**, consigné au Journal : `docs/plan-1-semaine.md` §J6 chiffre
    « ≤ 15 appels LLM » et son tableau de bord « ~14 ». Le périmètre élargi — décision
    explicite, pour qu'aucune paire ne soit écartée par construction — mène à 59 nominal."""
    from cohera.detection import config_detection

    assert len(perimetre_juge) == 57
    # De la marge pour DEUX appels par paire : une réparation ne doit pas coûter une cible.
    assert 2 * len(perimetre_juge) + 2 <= config_detection.max_appels_juge()


def test_les_quatre_cibles_du_j6_atteignent_le_juge(
    perimetre_juge, verite, identifiants
) -> None:
    """I03, I05 et I11 sont les trois `etage_attendu: "C"` de `label.json` ; I12 est le
    critère rouge du J5, qui escalade avec son motif.

    Le sens de la décision du J6 est là : leur donner une vraie chance d'être arbitrées
    plutôt que d'être écartées par construction. Qu'elles se débloquent ou non est une
    autre question — celle du modèle, pas de l'architecture."""
    soumises = {frozenset((p.clause_a, p.clause_b)) for p in perimetre_juge}
    for cas in ("I03", "I05", "I11", "I12"):
        a, b = paire_de(verite, cas, identifiants)
        assert frozenset((a, b)) in soumises, f"{cas} n'atteint pas l'étage C"


def test_i11_arrive_au_juge_alors_qu_elle_n_est_dans_aucune_escalade(
    detection, perimetre_juge, verite, identifiants
) -> None:
    """⭐ **Le piège que la mesure du J6 a révélé.**

    `label.json` désigne I11 comme « le cas qui justifie l'étage C ». Or elle ne produit
    aucun verdict escaladé : sans modalité ni grandeur, ses trois verdicts sont `AUCUNE` et
    elle est rangée dans `muets`. Un juge branché sur `Detection.escalades` — la lecture
    littérale de « toutes les escalades » — la manquerait par construction.

    Le tri se fait donc sur le MOTIF : « je n'ai pas de donnée » n'est pas « j'ai établi la
    compatibilité »."""
    a, b = paire_de(verite, "I11", identifiants)
    cible = frozenset((a, b))

    assert not any(frozenset((v.clause_a, v.clause_b)) == cible for v in detection.escalades)
    assert any(frozenset((v.clause_a, v.clause_b)) == cible for v in detection.muets)
    assert cible in {frozenset((p.clause_a, p.clause_b)) for p in perimetre_juge}


@pytest.mark.parametrize("cas, motif", [("N04", "portées disjointes"), ("N06", "valeurs égales"),
                                        ("N09", "écart de force nul")])
def test_les_contre_exemples_resolus_ne_repartent_pas_au_juge(
    perimetre_juge, verite, identifiants, cas: str, motif: str
) -> None:
    """Le pendant négatif du périmètre. Le symbolique a POSITIVEMENT établi la compatibilité
    de ces trois paires : les repayer en appels LLM serait à la fois du gaspillage et un
    risque de faux positif — c'est le LLM qu'on donnerait la chance de se tromper.

    N04 est le cas instructif : aucun détecteur ne pose `PORTEES_DISJOINTES` sur elle, car
    A2 s'arrête sur `PAS_DE_GRANDEUR_COMPARABLE` et A1 sur `MODALITE_ABSENTE`. C'est le test
    de recouvrement appliqué **à la paire** qui l'écarte, comme le veut architecture.md
    §7.2. Sans lui — mesuré — N04 partait au juge."""
    a, b = paire_de(verite, cas, identifiants)
    soumises = {frozenset((p.clause_a, p.clause_b)) for p in perimetre_juge}
    assert frozenset((a, b)) not in soumises, f"{cas} soumise au juge malgré {motif}"


def test_n08_atteint_le_juge_et_c_est_le_risque_de_la_journee(
    perimetre_juge, verite, identifiants
) -> None:
    """⚠️ **Le seul contre-exemple du périmètre qui arrive devant le LLM.**

    N08 (D1 §5.6 « sous 5 jours ouvrés » contre D2 §4.5 « sous 10 jours ouvrés ») a le
    profil exact d'une divergence : même dimension, même rôle, valeurs différentes. Ce qui
    la sauve est que les objets n'ont aucun rapport — commande d'EPI contre compte rendu de
    comité — et c'est précisément ce que le garde-fou des objets a détecté à l'étage A.

    Elle atteint donc le juge avec `OBJETS_SANS_RECOUVREMENT`, et le prompt doit lui donner
    de quoi conclure : les objets canoniques des deux côtés et leur non-recouvrement y sont
    injectés. Ce test fige le fait qu'elle est soumise ; c'est `cohera evaluer` qui vérifie
    qu'elle n'en ressort pas en constatation."""
    a, b = paire_de(verite, "N08", identifiants)
    assert entree_de(verite, "N08")["attendu"] == "AUCUNE_CONSTATATION"

    paire = next(
        (p for p in perimetre_juge if frozenset((p.clause_a, p.clause_b)) == frozenset((a, b))),
        None,
    )
    assert paire is not None
    assert paire.motif_amont == "OBJETS_SANS_RECOUVREMENT"
