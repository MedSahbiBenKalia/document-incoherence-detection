"""detection/symbolique/a1.py — conflit déontique et écart de force.

architecture.md §7.1, corrigé en v2 : les cases vides de la matrice v1 sont remplacées par
un écart de force. « La procédure impose ce que la politique se contente de recommander »
est une incohérence réelle — un intervenant peut invoquer la politique pour ne pas porter
son casque, et l'obligation devient inopposable.

Hors ligne, mais le recouvrement d'objets est mesuré pour de bon — comme dans
`test_a2.py`, et pour la même raison.
"""

from __future__ import annotations

import pytest

from cohera.detection.modeles import Motif, TypeVerdict
from cohera.detection.objets import objets_partages
from cohera.detection.symbolique.a1 import a1, force_de
from cohera.extraction.frames import ClauseFrame, Modalite


@pytest.fixture(scope="module")
def juger(frames, identifiants, algebre, vocabulaire, pont):
    def _juger(doc_a, ref_a, doc_b, ref_b, partages=None, frame_a=None, frame_b=None):
        id_a = identifiants[(doc_a, ref_a)] if doc_a else frame_a.clause_id
        id_b = identifiants[(doc_b, ref_b)] if doc_b else frame_b.clause_id
        a = frame_a if frame_a is not None else frames[id_a]
        b = frame_b if frame_b is not None else frames[id_b]
        mesures = (
            partages
            if partages is not None
            else objets_partages(id_a, id_b, vocabulaire, pont)
        )
        return a1(a, b, algebre, objets_partages=mesures)

    return _juger


# ------------------------------------------------------------------ l'échelle de force


@pytest.mark.parametrize(
    "modalite, force",
    [
        (Modalite.INTERDICTION, 4),
        (Modalite.OBLIGATION, 3),
        (Modalite.RECOMMANDATION, 2),
        (Modalite.PERMISSION, 1),
    ],
)
def test_l_echelle_est_lue_dans_la_configuration(modalite: Modalite, force: int) -> None:
    """`config/detection.yaml`, jamais en dur (`CLAUDE.md`)."""
    assert force_de(modalite) == force


@pytest.mark.parametrize("modalite", [Modalite.CONSTAT, Modalite.DEFINITION])
def test_les_modalites_non_prescriptives_n_ont_pas_de_force(modalite: Modalite) -> None:
    """Une définition et un constat ne prescrivent rien : ils ne peuvent pas se contredire
    par la force. `Modalite` les porte quand même, l'échelle ne les connaît pas."""
    assert force_de(modalite) is None


def test_la_force_est_recalculee_depuis_la_modalite_et_non_reprise_de_la_frame() -> None:
    """**Piège du J2, désamorcé ici.** `regles/deontique.py` inverse la modalité sous
    l'effet d'une négation — « ne doit pas » devient INTERDICTION — mais laisse `force` à
    la valeur du marqueur d'origine, soit 3. Reprendre `frame.force` donnerait donc une
    interdiction de force 3, et l'écart avec une obligation vaudrait 0 au lieu de 1.

    Le corpus n'a pas ce cas — ses marqueurs négatifs (« ne sont pas autorisées ») sont
    déjà déclarés en INTERDICTION 4 dans le lexique — d'où cette frame synthétique."""
    incoherente = ClauseFrame(
        clause_id="X", modalite=Modalite.INTERDICTION, force=3, negation=True,
        modalite_surface="ne doit pas",
    )
    assert incoherente.force == 3
    assert force_de(incoherente.modalite) == 4


# ------------------------------------------------------------------------ le positif


def test_i04_permission_contre_interdiction_est_un_conflit_fort(juger) -> None:
    """D1 §7.4 autorise l'échelle comme poste de travail pour les interventions de moins de
    30 minutes ; D2 §7.4 l'interdit sur l'ensemble du site. PERMISSION (1) contre
    INTERDICTION (4) : écart 3, et polarités opposées. Conflit fort et ferme."""
    verdict = juger("D1", "7.4", "D2", "7.4")
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert verdict.ferme
    assert verdict.type_taxonomie == "NEGATION"
    assert verdict.gravite == "CRITIQUE"
    assert verdict.est_constatation


def test_i04_porte_les_deux_marqueurs_deontiques_en_preuve(juger, textes, identifiants) -> None:
    """Invariant #3 : la preuve est le marqueur littéral, sous-chaîne de `texte_source`."""
    verdict = juger("D1", "7.4", "D2", "7.4")
    assert verdict.preuve_a == "est autorisée"
    assert verdict.preuve_b == "est interdite"
    assert verdict.preuve_a in textes[identifiants[("D1", "7.4")]]
    assert verdict.preuve_b in textes[identifiants[("D2", "7.4")]]


def test_i05_ecart_de_un_escalade_au_lieu_d_affirmer(juger) -> None:
    """D1 §5.4 rend le casque obligatoire en zone A, D2 §5.4 se contente de le recommander,
    dans la même zone A. OBLIGATION (3) contre RECOMMANDATION (2) : écart 1.

    C'est une incohérence réelle — `label.json` la liste en I05, gravité ÉLEVÉE — mais
    l'architecture la déclare NON FERME et exige l'escalade vers l'étage B. Elle n'est donc
    pas une constatation du J5, et ce test le dit plutôt que de le taire."""
    verdict = juger("D1", "5.4", "D2", "5.4")
    assert verdict.type is TypeVerdict.DIVERGENCE_PERSPECTIVE
    assert verdict.motif is Motif.ECART_DE_FORCE
    assert not verdict.ferme
    assert not verdict.est_constatation
    assert verdict.relation_portees == "IDENTIQUE"


# ------------------------------------------------------------------ les négatifs


def test_n09_la_negation_est_absorbee_et_l_ecart_est_nul(juger, frames, identifiants) -> None:
    """**Le piège d'A1.** D1 §7.3 est formulé négativement (« ne sont pas autorisées »),
    D2 §7.3 positivement (« sont suspendus ») : un détecteur déontique naïf y voit une
    opposition de polarité. En réalité les deux énoncés interdisent la même chose au même
    seuil de vent.

    Le test assert les deux modalités RÉSOLUES et l'écart, pas seulement l'absence de
    verdict : c'est la seule façon de savoir que la portée de négation a été gérée, et non
    que le test passe par accident."""
    a = frames[identifiants[("D1", "7.3")]]
    b = frames[identifiants[("D2", "7.3")]]
    assert (a.modalite, a.negation) == (Modalite.INTERDICTION, True)
    assert (b.modalite, b.negation) == (Modalite.INTERDICTION, False)
    assert force_de(a.modalite) == force_de(b.modalite) == 4

    verdict = juger("D1", "7.3", "D2", "7.3")
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.ECART_DE_FORCE_NUL


def test_n09_a_bien_le_meme_seuil_des_deux_cotes(algebre, frames, identifiants) -> None:
    """L'autre moitié de N09, que `label.json` demande explicitement : « seuil identique
    (A2) ». Les deux clauses portent la même condition SEUIL « 50 km/h », donc la même
    condition dédupliquée — ce n'est pas une coïncidence de surface."""
    from cohera.graphe.conditions import Relation

    a = next(c for c in frames[identifiants[("D1", "7.3")]].conditions if c.valeur == 50.0)
    b = next(c for c in frames[identifiants[("D2", "7.3")]].conditions if c.valeur == 50.0)
    assert algebre.relation(a, b) is Relation.RECOUVRE


def test_n02_deux_obligations_distinctes_ne_se_contredisent_pas(juger) -> None:
    """D1 §5.4 (casque, zone A) et D2 §5.6 (gants, opérations de chargement) : deux
    obligations aux formulations très proches. Écart de force nul.

    La paire n'est jamais candidate au J4 — la liste noire tient `casque`/`gants`
    disjoints et le cosinus reste sous le seuil — mais A1 doit se taire même si on la lui
    présente, sans quoi le zéro faux positif tiendrait au seul ciblage."""
    verdict = juger("D1", "5.4", "D2", "5.6")
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.ECART_DE_FORCE_NUL


def test_une_clause_sans_modalite_ne_declenche_rien(juger) -> None:
    """I12 : les deux clauses sont prescriptives sans marqueur déontique, le J2 laisse donc
    `modalite = null`. A1 n'a rien à comparer — c'est A2 qui traite, ou personne."""
    verdict = juger("D1", "6.2", "D2", "6.2")
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.MODALITE_ABSENTE


def test_une_definition_ne_se_contredit_pas_par_la_force(juger) -> None:
    """I19 : D1 §3.2 et D2 §3.2 définissent toutes deux « zone à risque », de façon
    incompatible. C'est une divergence terminologique (A6, hors périmètre 7 jours), pas un
    conflit déontique — et A1 ne doit pas s'en emparer par accident."""
    verdict = juger("D1", "3.2", "D2", "3.2")
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.MODALITE_NON_PRESCRIPTIVE


def test_des_conditions_disjointes_arretent_a1(juger, frames, identifiants) -> None:
    """Cas négatif de la lecture des portées par A1. On oppose la modalité de D2 §5.4
    (RECOMMANDATION, zone A) à celle de D1 §5.4 (OBLIGATION) mais en déplaçant la première
    en zone de stockage, dans une COPIE MÉMOIRE : deux règles qui ne se rencontrent jamais
    ne se contredisent pas, quel que soit leur écart de force."""
    ailleurs = frames[identifiants[("D2", "5.4")]].model_copy(deep=True)
    ailleurs.conditions = list(frames[identifiants[("D2", "5.2")]].conditions)

    verdict = juger("D1", "5.4", None, None, frame_b=ailleurs)
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.PORTEES_DISJOINTES


def test_une_portee_indeterminee_n_arrete_pas_a1_alors_qu_elle_arrete_a2(
    juger, frames, identifiants, algebre
) -> None:
    """**L'asymétrie A1/A2, mesurée et figée.**

    I04 oppose une condition POPULATIONNELLE (D1 §7.4, « pour les interventions de moins de
    30 minutes ») à une condition SPATIALE (D2 §7.4, « sur l'ensemble du site »). Aucune
    règle typée ne relie ces deux types : la relation des portées vaut INDÉTERMINÉE.

    A2 rétrograderait — comparer deux valeurs suppose de savoir si elles s'appliquent jamais
    au même cas. A1 conclut quand même : architecture.md §7.1 ne lui demande que des
    conditions « non disjointes », et une permission contre une interdiction sur le même
    acte se contredisent dès que les périmètres *peuvent* se recouvrir. Sans cette
    asymétrie, I04 serait perdue."""
    from cohera.detection.portees import RelationPortees, relation_portees

    a = frames[identifiants[("D1", "7.4")]]
    b = frames[identifiants[("D2", "7.4")]]
    assert relation_portees(a, b, algebre) is RelationPortees.INDETERMINEE

    verdict = juger("D1", "7.4", "D2", "7.4")
    assert verdict.relation_portees == "INDETERMINEE"
    assert verdict.ferme


def test_le_garde_fou_des_objets_s_applique_aussi_a_a1(juger) -> None:
    """A1 et A2 partagent la même discipline de preuve : sans recouvrement d'objets, une
    opposition de modalités escalade au lieu d'affirmer.

    Le corpus ne fournit pas le cas — I04 partage 7 objets, I05 en partage 3 — d'où le
    compte forcé. Sans ce test, la garde d'A1 ne serait jamais exécutée."""
    verdict = juger("D1", "7.4", "D2", "7.4", partages=0)
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert not verdict.ferme
    assert verdict.motif is Motif.OBJETS_SANS_RECOUVREMENT


def test_i04_et_i05_passent_le_garde_fou_des_objets(
    vocabulaire, pont, identifiants
) -> None:
    """Le pendant positif : mesuré, I04 partage 7 objets canoniques (« échelle comme poste
    de travail », « utilisation »…) et I05 en partage 3 (« casque », « zone A », « zone »).
    La garde ne coûte donc rien à A1 sur ce corpus."""
    i04 = objets_partages(
        identifiants[("D1", "7.4")], identifiants[("D2", "7.4")], vocabulaire, pont
    )
    i05 = objets_partages(
        identifiants[("D1", "5.4")], identifiants[("D2", "5.4")], vocabulaire, pont
    )
    assert i04 >= 2 and i05 >= 2
