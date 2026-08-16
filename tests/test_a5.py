"""detection/symbolique/a5.py — références cassées et référentiels obsolètes.

Deux passes, deux natures. I09 et I10 sont des **anomalies mono-clause** : détectées sans
aucune comparaison de paire, donc sans rien coûter au ciblage. I08 est une paire, et le
double constat qu'attend `label.json` — référentiels divergents ET l'un des deux retiré.

**Source : les Clause Frames, pas le graphe.** `chargeur.py` n'écrit pas d'arête
`RENVOIE_A` ; `Reference.resolu` est calculé au J2 contre les `Segmentation` en mémoire.
Décision actée au J4, non rediscutée ici.

Hors ligne.
"""

from __future__ import annotations

import pytest

from cohera.detection.modeles import Motif, TypeVerdict
from cohera.detection.symbolique.a5 import (
    a5_normes_divergentes,
    a5_sur_une_clause,
    charger_registre_normes,
)


# --------------------------------------------------------------- le registre des normes


def test_le_registre_reel_declare_les_deux_normes_du_corpus() -> None:
    registre = charger_registre_normes()
    assert set(registre) == {"ISO 45001", "OHSAS 18001"}


def test_ohsas_18001_est_retiree_et_remplacee_par_iso_45001() -> None:
    """La donnée dont dépend I08 : sans elle, « deux référentiels différents » ne devient
    jamais « l'un des deux est obsolète »."""
    ohsas = charger_registre_normes()["OHSAS 18001"]
    assert ohsas.statut == "RETIREE"
    assert ohsas.remplacee_par == "ISO 45001"
    assert ohsas.date_retrait is not None and ohsas.date_retrait.year == 2021


def test_iso_45001_est_en_vigueur() -> None:
    """Cas négatif du registre : citer une norme n'est pas une anomalie."""
    assert charger_registre_normes()["ISO 45001"].statut == "EN_VIGUEUR"


# ------------------------------------------------- les anomalies mono-clause (I09, I10)


def test_i09_renvoi_vers_un_paragraphe_inexistant(frames, identifiants, textes) -> None:
    """D1 §7.5 renvoie au « § 12.3 » alors que D1 ne comporte que 10 sections."""
    verdicts = a5_sur_une_clause(frames[identifiants[("D1", "7.5")]])
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert verdict.motif is Motif.REFERENCE_CASSEE
    assert verdict.clause_b is None, "une anomalie mono-clause n'a pas de seconde clause"
    assert verdict.preuve_a in textes[identifiants[("D1", "7.5")]]


def test_i10_renvoi_inter_documents_non_resolvable(frames, identifiants) -> None:
    """D2 §6.3 renvoie au « § 11.2 de la procédure PR-QSE-04 ». La résolution doit chercher
    dans D1 — et D1 n'a pas de section 11."""
    verdicts = a5_sur_une_clause(frames[identifiants[("D2", "6.3")]])
    assert [v.motif for v in verdicts] == [Motif.REFERENCE_CASSEE]
    assert verdicts[0].preuve_a == "§ 11.2 de la procédure PR-QSE-04"


def test_i08_cote_d2_le_referentiel_cite_est_retire(frames, identifiants) -> None:
    """La moitié mono-clause d'I08 : OHSAS 18001 a été retirée en mars 2021."""
    verdicts = a5_sur_une_clause(frames[identifiants[("D2", "10.1")]])
    assert [v.motif for v in verdicts] == [Motif.REFERENTIEL_OBSOLETE]
    assert "ISO 45001" in verdicts[0].explication
    assert verdicts[0].preuve_a == "OHSAS 18001"


# ----------------------------------------------------------------- les négatifs d'A5


def test_un_renvoi_resolvable_n_est_pas_une_anomalie(frames, identifiants) -> None:
    """D1 §10.1 renvoie au « § 6.4 de la politique POL-SEC-01 » — qui existe. Le détecteur
    doit se taire, sans quoi les 17 autres renvois du corpus deviendraient autant de faux
    positifs."""
    assert a5_sur_une_clause(frames[identifiants[("D1", "10.1")]]) == []


def test_citer_une_norme_en_vigueur_n_est_pas_une_anomalie(frames, identifiants) -> None:
    """D1 §2.1 cite ISO 45001:2018, en vigueur. Cas négatif du registre des normes."""
    assert a5_sur_une_clause(frames[identifiants[("D1", "2.1")]]) == []


def test_aucune_clause_sans_reference_ne_produit_de_verdict(frames, identifiants) -> None:
    """Le cas le plus fréquent, et celui qui garantit qu'A5 ne bruite pas le rapport."""
    assert a5_sur_une_clause(frames[identifiants[("D1", "5.1")]]) == []


def test_a5_sur_tout_le_corpus_ne_trouve_que_quatre_clauses(frames, identifiants) -> None:
    """Passe mono-clause exhaustive sur les 78 clauses — pas un échantillon. C'est la
    mesure de précision d'A5, et elle rend **quatre** clauses, pas trois.

    Les trois attendues : I09 (D1 §7.5, « § 12.3 »), I10 (D2 §6.3, « § 11.2 de la procédure
    PR-QSE-04 ») et l'obsolescence d'I08 (D2 §10.1, OHSAS 18001).

    La quatrième, **mesurée et non prévue par la consigne du J5**, est D1 §10.2 : « Par
    dérogation à la procédure PR-QSE-02 § 3.1 ». PR-QSE-02 est absent du corpus, le renvoi
    est donc littéralement irrésolvable et la règle « renvoi non résolu -> référence
    cassée » d'architecture.md §7.1 s'applique telle quelle.

    Ce n'est **pas un faux positif** : c'est I17 de `label.json` (DEROGATION / ORPHELINE),
    une incohérence réelle — simplement attribuée au détecteur A8, hors périmètre 7 jours.
    A5 l'attrape plus tôt et par un autre chemin. Le constat est juste, son étiquette de
    détecteur diffère de la vérité terrain ; l'écart est consigné au Journal, et
    `corpus/fixtures/` n'est pas touché."""
    trouvees = {
        clause_id
        for clause_id, frame in frames.items()
        if a5_sur_une_clause(frame)
    }
    assert trouvees == {
        identifiants[("D1", "7.5")],    # I09
        identifiants[("D2", "6.3")],    # I10
        identifiants[("D2", "10.1")],   # I08, moitié obsolescence
        identifiants[("D1", "10.2")],   # I17, hors périmètre, attendue d'A8
    }


def test_la_quatrieme_clause_est_bien_i17_et_non_un_faux_positif(
    frames, identifiants, verite
) -> None:
    """Le contrôle qui rend le test précédent honnête : D1 §10.2 est bien listée comme une
    incohérence par `label.json`, et non comme un contre-exemple."""
    from tests.conftest import entree_de

    i17 = entree_de(verite, "I17")
    assert (i17["clause_a"]["doc"], i17["clause_a"]["ref"]) == ("D1", "10.2")
    assert i17["dans_perimetre_7j"] is False
    assert i17["detecteur_attendu"] == "A8"

    verdicts = a5_sur_une_clause(frames[identifiants[("D1", "10.2")]])
    assert [v.motif for v in verdicts] == [Motif.REFERENCE_CASSEE]


# ------------------------------------------------------ la divergence de référentiel


def test_i08_les_deux_documents_n_invoquent_pas_le_meme_referentiel(
    frames, identifiants
) -> None:
    """Le second constat d'I08 : D1 §2.1 se dit conforme à ISO 45001:2018, D2 §10.1 applique
    OHSAS 18001. Le registre dit laquelle est fautive — OHSAS a été remplacée par ISO 45001,
    donc c'est D2 qui doit être mise à jour."""
    verdict = a5_normes_divergentes(
        frames[identifiants[("D1", "2.1")]], frames[identifiants[("D2", "10.1")]]
    )
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert verdict.motif is Motif.REFERENTIEL_DIVERGENT
    assert verdict.ferme
    assert verdict.type_taxonomie == "FACTUEL"
    assert verdict.plus_permissive == "B", "c'est D2 qui cite le référentiel retiré"
    assert verdict.preuve_a == "ISO 45001:2018"
    assert verdict.preuve_b == "OHSAS 18001"


def test_deux_clauses_citant_le_meme_referentiel_ne_divergent_pas(
    frames, identifiants
) -> None:
    """Cas négatif de la divergence : on oppose D1 §2.1 à une COPIE MÉMOIRE d'elle-même.
    Deux documents conformes à la même norme n'ont aucune divergence de référentiel."""
    original = frames[identifiants[("D1", "2.1")]]
    jumelle = original.model_copy(deep=True)
    jumelle.clause_id = "D2::COPIE"

    verdict = a5_normes_divergentes(original, jumelle)
    assert verdict.type is TypeVerdict.AUCUNE


def test_une_clause_sans_norme_ne_peut_pas_diverger(frames, identifiants) -> None:
    verdict = a5_normes_divergentes(
        frames[identifiants[("D1", "2.1")]], frames[identifiants[("D2", "5.1")]]
    )
    assert verdict.type is TypeVerdict.AUCUNE
