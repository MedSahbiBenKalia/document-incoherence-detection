"""Ablations du J7 et table `evaluation/historique.csv`.

Les ablations sont l'un des quatre livrables que `docs/plan-1-semaine.md` §5 classe
« **jamais** à couper » : « sans elles, tu ne peux rien affirmer dans le rapport ». Un
drapeau `--sans-alias` ne supprime donc rien — il éteint le pont le temps d'une exécution
pour chiffrer ce que son absence coûte, ce qui est la preuve qu'il sert.

Les tests qui touchent au graphe portent le marqueur `neo4j` : l'effet d'un canal désactivé
sur le ciblage ne se démontre pas sans serveur, c'est justement le comportement du graphe
qu'on mesure.
"""

from __future__ import annotations

import pytest

from cohera.ciblage.modeles import Canal
from cohera.evaluation import historique as table


# ═══════════════════════════════════════════════════ le levier des canaux


@pytest.mark.neo4j
def test_desactiver_le_canal_dimension_le_vide_sans_toucher_aux_autres(frames):
    """Test POSITIF de `--sans-canal5` : le canal disparaît, les trois autres sont intacts."""
    from cohera.ciblage import cibler
    from cohera.graphe.connexion import session as ouvrir_session

    with ouvrir_session() as session:
        complet = cibler(session, frames)
        ampute = cibler(session, frames, canaux_desactives=frozenset({Canal.DIMENSION}))

    assert complet.par_canal.get(Canal.DIMENSION.value)
    assert Canal.DIMENSION.value not in ampute.par_canal

    for canal in (Canal.CLE.value, Canal.CONCEPTUEL.value, Canal.VECTORIEL.value):
        assert len(ampute.par_canal.get(canal, [])) == len(complet.par_canal.get(canal, []))


@pytest.mark.neo4j
def test_un_ensemble_vide_de_canaux_desactives_ne_change_rien(frames):
    """Test NÉGATIF : le paramètre par défaut ne doit avoir aucun effet de bord."""
    from cohera.ciblage import cibler
    from cohera.graphe.connexion import session as ouvrir_session

    with ouvrir_session() as session:
        defaut = cibler(session, frames)
        explicite = cibler(session, frames, canaux_desactives=frozenset())

    assert len(defaut.candidates) == len(explicite.candidates)


@pytest.mark.neo4j
def test_le_drapeau_ne_modifie_pas_la_configuration(frames):
    """⭐ La config déclare ce qui existe, le drapeau éteint pour un run — jamais l'inverse.

    Muter `config/ciblage.yaml` serait de toute façon sans effet (`canal_actif` est mis en
    cache par `lru_cache`), mais surtout : une ablation qui laisserait une trace dans la
    configuration contaminerait toutes les exécutions suivantes.
    """
    from cohera.ciblage import cibler, config_ciblage
    from cohera.graphe.connexion import session as ouvrir_session

    with ouvrir_session() as session:
        cibler(session, frames, canaux_desactives=frozenset({Canal.DIMENSION}))

    assert config_ciblage.canal_actif(Canal.DIMENSION) is True


# ═══════════════════════════════════════════ la table historique


def test_consigner_cree_le_fichier_et_ses_colonnes(tmp_path):
    chemin = table.consigner(
        tmp_path / "evaluation" / "historique.csv",
        [table.ligne_depuis_bareme(
            jour="J4", configuration="ciblage seul", paires_candidates=72,
            rappel_ciblage="12/12", vrais_positifs=0, faux_positifs=0,
            attendues=12, precision=0.0,
        )],
    )

    lignes = table.lire(chemin)
    assert len(lignes) == 1
    assert set(lignes[0]) == set(table.COLONNES)


def test_consigner_deux_fois_la_meme_execution_remplace_au_lieu_d_empiler(tmp_path):
    """⭐ Rejouer les ablations trois fois ne doit pas donner trois fois les mêmes lignes."""
    chemin = tmp_path / "historique.csv"

    def ligne(faux_positifs: int) -> dict:
        return table.ligne_depuis_bareme(
            jour="J7", configuration="pipeline complet", profil="local",
            paires_candidates=72, rappel_ciblage="12/12", vrais_positifs=9,
            faux_positifs=faux_positifs, attendues=12, precision=0.75,
        )

    table.consigner(chemin, [ligne(4)])
    table.consigner(chemin, [ligne(3)])

    lignes = table.lire(chemin)
    assert len(lignes) == 1
    assert lignes[0]["faux_positifs"] == "3", "la mesure la plus récente doit gagner"


def test_deux_profils_du_meme_jour_sont_deux_lignes(tmp_path):
    """Test NÉGATIF de l'idempotence : le profil fait partie de la clé d'identité."""
    chemin = tmp_path / "historique.csv"

    for profil in ("local", "groq"):
        table.consigner(chemin, [table.ligne_depuis_bareme(
            jour="J6", configuration="pipeline complet", profil=profil,
            paires_candidates=72, rappel_ciblage="12/12", vrais_positifs=9,
            faux_positifs=3, attendues=12, precision=0.75,
        )])

    assert len(table.lire(chemin)) == 2


def test_la_table_est_ordonnee_du_premier_jour_au_dernier(tmp_path):
    """C'est une figure de rapport : elle se lit du J4 au J7, pas dans l'ordre des commandes."""
    chemin = tmp_path / "historique.csv"

    for jour in ("J7", "J4", "J6", "J5"):
        table.consigner(chemin, [table.ligne_depuis_bareme(
            jour=jour, configuration=f"config {jour}", paires_candidates=72,
            rappel_ciblage="12/12", vrais_positifs=0, faux_positifs=0,
            attendues=12, precision=0.0,
        )])

    assert [ligne["jour"] for ligne in table.lire(chemin)] == ["J4", "J5", "J6", "J7"]


def test_la_colonne_source_distingue_mesure_et_transcription(tmp_path):
    """Sans elle, on ne saurait pas quelles cellules sont des mesures et lesquelles des
    souvenirs — et une figure dont on ignore cela n'argumente rien."""
    chemin = tmp_path / "historique.csv"

    table.consigner(chemin, [
        table.ligne_depuis_bareme(
            jour="J4", configuration="ciblage seul", paires_candidates=72,
            rappel_ciblage="12/12", vrais_positifs=0, faux_positifs=0,
            attendues=12, precision=0.0,
        ),
        table.ligne_depuis_bareme(
            jour="J6", configuration="run distant cadencé", profil="groq",
            paires_candidates=72, rappel_ciblage="12/12", vrais_positifs=10,
            faux_positifs=9, attendues=12, precision=0.53,
            appels_llm=43, duree_s=420.0, source="journal",
        ),
    ])

    sources = {ligne["jour"]: ligne["source"] for ligne in table.lire(chemin)}
    assert sources == {"J4": "mesure", "J6": "journal"}


def test_lire_un_historique_absent_rend_une_liste_vide(tmp_path):
    """Comme `charger_rapport` : l'absence est un état, pas une erreur."""
    assert table.lire(tmp_path / "jamais_ecrit.csv") == []


def test_le_f1_est_calcule_et_non_recopie():
    ligne = table.ligne_depuis_bareme(
        jour="J7", configuration="c", paires_candidates=72, rappel_ciblage="12/12",
        vrais_positifs=9, faux_positifs=3, attendues=12, precision=0.75,
    )

    assert ligne["rappel"] == "9/12"
    assert ligne["f1"] == "0.75"


def test_un_bareme_vide_ne_fait_pas_diviser_par_zero():
    ligne = table.ligne_depuis_bareme(
        jour="J0", configuration="ligne de base", paires_candidates=0,
        rappel_ciblage="0/0", vrais_positifs=0, faux_positifs=0,
        attendues=0, precision=0.0,
    )

    assert ligne["f1"] == "0.00"


# ═══════════════════════════════════ la comparaison du scénario incrémental


def test_une_constatation_disparue_est_reperee_comme_resolue():
    """Test POSITIF du scénario incrémental : c'est ce qui donne le statut RESOLUE."""
    from cohera.cli import _comparer_rapports
    from cohera.restitution.rapport_json import Constatation, CoteClause, Rapport

    def constat(ref_a: str, ref_b: str) -> Constatation:
        return Constatation(
            id="X", type="NUMERIQUE",
            clause_a=CoteClause(doc="D1", ref=ref_a, preuve="a"),
            clause_b=CoteClause(doc="D2", ref=ref_b, preuve="b"),
        )

    avant = Rapport(constatations=[constat("5.1", "5.1"), constat("4.2", "4.2")])
    apres = Rapport(constatations=[constat("4.2", "4.2")])

    resolues, nouvelles = _comparer_rapports(avant, apres)

    assert [c.clause_a.ref for c in resolues] == ["5.1"]
    assert nouvelles == []


def test_un_identifiant_de_constatation_qui_change_ne_cree_pas_de_fausse_resolution():
    """⭐ Les identifiants sont réattribués à chaque exécution — comparer dessus mentirait.

    L'appariement se fait sur le couple de clauses, comme dans le harnais : c'est le même
    problème de fond qu'on suit d'une exécution à l'autre.
    """
    from cohera.cli import _comparer_rapports
    from cohera.restitution.rapport_json import Constatation, CoteClause, Rapport

    def constat(identifiant: str) -> Constatation:
        return Constatation(
            id=identifiant, type="NUMERIQUE",
            clause_a=CoteClause(doc="D1", ref="5.1", preuve="a"),
            clause_b=CoteClause(doc="D2", ref="5.1", preuve="b"),
        )

    resolues, nouvelles = _comparer_rapports(
        Rapport(constatations=[constat("A2-009")]),
        Rapport(constatations=[constat("A2-004")]),
    )

    assert (resolues, nouvelles) == ([], [])
