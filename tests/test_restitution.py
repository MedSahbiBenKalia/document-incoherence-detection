"""Restitution L6 — preuves littérales bloquantes, dérogations, jeu dérivé.

Trois briques du J7 réunies parce qu'elles servent le même livrable — le rapport publié —
et qu'elles partagent le même principe : **ce que le rapport affirme doit être vérifiable
dans le texte d'origine**.
"""

from __future__ import annotations

from datetime import date

import pytest

from cohera.consolidation import derogations as module_derogations
from cohera.restitution import preuves as module_preuves
from cohera.restitution.rapport_json import (
    Constatation,
    CoteClause,
    Derogation,
    Occurrence,
    Rapport,
)

TEXTE = "Le port du casque est obligatoire en zone A pour toute intervention."


def cote(preuve: str, texte: str | None = TEXTE, doc: str = "D1", ref: str = "5.4") -> CoteClause:
    return CoteClause(doc=doc, ref=ref, clause_id=f"{doc}::{ref}", preuve=preuve, texte_source=texte)


def constatation(a: CoteClause, b: CoteClause | None = None, **extra) -> Constatation:
    return Constatation(id="T-001", type="NEGATION", detecteur="A1", etage="A",
                        clause_a=a, clause_b=b, **extra)


# ═══════════════════════════════════════════ étape 3 — preuves littérales bloquantes


def test_un_rapport_sain_est_conforme_a_cent_pour_cent():
    """Test POSITIF : deux preuves littérales, aucun échec."""
    rapport = Rapport(constatations=[constatation(cote("est obligatoire"), cote("en zone A"))])

    bilan = module_preuves.verifier(rapport)

    assert bilan.conforme
    assert (bilan.verifiees, bilan.taux) == (2, 1.0)


def test_une_preuve_reformulee_fait_echouer_la_verification():
    """⭐ Test NÉGATIF : le cas que le garde-fou doit arrêter.

    « le casque est obligatoire » est une reformulation fidèle du sens, et n'existe pas
    littéralement dans le texte. C'est exactement ce qu'un LLM produit quand il croit citer.
    """
    rapport = Rapport(constatations=[constatation(cote("le casque est obligatoire"))])

    bilan = module_preuves.verifier(rapport)

    assert not bilan.conforme
    assert bilan.echecs[0].motif is module_preuves.MotifEchecPreuve.PREUVE_NON_LITTERALE


def test_un_seul_caractere_de_difference_suffit_a_faire_echouer():
    """La vérification est littérale, pas approximative."""
    rapport = Rapport(constatations=[constatation(cote("est obligatoires"))])

    assert not module_preuves.verifier(rapport).conforme


def test_un_texte_source_absent_est_un_echec_et_non_une_dispense():
    """⭐ La différence exacte avec `CoteClause.preuve_est_litterale`, qui est permissive.

    Sans texte contre quoi vérifier, il n'y a pas de vérification : le dire est la seule
    réponse honnête. Une méthode permissive convient à un rapport partiel ; une porte
    bloquante ne peut pas s'en contenter.
    """
    permissive = cote("n'importe quoi", texte=None)
    assert permissive.preuve_est_litterale() is True

    bilan = module_preuves.verifier(Rapport(constatations=[constatation(permissive)]))

    assert not bilan.conforme
    assert bilan.echecs[0].motif is module_preuves.MotifEchecPreuve.TEXTE_SOURCE_ABSENT


def test_une_constatation_sans_preuve_est_un_echec():
    """Une affirmation qui ne cite rien ne devrait pas être une constatation."""
    bilan = module_preuves.verifier(Rapport(constatations=[constatation(cote(""))]))

    assert bilan.echecs[0].motif is module_preuves.MotifEchecPreuve.PREUVE_ABSENTE


def test_une_derogation_sans_preuve_n_est_pas_un_echec():
    """Test NÉGATIF de l'exigence : lister n'est pas affirmer.

    Une constatation accuse et doit citer ; une dérogation informe. L'exigence de preuve ne
    porte donc que sur les constatations.
    """
    rapport = Rapport(derogations_en_vigueur=[Derogation(id="D", clause_a=cote(""))])

    assert module_preuves.verifier(rapport).conforme


def test_une_derogation_qui_cite_faux_est_un_echec():
    """Mais si elle cite, elle est tenue par la même règle que tout le reste."""
    rapport = Rapport(
        derogations_en_vigueur=[Derogation(id="D", clause_a=cote("inventé de toutes pièces"))]
    )

    assert not module_preuves.verifier(rapport).conforme


def test_les_occurrences_regroupees_sont_verifiees_aussi():
    """Le regroupement recopie des preuves : elles restent citées, donc contrôlées."""
    constat = constatation(
        cote("est obligatoire"),
        occurrences=[
            Occurrence(id="T-001", clause_a=cote("est obligatoire")),
            Occurrence(id="T-002", clause_a=cote("cette preuve n'existe pas")),
        ],
    )

    bilan = module_preuves.verifier(Rapport(constatations=[constat]))

    assert not bilan.conforme
    assert bilan.echecs[0].identifiant == "T-002"


def test_l_occurrence_representante_n_est_pas_comptee_deux_fois():
    """Elle EST la constatation : la recompter gonflerait le dénominateur pour rien."""
    constat = constatation(
        cote("est obligatoire"),
        occurrences=[Occurrence(id="T-001", clause_a=cote("est obligatoire"))],
    )

    assert module_preuves.verifier(Rapport(constatations=[constat])).total == 1


def test_un_rapport_vide_est_conforme():
    """Il n'affirme rien, donc il ne ment pas — et l'évaluation d'un rapport vide doit
    rendre des chiffres, pas une exception."""
    bilan = module_preuves.verifier(Rapport())

    assert bilan.conforme and bilan.taux == 1.0


def test_le_bilan_nomme_chaque_echec_plutot_que_de_les_compter():
    """Un compteur d'échecs sans leur liste ne permet pas de corriger."""
    rapport = Rapport(constatations=[constatation(cote("faux"), cote("faux aussi"))])

    texte = module_preuves.formater_bilan(module_preuves.verifier(rapport), couleur=False)

    assert "D1 §5.4" in texte and "PREUVE_NON_LITTERALE" in texte


# ═══════════════════════════════════════════════ étape 5 — dérogations en vigueur


@pytest.fixture(scope="module")
def derogations_du_corpus(frames, jeu):
    clauses = {c.clause_id: c for s in jeu.values() for c in s.clauses}
    return module_derogations.derogations_en_vigueur(frames, clauses, date(2026, 8, 10))


def test_la_derogation_valide_est_listee(derogations_du_corpus):
    """⭐ Test POSITIF : N05 — déclarée, motivée, approuvée, non expirée.

    `label.json` : « elle doit apparaître dans la rubrique dérogations en vigueur du
    rapport, pas dans les incohérences ».
    """
    listees = {(d.clause_a.doc, d.clause_a.ref) for d in derogations_du_corpus}

    assert ("D1", "10.1") in listees


def test_la_derogation_orpheline_n_est_pas_listee(derogations_du_corpus):
    """Test NÉGATIF : I17 — PR-QSE-02 est absent du corpus, la cible n'est pas résolvable."""
    listees = {(d.clause_a.doc, d.clause_a.ref) for d in derogations_du_corpus}

    assert ("D1", "10.2") not in listees


def test_la_derogation_expiree_n_est_pas_listee(derogations_du_corpus):
    """Test NÉGATIF : I18 — échéance au 31 décembre 2024, dépassée le 10 août 2026."""
    listees = {(d.clause_a.doc, d.clause_a.ref) for d in derogations_du_corpus}

    assert ("D1", "10.3") not in listees


def test_le_corpus_ne_compte_qu_une_derogation_en_vigueur(derogations_du_corpus):
    """Les trois dérogations du corpus se séparent proprement : une valide, deux écartées."""
    assert len(derogations_du_corpus) == 1


def test_la_derogation_listee_porte_de_quoi_la_juger(derogations_du_corpus):
    """Une rubrique qui dirait seulement « il y a une dérogation » n'aiderait personne."""
    derogation = derogations_du_corpus[0]

    assert derogation.justification and derogation.approbateur
    assert derogation.echeance == date(2026, 12, 31)
    assert "6.4" in derogation.cible


def test_la_derogation_porte_la_clause_a_laquelle_elle_deroge(derogations_du_corpus, verite):
    """⭐ Sans le côté visé, le harnais n'apparie pas la dérogation — mesuré au J7.

    `label.json` désigne N05 par la **paire** `D1 §10.1 ↔ D2 §6.4` ; l'appariement se fait
    sur le `frozenset` des deux couples. Une dérogation qui ne porterait que sa clause
    source resterait « absente du rapport » alors même qu'elle y figure.
    """
    from cohera.evaluation import metriques

    derogation = derogations_du_corpus[0]
    assert derogation.clause_b is not None
    assert derogation.clause_b.couple() == ("D2", "6.4")

    attendue = next(e for e in verite["contre_exemples"] if e["id"] == "N05")
    obtenue = frozenset({derogation.clause_a.couple(), derogation.clause_b.couple()})
    assert obtenue == metriques.cle_entree(attendue)


def test_les_preuves_des_derogations_sont_litterales(derogations_du_corpus):
    """La rubrique passe la même porte bloquante que les constatations."""
    bilan = module_preuves.verifier(Rapport(derogations_en_vigueur=derogations_du_corpus))

    assert bilan.conforme and bilan.verifiees == 1


def test_une_echeance_depassee_a_la_date_de_reference_ecarte_la_derogation(frames, jeu):
    """Test NÉGATIF sur la date : la même dérogation, jugée après son terme.

    Vérifie que c'est bien la date de RÉFÉRENCE qui décide, et non la date du jour.
    """
    clauses = {c.clause_id: c for s in jeu.values() for c in s.clauses}

    apres = module_derogations.derogations_en_vigueur(frames, clauses, date(2027, 1, 1))

    assert apres == []


# ═══════════════════════════════════════ étape 7 — le jeu dérivé, sans toucher aux fixtures


def test_le_jeu_derive_applique_sa_substitution():
    """Test POSITIF : D1 §5.1 passe de « tous les trimestres » à « deux fois par an »."""
    from cohera.ingestion import segmenter_jeu

    derive = segmenter_jeu("incremental")
    clause = next(c for c in derive["D1"].clauses if c.ref == "5.1")

    assert "deux fois par an" in clause.texte_source
    assert "tous les trimestres" not in clause.texte_source


def test_le_jeu_derive_ne_touche_pas_au_corpus_de_reference():
    """⭐ `corpus/fixtures/` est en LECTURE SEULE — y compris pour le scénario incrémental."""
    from cohera import reglages
    from cohera.ingestion import segmenter_jeu

    segmenter_jeu("incremental")

    source = (reglages.racine_projet() / "corpus" / "fixtures" / "file-1.txt").read_text(
        encoding="utf-8"
    )
    assert "tous les trimestres" in source
    assert "deux fois par an" not in source


def test_le_jeu_derive_conserve_le_reste_du_corpus():
    """Une seule clause change ; le compte de clauses et D2 sont intacts."""
    from cohera.ingestion import segmenter_jeu

    reference, derive = segmenter_jeu("fixtures"), segmenter_jeu("incremental")

    assert len(derive["D1"].clauses) == len(reference["D1"].clauses) == 41
    assert len(derive["D2"].clauses) == len(reference["D2"].clauses) == 37


def test_une_substitution_ambigue_est_refusee(monkeypatch):
    """Test NÉGATIF : une chaîne présente deux fois modifierait une clause non visée.

    On refuse plutôt que de deviner — même principe que « un rejet est définitif et
    silencieux, une escalade reste visible ».
    """
    from cohera import reglages
    from cohera.ingestion import materialiser_jeu_derive

    config = reglages.charger_config("corpus")
    truquee = {
        "jeux": dict(config["jeux"])
        | {
            "ambigu": {
                "derive_de": "fixtures",
                "substitutions": [{"document": "D1", "ref": "5.1", "ancien": "le", "nouveau": "LE"}],
            }
        }
    }
    monkeypatch.setattr(reglages, "charger_config", lambda nom: truquee if nom == "corpus" else config)

    with pytest.raises(ValueError, match="exactement une"):
        materialiser_jeu_derive("ambigu")


def test_la_date_de_reference_vient_de_la_configuration_pas_du_jour():
    """Un rapport dont le contenu change avec la date du jour n'est pas reproductible."""
    from cohera.ingestion import date_reference

    assert date_reference("fixtures") == date(2026, 8, 10)


def test_le_jeu_derive_herite_de_la_date_de_reference_de_sa_source():
    """Sinon le rapport incrémental jugerait les échéances autrement que le rapport comparé."""
    from cohera.ingestion import date_reference

    assert date_reference("incremental") == date_reference("fixtures")
