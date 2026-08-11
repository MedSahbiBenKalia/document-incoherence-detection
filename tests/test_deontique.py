"""regles/deontique.py — modalité, force, portée de la négation.

Critère chiffré (docs/plan-1-semaine.md §J2) : ≥ 25/30 modalités correctes, dont
« ne doit pas valider » ≠ « doit ne pas valider ».
"""

from __future__ import annotations

import pytest

from cohera.extraction.frames import Modalite
from cohera.extraction.regles.deontique import extraire_modalite
from cohera.ingestion.modeles import Clause


def _clause(texte: str, texte_source: str | None = None) -> Clause:
    return Clause(
        clause_id="TEST::S0::C01",
        doc_id="TEST",
        ref="0.1",
        ordre=1,
        texte_source=texte_source if texte_source is not None else texte,
        texte_autonome=texte,
        offset=(0, len(texte_source if texte_source is not None else texte)),
    )


# --------------------------------------------------------- 19 marqueurs explicites réels


@pytest.mark.parametrize(
    "doc_fixture,ref,modalite,force",
    [
        ("d1", "3.1", Modalite.DEFINITION, None),  # on entend par « anomalie »
        ("d1", "3.2", Modalite.DEFINITION, None),  # « zone à risque » est... obligatoire (définition gagne)
        ("d1", "5.1", Modalite.OBLIGATION, 3),  # doit être renouvelé
        ("d1", "5.4", Modalite.OBLIGATION, 3),  # est obligatoire
        ("d1", "6.4", Modalite.PERMISSION, 1),  # peut poursuivre
        ("d1", "7.1", Modalite.OBLIGATION, 3),  # est requis
        ("d1", "7.3", Modalite.INTERDICTION, 4),  # ne sont pas autorisées
        ("d1", "7.4", Modalite.PERMISSION, 1),  # est autorisée
        ("d1", "10.1", Modalite.PERMISSION, 1),  # sont dispensées
        ("d2", "1.1", Modalite.OBLIGATION, 3),  # s'engage à
        ("d2", "4.2", Modalite.OBLIGATION, 3),  # est chargé de
        ("d2", "5.4", Modalite.RECOMMANDATION, 2),  # il est recommandé
        ("d2", "5.6", Modalite.OBLIGATION, 3),  # est obligatoire
        ("d2", "7.2", Modalite.RECOMMANDATION, 2),  # sont privilégiés
        ("d2", "7.3", Modalite.INTERDICTION, 4),  # sont suspendus
        ("d2", "7.4", Modalite.INTERDICTION, 4),  # est interdite
        ("d2", "10.2", Modalite.CONSTAT, None),  # prévalent
    ],
)
def test_une_modalite_reelle_du_corpus_est_correctement_classee(
    doc_fixture: str, ref: str, modalite: Modalite, force: int | None, request: pytest.FixtureRequest
) -> None:
    segmentation = request.getfixturevalue(doc_fixture)
    resultat = extraire_modalite(segmentation.clause(ref))
    assert resultat["modalite"] is modalite
    assert resultat.get("force") == force


def test_la_liste_a_chapeau_4_4_porte_l_obligation_via_texte_autonome(d1) -> None:
    """`texte_source` de l'item (c) ne contient AUCUN marqueur : seul `texte_autonome`
    (chapeau « L'Animateur QSE doit : » redistribué) révèle « doit »."""
    items = d1.par_ref("4.4")
    assert len(items) == 3
    for item in items:
        assert "doit" not in item.texte_source.lower() or item is items[0]
        resultat = extraire_modalite(item)
        assert resultat["modalite"] is Modalite.OBLIGATION
        assert resultat["force"] == 3


def test_le_repli_present_plus_gazetteer_classe_d2_4_3_a_confiance_reduite(d2) -> None:
    """« Le Référent sécurité anime le réseau... » : aucun marqueur explicite, mais un
    sujet du gazetteer au présent (architecture.md §4.2, confiance 0,78)."""
    resultat = extraire_modalite(d2.clause("4.3"))
    assert resultat["modalite"] is Modalite.OBLIGATION
    assert resultat["force"] == 3
    assert resultat["confiance_extraction"] == 0.78


# ------------------------------------------------------- paire synthétique de négation


def test_ne_doit_pas_valider_differe_de_doit_ne_pas_valider() -> None:
    a = extraire_modalite(_clause("Il ne doit pas valider la fiche."))
    b = extraire_modalite(_clause("Il doit ne pas valider la fiche."))
    assert (a["modalite"], a["negation"]) != (b["modalite"], b["negation"])
    assert a["modalite"] is Modalite.INTERDICTION
    assert a["negation"] is True
    assert b["modalite"] is Modalite.OBLIGATION
    assert b["negation"] is False


# ------------------------------------------------------------------- cas-pièges négatifs


def test_ne_permet_plus_negation_de_capacite_reste_une_definition(d1) -> None:
    """D1§3.3 : « ne permet plus » n'est pas déontique — la clause est de toute façon une
    DEFINITION (guillemets + copule), donc aucun marqueur n'y est même cherché."""
    resultat = extraire_modalite(d1.clause("3.3"))
    assert resultat["modalite"] is Modalite.DEFINITION


def test_ne_plus_hors_definition_ne_devient_pas_une_interdiction() -> None:
    """Isolé de toute définition : « ne...plus » qualifie une capacité, pas une norme."""
    resultat = extraire_modalite(_clause("Le dispositif ne fonctionne plus correctement."))
    assert resultat.get("modalite") is not Modalite.INTERDICTION


def test_autorisation_de_conduite_le_nom_ne_declenche_pas_le_marqueur_verbal(d1) -> None:
    """D1§8.3 : « autorisation(s) de conduite » partage le radical « autoris- » avec les
    marqueurs verbaux (« est autorisé »), mais c'est un nom, pas un verbe conjugué."""
    resultat = extraire_modalite(d1.clause("8.3"))
    assert resultat.get("modalite") not in (Modalite.PERMISSION, Modalite.INTERDICTION)


def test_un_passif_nu_sans_sujet_du_gazetteer_reste_sans_modalite(d1) -> None:
    """D1§7.2 : « Le point d'ancrage est vérifié... » — pas de marqueur, sujet hors
    gazetteer : le repli ne doit pas sur-déclencher."""
    resultat = extraire_modalite(d1.clause("7.2"))
    assert resultat.get("modalite") is None
