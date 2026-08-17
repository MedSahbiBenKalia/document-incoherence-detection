"""Regroupement des constatations — architecture.md §8.2.

Deux mécanismes distincts vivent dans `consolidation/constatations.py`, et les confondre
serait une faute :

* le **regroupement** fusionne N paires qui manifestent une même divergence de fond, par la
  clé `(type, clé de comparaison, valeurs en conflit)` de §8.2 ;
* l'**absorption** range une anomalie *mono-clause* sous la constatation de *paire* qui
  porte déjà la même preuve littérale sur cette clause.

Sur le corpus fixtures, seule l'absorption travaille : c'est elle qui corrige le faux
positif `D2 §10.1`, seconde moitié du double constat d'I08 (« référentiels divergents ET
OHSAS 18001 retirée », dit `label.json` lui-même).

⚠️ **Le risque de cette étape est de faire disparaître un vrai positif sans bruit.** Le
harnais apparie sur le `frozenset` des couples `(doc, ref)` : un regroupement qui change la
clé d'une constatation la retire silencieusement du barème. D'où le test d'intégration en
fin de fichier, qui rejoue le regroupement sur un vrai rapport et vérifie que les 9 vrais
positifs sont tous encore appariés.
"""

from __future__ import annotations

import pytest

from cohera.consolidation.constatations import regrouper
from cohera.evaluation import metriques
from cohera.restitution.rapport_json import (
    Constatation,
    CoteClause,
    charger_rapport,
)


# ------------------------------------------------------------------- fabrication


def _cote(doc: str, ref: str, preuve: str) -> CoteClause:
    """Un côté de constatation dont la preuve est littérale par construction."""
    return CoteClause(
        doc=doc, ref=ref, clause_id=f"{doc}::{ref}", preuve=preuve, texte_source=preuve
    )


def constatation(
    identifiant: str,
    type_: str,
    a: tuple[str, str, str],
    b: tuple[str, str, str] | None = None,
    *,
    detecteur: str = "A5",
    cle_comparaison: str = "",
) -> Constatation:
    return Constatation(
        id=identifiant,
        type=type_,
        detecteur=detecteur,
        etage="A",
        gravite="ELEVEE",
        confiance=0.95,
        cle_comparaison=cle_comparaison,
        clause_a=_cote(*a),
        clause_b=_cote(*b) if b else None,
    )


#: Le double constat d'I08, tel que la cascade le produit réellement au J6.
DOUBLE_CONSTAT_I08 = (
    constatation("A5-004", "FACTUEL", ("D2", "10.1", "OHSAS 18001")),
    constatation(
        "A5-011", "FACTUEL", ("D1", "2.1", "ISO 45001:2018"), ("D2", "10.1", "OHSAS 18001")
    ),
)


# ------------------------------------------------------------------- l'absorption


def test_la_moitie_mono_clause_du_double_constat_est_absorbee():
    """⭐ Le cas qui corrige le faux positif `D2 §10.1` — test POSITIF de l'absorption."""
    regroupees = regrouper(list(DOUBLE_CONSTAT_I08))

    assert len(regroupees) == 1
    survivante = regroupees[0]

    # C'est la constatation de PAIRE qui survit : elle seule s'apparie à I08 dans le harnais.
    assert survivante.id == "A5-011"
    assert survivante.clause_b is not None
    assert survivante.clause_a.couple() == ("D1", "2.1")
    assert survivante.clause_b.couple() == ("D2", "10.1")

    # L'absorbée n'est pas perdue : elle devient une occurrence, et le compte le dit.
    assert survivante.nb_occurrences == 2
    assert {o.id for o in survivante.occurrences} == {"A5-004", "A5-011"}


def test_l_absorption_retire_la_cle_qui_faisait_le_faux_positif():
    """Le harnais apparie sur le `frozenset` des couples : c'est CETTE clé qui doit partir."""
    avant = {metriques.cle_constatation(c) for c in DOUBLE_CONSTAT_I08}
    apres = {metriques.cle_constatation(c) for c in regrouper(list(DOUBLE_CONSTAT_I08))}

    mono = frozenset({("D2", "10.1")})
    paire = frozenset({("D1", "2.1"), ("D2", "10.1")})

    assert mono in avant and paire in avant
    assert apres == {paire}, "la clé mono-clause doit disparaître, celle de la paire rester"


def test_une_anomalie_mono_clause_sans_paire_survit_intacte():
    """Test NÉGATIF : I09 et I10 n'ont aucune paire correspondante, rien ne les absorbe."""
    i09 = constatation("A5-001", "FACTUEL", ("D1", "7.5", "§ 12.3"))
    i10 = constatation("A5-003", "FACTUEL", ("D2", "6.3", "§ 11.2 de la procédure PR-QSE-04"))

    regroupees = regrouper([i09, i10, *DOUBLE_CONSTAT_I08])

    survivantes = {c.id for c in regroupees}
    assert survivantes == {"A5-001", "A5-003", "A5-011"}
    for constat in regroupees:
        if constat.id in {"A5-001", "A5-003"}:
            assert constat.nb_occurrences == 1


def test_pas_d_absorption_quand_la_preuve_differe():
    """Test NÉGATIF : partager une clause ne suffit pas — il faut la MÊME preuve littérale.

    C'est le garde-fou qui empêche d'absorber une anomalie mono-clause dans une constatation
    de paire qui parle d'autre chose sur la même clause. Sans lui, `D1 §10.2` (renvoi vers
    une procédure absente) disparaîtrait dans la paire `D1 §10.2 ↔ D2 §4.2` que le profil
    distant produit, alors que les deux constats n'ont aucun rapport.
    """
    mono = constatation("A5-002", "FACTUEL", ("D1", "10.2", "procédure PR-QSE-02 § 3.1"))
    paire = constatation(
        "C-020", "FACTUEL", ("D1", "10.2", "Par dérogation"), ("D2", "4.2", "sous 5 jours")
    )

    regroupees = regrouper([mono, paire])

    assert {c.id for c in regroupees} == {"A5-002", "C-020"}


def test_pas_d_absorption_quand_le_type_differe():
    """Test NÉGATIF : même clause, même preuve, mais deux natures de problème distinctes."""
    mono = constatation("A5-004", "FACTUEL", ("D2", "10.1", "OHSAS 18001"))
    paire = constatation(
        "A2-030", "NUMERIQUE", ("D1", "2.1", "ISO 45001:2018"), ("D2", "10.1", "OHSAS 18001")
    )

    regroupees = regrouper([mono, paire])

    assert {c.id for c in regroupees} == {"A5-004", "A2-030"}


def test_une_paire_n_absorbe_jamais_une_autre_paire():
    """L'absorption va du mono-clause vers la paire, jamais de paire à paire.

    Deux paires ne se fusionnent que par le regroupement de §8.2, qui exige une clé de
    comparaison — pas par la seule présence d'une preuve commune.
    """
    gauche = constatation(
        "A5-011", "FACTUEL", ("D1", "2.1", "ISO 45001:2018"), ("D2", "10.1", "OHSAS 18001")
    )
    droite = constatation(
        "A5-012", "FACTUEL", ("D1", "9.9", "OHSAS 18001"), ("D2", "10.1", "OHSAS 18001")
    )

    assert len(regrouper([gauche, droite])) == 2


# ------------------------------------------------------- le regroupement de §8.2


def test_deux_paires_de_meme_cle_et_memes_valeurs_sont_regroupees():
    """Test POSITIF du `groupby` de §8.2 : un seul problème de fond, deux manifestations.

    Le cas décrit par l'architecture : « la valeur 3 mois apparaît dans 4 clauses de D1 et
    6 mois dans 3 clauses de D2 → 12 paires signalées pour UN SEUL problème ».
    """
    cle = "responsable qse|valider|fiche de controle|TEMPS|delai"
    premiere = constatation(
        "A2-005", "NUMERIQUE", ("D1", "4.2", "48 heures"), ("D2", "4.2", "5 jours"),
        detecteur="A2", cle_comparaison=cle,
    )
    seconde = constatation(
        "A2-006", "NUMERIQUE", ("D1", "4.7", "48 heures"), ("D2", "4.8", "5 jours"),
        detecteur="A2", cle_comparaison=cle,
    )

    regroupees = regrouper([premiere, seconde])

    assert len(regroupees) == 1
    assert regroupees[0].nb_occurrences == 2
    assert {o.id for o in regroupees[0].occurrences} == {"A2-005", "A2-006"}


def test_les_valeurs_en_conflit_sont_comparees_sans_ordre():
    """« 48 heures contre 5 jours » et « 5 jours contre 48 heures » sont le même problème."""
    cle = "responsable qse|valider|fiche de controle|TEMPS|delai"
    endroit = constatation(
        "A2-005", "NUMERIQUE", ("D1", "4.2", "48 heures"), ("D2", "4.2", "5 jours"),
        detecteur="A2", cle_comparaison=cle,
    )
    envers = constatation(
        "A2-006", "NUMERIQUE", ("D2", "4.8", "5 jours"), ("D1", "4.7", "48 heures"),
        detecteur="A2", cle_comparaison=cle,
    )

    assert len(regrouper([endroit, envers])) == 1


def test_pas_de_regroupement_sur_une_cle_de_comparaison_absente():
    """Test NÉGATIF, et c'est le garde-fou central du regroupement.

    Une clé partielle ne regroupe pas. Regrouper sur le seul `type` fusionnerait toutes les
    divergences numériques du corpus en une ligne, ce qui détruirait le rapport au lieu de
    le rendre lisible — et ferait disparaître des vrais positifs du barème.
    """
    premiere = constatation(
        "A2-005", "NUMERIQUE", ("D1", "4.2", "48 heures"), ("D2", "4.2", "5 jours"),
        detecteur="A2",
    )
    seconde = constatation(
        "A2-009", "NUMERIQUE", ("D1", "5.1", "trimestres"), ("D2", "5.1", "deux fois par an"),
        detecteur="A2",
    )

    assert len(regrouper([premiere, seconde])) == 2


def test_meme_cle_mais_valeurs_differentes_ne_regroupe_pas():
    """Test NÉGATIF : la clé de §8.2 porte AUSSI les valeurs en conflit."""
    cle = "responsable qse|valider|fiche de controle|TEMPS|delai"
    premiere = constatation(
        "A2-005", "NUMERIQUE", ("D1", "4.2", "48 heures"), ("D2", "4.2", "5 jours"),
        detecteur="A2", cle_comparaison=cle,
    )
    seconde = constatation(
        "A2-006", "NUMERIQUE", ("D1", "4.7", "72 heures"), ("D2", "4.8", "9 jours"),
        detecteur="A2", cle_comparaison=cle,
    )

    assert len(regrouper([premiere, seconde])) == 2


def test_le_regroupement_est_idempotent():
    """Rejouer le regroupement sur son propre résultat ne change rien.

    Même exigence que pour le chargement du graphe : une étape de consolidation qui dérive
    à chaque passage rendrait `nb_occurrences` ininterprétable.
    """
    une_fois = regrouper(list(DOUBLE_CONSTAT_I08))
    deux_fois = regrouper(une_fois)

    assert len(deux_fois) == 1
    assert deux_fois[0].nb_occurrences == une_fois[0].nb_occurrences == 2


def test_le_regroupement_ne_modifie_pas_la_liste_recue():
    """Fonction pure : l'appelant garde son rapport d'origine intact pour comparaison."""
    origine = list(DOUBLE_CONSTAT_I08)
    regrouper(origine)

    assert len(origine) == 2
    assert all(not c.occurrences for c in origine)


# ------------------------------------------------------------- test d'intégration


def _degrouper(constatations: list[Constatation]) -> list[Constatation]:
    """Défait un regroupement : une constatation par manifestation.

    ⚠️ **Pourquoi le test en a besoin.** Le rapport versionné est celui que le pipeline
    produit, donc déjà consolidé. Un test qui supposerait le contraire dépendrait de
    l'artefact *ne pas* avoir été régénéré — et casserait le jour où il l'est, sans qu'aucun
    comportement n'ait changé. On reconstruit donc l'état d'avant regroupement à partir des
    occurrences que la consolidation a précisément conservées pour cela.
    """
    eclatees: list[Constatation] = []
    for constatation in constatations:
        if not constatation.occurrences:
            eclatees.append(constatation)
            continue
        for occurrence in constatation.occurrences:
            eclatees.append(
                constatation.model_copy(
                    update={
                        "id": occurrence.id,
                        "detecteur": occurrence.detecteur or constatation.detecteur,
                        "etage": occurrence.etage or constatation.etage,
                        "clause_a": occurrence.clause_a,
                        "clause_b": occurrence.clause_b,
                        "occurrences": [],
                    }
                )
            )
    return eclatees


@pytest.fixture(scope="module")
def rapport_du_profil_local():
    """Le rapport du profil local, versionné — une base de mesure stable."""
    from cohera import reglages

    chemin = reglages.racine_projet() / "rapport_local.json"
    if not chemin.is_file():
        pytest.fail(f"{chemin.name} est absent : `cohera detecter --llm local` d'abord.")
    return charger_rapport(chemin)


def test_sur_le_rapport_reel_seule_la_moitie_du_double_constat_disparait(
    rapport_du_profil_local, verite
):
    """⭐ Le chiffre de la journée : 18 constatations → 17, et 4 faux positifs → 3.

    Le test le plus important du fichier : il vérifie sur un **vrai** rapport que le
    regroupement retire **exactement** le faux positif visé, et **aucun vrai positif**.

    L'état « avant » est reconstruit en défaisant le regroupement, ce qui rend le test
    indépendant du fait que l'artefact versionné soit consolidé ou non.
    """
    rapport = rapport_du_profil_local.model_copy(deep=True)
    rapport.constatations = _degrouper(rapport.constatations)

    avant = metriques.evaluer(rapport, verite).perimetre_7j
    assert len(rapport.constatations) == 18
    assert (len(avant.vrais_positifs), len(avant.faux_positifs)) == (9, 4)

    rapport.constatations = regrouper(rapport.constatations)
    apres = metriques.evaluer(rapport, verite).perimetre_7j

    assert len(rapport.constatations) == 17
    assert apres.vrais_positifs == avant.vrais_positifs, "aucun vrai positif ne doit tomber"
    assert len(apres.faux_positifs) == 3

    disparus = {tuple(fp.clauses) for fp in avant.faux_positifs} - {
        tuple(fp.clauses) for fp in apres.faux_positifs
    }
    assert disparus == {("D2 §10.1",)}


def test_le_rapport_publie_est_deja_consolide(rapport_du_profil_local):
    """Regrouper un rapport déjà consolidé ne change rien — l'idempotence, sur données réelles."""
    constatations = rapport_du_profil_local.constatations

    assert len(regrouper(constatations)) == len(constatations)
