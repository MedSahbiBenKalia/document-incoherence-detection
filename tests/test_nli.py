"""detection/nli.py — l'étage B, et la seule chose qu'il a le droit de faire.

**L'étage B ne conclut jamais seul.** Il n'a pas de citation à produire, et l'invariant #3
de `CLAUDE.md` interdit un verdict sans preuve littérale. Il ne peut donc que **fermer**
une paire par le bas — quand les deux sens de l'inférence s'accordent à ne voir aucune
contradiction — et **journaliser** le reste. Ces tests figent cette asymétrie : c'est elle
qui garantit qu'aucun faux positif ne peut naître de cet étage.

Deux tests chargent le modèle réel (~1,4 s, il est en cache) parce que la question qu'ils
posent est « que dit `distilcamembert` de cette paire ? », et qu'un inféreur factice y
répondrait à sa place. Tout le reste — le maximum bidirectionnel, la forme de l'entrée, le
routage vers le juge — se teste avec un inféreur injecté, sur le modèle de
`tests/test_embeddings.py`.
"""

from __future__ import annotations

import pytest

from cohera.detection import config_detection, nli
from cohera.detection.cascade import Detection, etage_b
from cohera.detection.juge_llm import paires_a_juger
from cohera.detection.modeles import Motif, TypeVerdict, Verdict
from cohera.detection.nli import ZoneNLI
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.conditions import construire_algebre
from cohera.ingestion.modeles import Clause


# ------------------------------------------------------------------------ outillage


def clause(clause_id: str, doc: str, ref: str, texte: str, *, autonome: str | None = None,
           section: str = "5. CONTRÔLE PÉRIODIQUE DES EPI") -> Clause:
    return Clause(
        clause_id=clause_id, doc_id=doc, ref=ref, ordre=1, section_path=[section],
        texte_source=texte, texte_autonome=autonome or texte, offset=(0, len(texte)),
    )


class InfereurFixe:
    """Inféreur factice : rend une probabilité par couple, et retient ce qu'on lui a passé.

    La table est indexée par (prémisse, hypothèse) *entières*, ce qui oblige les tests à
    dire exactement quelle chaîne ils attendent en entrée du modèle — c'est ce qui rend
    vérifiable le fait que l'étage B envoie `texte_autonome` et non `texte_source`.
    """

    def __init__(self, table: dict[tuple[str, str], float], defaut: float = 0.5) -> None:
        self.table, self.defaut = table, defaut
        self.vus: list[tuple[str, str]] = []
        self.appels = 0

    def __call__(self, premisses: list[str], hypotheses: list[str]) -> list[float]:
        self.appels += 1
        self.vus += list(zip(premisses, hypotheses))
        return [self.table.get(couple, self.defaut) for couple in zip(premisses, hypotheses)]


def detection_d_une_paire(*, escaladee: bool) -> Detection:
    """Une `Detection` portant la paire A/B, escaladée par A2 ou muette faute de données."""
    detection = Detection(paires_examinees=1)
    if escaladee:
        detection.escalades.append(
            Verdict(detecteur="A2", type=TypeVerdict.CONTRADICTION,
                    motif=Motif.OBJETS_SANS_RECOUVREMENT, clause_a="A", clause_b="B",
                    explication="même rôle, valeurs différentes, objets sans recouvrement")
        )
    else:
        detection.muets.append(
            Verdict(detecteur="A2", type=TypeVerdict.AUCUNE,
                    motif=Motif.PAS_DE_GRANDEUR_COMPARABLE, clause_a="A", clause_b="B")
        )
    return detection


@pytest.fixture
def monde():
    """Deux clauses et de quoi appeler `paires_a_juger` — aucun graphe, aucun réseau."""
    clauses = {
        "A": clause("A", "D1", "5.4", "Le port du casque est obligatoire en zone A."),
        "B": clause("B", "D2", "5.6", "Le port du casque est interdit en zone A."),
    }
    frames = {"A": ClauseFrame(clause_id="A"), "B": ClauseFrame(clause_id="B")}
    return {"clauses": clauses, "frames": frames, "algebre": construire_algebre(frames)}


# ====================== LE MODÈLE RÉEL — ce que distilcamembert dit vraiment ======================


def test_positif_une_contradiction_nette_est_vue_comme_telle():
    """Test positif du plan §J8 : « contradiction nette détectée ».

    Obligation contre interdiction sur le même objet et la même zone. C'est le cas le plus
    facile qui soit pour un NLI, et il doit atteindre la bande haute — sans quoi les seuils
    calibrés sur le corpus ne voudraient rien dire.
    """
    a = clause("A", "D1", "5.4", "Le port du casque est obligatoire en zone A.")
    b = clause("B", "D2", "5.6", "Le port du casque est interdit en zone A.")

    score = nli.scorer([("A", "B")], {"A": a, "B": b})[0]

    assert score.zone is ZoneNLI.CONTRADICTION_FERME
    # Et elle est nette dans les DEUX sens : c'est ce qui distingue une vraie opposition
    # d'une instabilité de sens (voir le test sur N02 plus bas).
    assert min(score.p_contradiction_ab, score.p_contradiction_ba) >= 0.80


def test_negatif_une_paire_neutre_est_fermement_rejetee():
    """Test négatif du plan §J8 : « paire neutre correctement rejetée ».

    Les textes sont ceux du corpus : D1 §7.1 et D2 §5.3 parlent toutes deux du harnais
    antichute, l'une de quand il est requis, l'autre de sa vérification. Aucune opposition.
    C'est la paire la plus basse des 57 mesurées à l'étape 0 (0,0172).
    """
    a = clause("A", "D1", "7.1",
               "Le harnais antichute est requis pour les interventions réalisées à plus "
               "de 3 mètres.", section="7. TRAVAUX EN HAUTEUR")
    b = clause("B", "D2", "5.3",
               "Les harnais antichute font l'objet d'une vérification annuelle.",
               section="5. VÉRIFICATION DES ÉQUIPEMENTS DE PROTECTION")

    score = nli.scorer([("A", "B")], {"A": a, "B": b})[0]

    assert score.zone is ZoneNLI.REJET


def test_le_nli_ne_rejette_PAS_n02_contrairement_a_ce_qu_annonce_label_json():
    """⚠️ LIMITE MESURÉE, figée ici plutôt que laissée dans un commentaire.

    `corpus/fixtures/label.json` annonce pour N02 : `"teste": "Liste noire des alias +
    rejet NLI"`. La mesure dit l'inverse — sur les deux vraies clauses du corpus, le modèle
    voit une **contradiction** entre deux obligations portant sur deux équipements
    différents, et fortement dans un sens.

    N02 n'atteint jamais l'étage B (la liste noire des alias l'écarte au ciblage), donc
    rien n'est cassé ; mais c'est bien la liste noire qui protège N02, **pas** le NLI. La
    vérité terrain n'est pas corrigée — elle est signalée, comme l'exige `CLAUDE.md`.

    C'est aussi la démonstration directe de pourquoi la bande haute n'est pas fermante.
    """
    a = clause("A", "D1", "5.4", "Le port du casque est obligatoire en zone A.")
    b = clause("B", "D2", "5.6",
               "Le port de gants de manutention est obligatoire lors des opérations "
               "de chargement.", section="5. VÉRIFICATION DES ÉQUIPEMENTS DE PROTECTION")

    score = nli.scorer([("A", "B")], {"A": a, "B": b})[0]

    assert score.zone is not ZoneNLI.REJET, "le NLI ne rejette pas N02 — label.json l'espère"
    assert score.p_contradiction >= 0.70


# ============================ L'INFÉRENCE — bidirectionnelle, par lots ============================


def test_le_maximum_des_deux_sens_est_retenu(monde):
    """architecture.md §7.3 : « on calcule les deux sens, on retient le maximum ».

    L'inféreur rend deux valeurs très différentes selon l'ordre ; c'est la plus forte qui
    doit ressortir, et les deux doivent rester lisibles dans le score.
    """
    a, b = nli.entree_nli(monde["clauses"]["A"]), nli.entree_nli(monde["clauses"]["B"])
    infereur = InfereurFixe({(a, b): 0.11, (b, a): 0.97})

    score = nli.scorer([("A", "B")], monde["clauses"], inferer=infereur)[0]

    assert score.p_contradiction_ab == pytest.approx(0.11)
    assert score.p_contradiction_ba == pytest.approx(0.97)
    assert score.p_contradiction == pytest.approx(0.97)
    assert (a, b) in infereur.vus and (b, a) in infereur.vus


def test_l_entree_porte_le_chemin_de_section_et_le_texte_autonome():
    """§7.3 : « `texte_autonome` préfixé du chemin de section ».

    `texte_autonome` et non `texte_source` : D1 §1.2 commence par « Elle s'applique… » dans
    le fichier, et l'autonomisation en fait « La présente procédure s'applique… ». Envoyer
    la version brute priverait le modèle du sujet de la phrase — exactement le contexte que
    la décontextualisation lui a retiré.
    """
    c = clause("A", "D1", "1.2",
               "Elle s'applique à l'ensemble du personnel du site.",
               autonome="La présente procédure s'applique à l'ensemble du personnel du site.",
               section="1. OBJET ET DOMAINE D'APPLICATION")

    entree = nli.entree_nli(c)

    assert entree.startswith("[D1 §1.2 1. OBJET ET DOMAINE D'APPLICATION]")
    assert "La présente procédure s'applique" in entree
    assert "Elle s'applique" not in entree


def test_les_deux_sens_de_toutes_les_paires_partent_en_un_seul_appel(monde):
    """Le coût de §7.3 (« lots de 32 ») suppose un appel groupé, pas 2N appels."""
    clauses = dict(monde["clauses"])
    clauses["C"] = clause("C", "D1", "6.1", "L'installation est arrêtée immédiatement.")
    infereur = InfereurFixe({})

    nli.scorer([("A", "B"), ("A", "C")], clauses, inferer=infereur)

    assert len(infereur.vus) == 4  # 2 paires x 2 sens
    assert infereur.appels == 1


# ================================ LES SEUILS — lus, jamais écrits ================================


def test_les_seuils_viennent_du_yaml_et_sont_ordonnes():
    """Aucune valeur métier en dur (`CLAUDE.md`), et un seuil bas sous un seuil haut."""
    rejet, contradiction = config_detection.seuils_nli()

    assert 0.0 < rejet < contradiction < 1.0
    assert config_detection.taille_lot_nli() > 0


def test_les_trois_zones_sont_bornees_par_les_seuils():
    rejet, contradiction = config_detection.seuils_nli()

    assert nli.zone_de(rejet) is ZoneNLI.REJET
    assert nli.zone_de(rejet + 1e-9) is ZoneNLI.ZONE_GRISE
    assert nli.zone_de(contradiction) is ZoneNLI.CONTRADICTION_FERME
    assert nli.zone_de(contradiction - 1e-9) is ZoneNLI.ZONE_GRISE


# ======================= LE ROUTAGE — ce que l'étage B retire, et ce qu'il laisse =======================


def test_un_rejet_ferme_la_paire_et_la_retire_du_juge(monde):
    """Le gain de l'étage B, et le seul qu'il produise : une paire de moins pour le LLM.

    Le motif `REJET_NLI` figure dans `juge.motifs_fermants` : c'est le mécanisme existant
    du J6 qui fait l'exclusion, aucun code neuf dans `paires_a_juger`.
    """
    detection = detection_d_une_paire(escaladee=True)
    avant = paires_a_juger(detection, monde["frames"], monde["algebre"])
    assert len(avant) == 1

    etage_b(detection, [("A", "B")], monde["clauses"], inferer=InfereurFixe({}, defaut=0.01))

    apres = paires_a_juger(detection, monde["frames"], monde["algebre"])
    assert apres == []
    ferme = [v for v in detection.muets if v.motif is Motif.REJET_NLI]
    assert len(ferme) == 1
    assert ferme[0].etage == "B" and ferme[0].type is TypeVerdict.COHERENT


def test_une_contradiction_ferme_n_affirme_rien_et_laisse_la_paire_au_juge(monde):
    """⭐ L'étage B ne conclut jamais seul — décision du J8, mesurée avant d'être prise.

    La bande haute des 57 paires contenait I03 (vraie), I06 (vraie), **un des trois faux
    positifs de l'étage C et le contre-exemple N05**. Affirmer à partir de là ajouterait au
    moins deux constatations fausses. L'étage B journalise donc son score et se tait.
    """
    detection = detection_d_une_paire(escaladee=True)

    resultat = etage_b(detection, [("A", "B")], monde["clauses"],
                       inferer=InfereurFixe({}, defaut=0.99))

    assert resultat.scores[0].zone is ZoneNLI.CONTRADICTION_FERME
    assert detection.constatations == []
    assert not any(v.etage == "B" for rubrique in detection.rubriques for v in rubrique)
    assert len(paires_a_juger(detection, monde["frames"], monde["algebre"])) == 1


def test_l_etage_b_ne_change_pas_le_signal_amont_du_prompt(monde):
    """⭐ LE TEST QUI PROTÈGE LE CACHE DU J6.

    Le prompt de l'étage C porte un `SIGNAL AMONT` tiré du premier verdict escaladé de la
    paire. Si l'étage B y écrivait le sien, les 21 paires « sans donnée » — dont I11, le
    cas qui justifie l'étage C — changeraient de clé de cache, et les mesures des J6 et J7
    deviendraient incomparables sans tout repayer.

    Vérifié sur les deux formes de paire : celle qui portait déjà une escalade, et celle
    qui n'en portait aucune.
    """
    for escaladee in (True, False):
        detection = detection_d_une_paire(escaladee=escaladee)
        avant = paires_a_juger(detection, monde["frames"], monde["algebre"])[0]

        etage_b(detection, [("A", "B")], monde["clauses"],
                inferer=InfereurFixe({}, defaut=0.99))

        apres = paires_a_juger(detection, monde["frames"], monde["algebre"])[0]
        assert apres.motif_amont == avant.motif_amont
        assert (apres.amont is None) == (avant.amont is None)


def test_la_zone_grise_est_journalisee_sans_verdict(monde):
    """Un rejet est définitif, une zone grise reste visible : les deux sont comptés."""
    detection = detection_d_une_paire(escaladee=True)

    resultat = etage_b(detection, [("A", "B")], monde["clauses"],
                       inferer=InfereurFixe({}, defaut=0.5))

    assert resultat.scores[0].zone is ZoneNLI.ZONE_GRISE
    assert resultat.paires_fermees == 0
    assert resultat.repartition[ZoneNLI.ZONE_GRISE] == 1
    assert len(paires_a_juger(detection, monde["frames"], monde["algebre"])) == 1


def test_la_stabilite_entre_les_deux_sens_est_exposee_et_comptee(monde):
    """⚠️ LIMITE MESURÉE AU J8, figée ici parce qu'un commentaire ne tient pas une limite.

    §7.3 retient le **maximum** des deux sens. Mesuré sur le corpus : 19 paires sur 57
    changent de zone selon l'ordre, et dans la bande haute les paires *stables* étaient les
    vraies incohérences quand les *instables* étaient le faux positif et le contre-exemple
    N05. Le maximum promeut donc une instabilité de modèle en confiance.

    Ce n'est **pas** devenu une règle — 5 paires ne fondent pas un séparateur, et un
    séparateur choisi parce qu'il trie la vérité terrain est ce que le projet s'interdit.
    La propriété est exposée et comptée, pour que le stage n° 2 puisse la reprendre.
    """
    a, b = nli.entree_nli(monde["clauses"]["A"]), nli.entree_nli(monde["clauses"]["B"])
    detection = detection_d_une_paire(escaladee=True)

    instable = etage_b(detection, [("A", "B")], monde["clauses"],
                       inferer=InfereurFixe({(a, b): 0.05, (b, a): 0.95}))
    assert instable.scores[0].stable is False
    assert instable.paires_instables == 1

    stable = etage_b(detection_d_une_paire(escaladee=True), [("A", "B")], monde["clauses"],
                     inferer=InfereurFixe({(a, b): 0.95, (b, a): 0.91}))
    assert stable.scores[0].stable is True
    assert stable.paires_instables == 0


def test_l_indice_de_l_etiquette_contradiction_est_lu_et_non_suppose():
    """Un modèle sans classe « contradiction » doit ÉCHOUER, pas rendre du bruit.

    `distilcamembert-base-nli` range la contradiction en 0 ; les deux alternatives de §7.3
    la rangent en 2. Un indice codé en dur inverserait les probabilités **sans lever la
    moindre erreur** — la panne silencieuse la plus coûteuse qui soit ici.
    """
    class Config:
        id2label = {0: "LABEL_0", 1: "LABEL_1"}

    class FauxModele:
        config = Config()

    with pytest.raises(ValueError, match="contradiction"):
        nli._indice_contradiction(FauxModele())

    class ConfigXnli:
        id2label = {0: "entailment", 1: "neutral", 2: "contradiction"}

    class ModeleXnli:
        config = ConfigXnli()

    assert nli._indice_contradiction(ModeleXnli()) == 2


def test_l_etage_b_sur_zero_paire_ne_charge_aucun_modele(monde):
    """`--sans-etage-c` laisse l'étage B sans rien à faire : il ne doit rien coûter."""
    detection = detection_d_une_paire(escaladee=True)

    resultat = etage_b(detection, [], monde["clauses"])

    assert resultat.scores == [] and resultat.paires_soumises == 0
