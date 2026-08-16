"""detection/symbolique/a2.py — divergence de valeurs, sous réserve des portées.

Sur les **vraies** Clause Frames du corpus, hors ligne : A2 est une comparaison d'entiers
et une lecture de configuration, rien qui exige un serveur. Le nombre d'objets canoniques
partagés est en revanche calculé pour de bon, depuis le vocabulaire et le pont du J3 : il
porte la garde de précision de la journée et le simuler ne prouverait rien.

⚠️ `corpus/fixtures/` est en lecture seule. Le test inverse (72 h) et la grandeur injectée
de N04 travaillent sur des `model_copy(deep=True)` en mémoire — les fichiers ne sont
jamais touchés.
"""

from __future__ import annotations

import pytest

from cohera.detection.modeles import Motif, TypeVerdict
from cohera.detection.objets import objets_partages
from cohera.detection.symbolique.a2 import a2
from cohera.extraction.frames import (
    Dimension,
    Grandeur,
    Monotonie,
    Operateur,
    StatutGrandeur,
)


@pytest.fixture(scope="module")
def juger(frames, identifiants, algebre, vocabulaire, pont):
    """Appelle A2 sur une paire du corpus, avec le VRAI compte d'objets partagés.

    ``partages`` permet de le forcer, mais seuls les tests du garde-fou lui-même s'en
    servent : partout ailleurs c'est la mesure réelle qui décide, sans quoi les tests
    prouveraient seulement que le code fait ce qu'on lui a soufflé.
    """
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
        return a2(a, b, algebre, objets_partages=mesures)

    return _juger


# ------------------------------------------------------------------ les positifs


@pytest.mark.parametrize(
    "cas, a, b, permissive",
    [
        # I01 — 48 h contre 5 jours ouvrés. delai est PLUS_PETIT : D1 est la plus stricte.
        ("I01", ("D1", "4.2"), ("D2", "4.2"), "B"),
        # I02 — trimestriel contre deux fois par an.
        ("I02", ("D1", "5.1"), ("D2", "5.1"), "B"),
        # I13 — harnais à plus de 3 m contre plus de 2 m. seuil_declenchement est
        # PLUS_PETIT depuis la correction du J5 : D1 est la clause fautive, comme
        # l'annonce `label.json` (`clause_fautive: "D1 (niveau 3, plus permissif...)"`).
        ("I13", ("D1", "7.1"), ("D2", "7.1"), "A"),
        # I14 — 85 dB(A) contre 80 dB(A). seuil_exposition est PLUS_PETIT.
        ("I14", ("D1", "5.5"), ("D2", "5.5"), "A"),
        # I15 — recyclage tous les 3 ans contre tous les 2 ans.
        ("I15", ("D1", "8.2"), ("D2", "8.2"), "A"),
    ],
)
def test_les_divergences_numeriques_sont_detectees(
    juger, cas: str, a, b, permissive: str
) -> None:
    """Les cinq divergences de valeurs qu'A2 conclut fermement sur ce corpus.

    Le test contrôle la DIRECTION (`plus_permissive`), pas seulement la détection : c'est
    elle qui exerce la lecture de la monotonie, et c'est elle qui dit à l'auditeur quelle
    clause est fautive."""
    verdict = juger(*a, *b)
    assert verdict.type is TypeVerdict.CONTRADICTION, cas
    assert verdict.ferme, cas
    assert verdict.motif is Motif.VALEURS_DIVERGENTES, cas
    assert verdict.plus_permissive == permissive, cas


def test_i13_et_i03_lisent_des_monotonies_opposees(juger) -> None:
    """Le cœur du critère « monotonies opposées » du plan §J5.

    ⚠️ **Écart au plan, mesuré et assumé.** Le plan oppose `seuil_declenchement` et
    `seuil_exposition` ; en réalité ces deux rôles se durcissent dans le MÊME sens (un
    seuil plus bas déclenche la protection plus tôt), et c'était la valeur `PLUS_GRAND`
    de `seuil_declenchement` — corrigée au J5 — qui donnait l'illusion d'une opposition.
    La vraie opposition du corpus est `seuil_declenchement`/`validite_habilitation`
    (PLUS_PETIT) contre `duree_conservation` (PLUS_GRAND).

    Ici : D1 porte la plus GRANDE valeur dans I13 (3 m contre 2 m) et la plus PETITE dans
    I03 (3 ans contre 5 ans), et sort pourtant « plus permissive » dans les deux cas.
    Aucune comparaison codée en dur ne peut produire ce résultat.

    La direction est lue sur I03 même si son verdict n'est pas ferme : la monotonie est
    appliquée avant les gardes de fermeté, et c'est bien elle qu'on teste ici."""
    i13 = juger("D1", "7.1", "D2", "7.1")
    i03 = juger("D1", "9.2", "D2", "9.1")
    assert i13.plus_permissive == i03.plus_permissive == "A"

    assert "3 mètres" in i13.preuve_a and "2 mètres" in i13.preuve_b
    assert "3 ans" in i03.preuve_a and "5 ans" in i03.preuve_b


def test_i03_escalade_faute_d_objets_partages(juger) -> None:
    """**Mesuré, et conforme à la vérité terrain.** D1 §9.2 (« Le registre de contrôle des
    EPI est archivé pendant 3 ans », après autonomisation de l'anaphore) et D2 §9.1 (« Les
    enregistrements de vérification sont conservés pendant 5 ans ») ne partagent qu'UN objet
    canonique, le générique « contrôle ». Sous le seuil de deux.

    Ce n'est pas une perte : `label.json` place I03 à `etage_attendu: "C"` et note qu'elle
    dépend d'un arbitrage LLM sur `archiver ~ conserver`, mesuré à 0,613 au J3 — sous le
    budget de la zone grise. L'escalade est donc exactement le comportement attendu.

    Une paire de plus dans ce cas — D1 §5.3 ↔ D2 §5.1, qui ne partage aussi que « contrôle »
    — est un faux positif que ce même seuil écarte. Aucun seuil ne sépare les deux : c'est
    pourquoi il vaut 2 et non 1."""
    verdict = juger("D1", "9.2", "D2", "9.1")
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert not verdict.ferme
    assert verdict.motif is Motif.OBJETS_SANS_RECOUVREMENT


def test_le_verdict_porte_une_preuve_litterale(juger, textes, identifiants) -> None:
    """Invariant #3 : `preuve_a` et `preuve_b` sont des sous-chaînes exactes de
    `texte_source`, pas des reformulations."""
    verdict = juger("D1", "4.2", "D2", "4.2")
    assert verdict.preuve_a in textes[identifiants[("D1", "4.2")]]
    assert verdict.preuve_b in textes[identifiants[("D2", "4.2")]]


# ------------------------------------------- N01 et le TEST INVERSE, exigé par le plan


def test_n01_est_une_specialisation_et_non_une_constatation(juger) -> None:
    """**Le critère n°1 du J5.** D1 §4.2 valide sous 48 h sans condition ; D2 §4.6 valide
    sous 24 h « en cas d'accident avec arrêt de travail ». Même clé, valeurs différentes,
    mais la portée de D2 est INCLUSE dans celle de D1 et la contrainte y est plus stricte
    (24 h < 48 h pour un délai). C'est une déclinaison légitime."""
    verdict = juger("D1", "4.2", "D2", "4.6")
    assert verdict.type is TypeVerdict.SPECIALISATION
    assert verdict.motif is Motif.INCLUSION_PLUS_STRICTE
    assert verdict.relation_portees == "INCLUSION_B_DANS_A"
    assert not verdict.est_constatation


def test_n01_devient_une_contradiction_si_la_valeur_restreinte_est_plus_permissive(
    juger, frames, identifiants
) -> None:
    """⭐ **LE TEST INVERSE, obligatoire.**

    On remplace « 24 heures » par « 72 heures » dans une COPIE MÉMOIRE de la frame de
    D2 §4.6 — `corpus/fixtures/` n'est pas touché. Le sous-cas devient alors plus
    PERMISSIF que la règle générale : autoriser 72 h pour un accident avec arrêt de travail
    quand le cas général exige 48 h.

    Sans ce test, on ne saurait pas si le détecteur applique la monotonie ou s'il se
    contente de dire « il y a inclusion, donc c'est compatible » — les deux hypothèses
    rendent N01 vert, une seule est correcte."""
    original = frames[identifiants[("D2", "4.6")]]
    assert original.quantites[0].valeur_si == 86400, "la fixture a changé sous le test"

    plus_permissif = original.model_copy(deep=True)
    plus_permissif.quantites[0].valeur_si = 72 * 3600
    plus_permissif.quantites[0].surface = "24 heures"  # la preuve reste littérale

    verdict = juger("D1", "4.2", None, None, frame_b=plus_permissif)
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert verdict.motif is Motif.INCLUSION_PLUS_PERMISSIVE
    assert verdict.relation_portees == "INCLUSION_B_DANS_A"
    assert verdict.plus_permissive == "B"

    # Et la fixture partagée n'a pas bougé.
    assert frames[identifiants[("D2", "4.6")]].quantites[0].valeur_si == 86400


# ------------------------------------------------------------------ les négatifs


def test_n06_douze_mois_egalent_une_annee(juger) -> None:
    """CAP05 : « tous les 12 mois » et « vérification annuelle » normalisent tous deux vers
    31 536 000 s. Valeurs égales, donc rien à dire — et le motif le dit."""
    verdict = juger("D1", "5.3", "D2", "5.3")
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.VALEURS_EGALES


def test_n04_est_rejete_par_la_disjonction_des_portees(
    juger, frames, identifiants
) -> None:
    """**Mesuré au J5, et c'est ce qui rend ce test probant.** D1 §5.2 (« avant chaque
    prise de poste ») ne porte AUCUNE grandeur : « prise de poste » n'est pas une
    périodicité du lexique. A2 s'y tairait donc faute de couple `(dimension, role)` commun,
    et la branche DISJOINTE ne serait jamais exécutée — le test passerait au vert pour la
    mauvaise raison.

    On injecte donc, dans une COPIE MÉMOIRE, une périodicité différente de celle de D2 §5.2
    (quotidienne contre hebdomadaire). A2 doit rester muet, et **pour le bon motif** :
    « zone A » et « zone de stockage » sont deux enfants distincts du site de Radès."""
    sans_grandeur = frames[identifiants[("D1", "5.2")]]
    assert sans_grandeur.quantites == [], "D1 §5.2 porte désormais une grandeur : revoir ce test"

    avec_grandeur = sans_grandeur.model_copy(deep=True)
    avec_grandeur.quantites = [
        Grandeur(
            role="periodicite", dimension=Dimension.TEMPS_PERIODE, valeur=1, unite="jour",
            valeur_si=86400, operateur=Operateur.EGAL, surface="avant chaque prise de poste",
            monotonie=Monotonie.PLUS_PETIT, statut=StatutGrandeur.NORMAL,
        )
    ]

    verdict = juger(None, None, "D2", "5.2", frame_a=avec_grandeur)
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.PORTEES_DISJOINTES


def test_n04_sans_grandeur_injectee_se_tait_pour_une_autre_raison(juger) -> None:
    """Le pendant honnête du test précédent : tel quel, le corpus fait taire A2 sur N04
    pour absence de grandeur comparable, pas pour disjonction. Les deux gardes tiennent,
    et on sait laquelle agit."""
    verdict = juger("D1", "5.2", "D2", "5.2")
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.PAS_DE_GRANDEUR_COMPARABLE


def test_n08_escalade_faute_d_objets_partages(juger, vocabulaire, pont, identifiants) -> None:
    """**Le garde-fou de précision du J5, côté négatif — et le contre-exemple N08.**

    D1 §5.6 (commande de remplacement d'un EPI défectueux, 5 jours ouvrés) et D2 §4.5
    (compte rendu du comité sécurité, 10 jours ouvrés) : même rôle `delai`, portées
    identiques, valeurs différentes. Un A2 nu crierait au conflit. Les deux clauses ne
    partagent **aucun** objet canonique : le ciblage a bien fait de les apparier — c'est son
    rôle de filet — mais rien n'atteste qu'elles parlent de la même chose."""
    a, b = identifiants[("D1", "5.6")], identifiants[("D2", "4.5")]
    assert objets_partages(a, b, vocabulaire, pont) == 0

    verdict = juger("D1", "5.6", "D2", "4.5")
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert not verdict.ferme
    assert verdict.motif is Motif.OBJETS_SANS_RECOUVREMENT
    assert not verdict.est_constatation


def test_le_garde_fou_des_objets_n_est_pas_un_rejet_deguise(juger) -> None:
    """Cas négatif du garde-fou : la même paire, créditée de deux objets partagés, redevient
    ferme. Ce qui prouve que la garde porte bien sur le recouvrement des objets, et non sur
    une autre propriété de la paire qu'on aurait attrapée par accident."""
    verdict = juger("D1", "5.6", "D2", "4.5", partages=2)
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert verdict.ferme


def test_i12_escalade_elle_aussi_faute_d_objets_partages(
    juger, vocabulaire, pont, identifiants
) -> None:
    """⚠️ **CRITÈRE ROUGE DU J5, et c'est le prix du garde-fou ci-dessus.**

    `label.json` annonce I12 à l'étage A, détecteur A2. D1 §6.2 (« Toute anomalie détectée
    est signalée au chef d'atelier sous 24 heures ») et D2 §6.2 (« Les écarts constatés sont
    remontés à la hiérarchie dans la semaine ») ne partagent **aucun** objet canonique —
    `anomalie`/`écart` et `chef d'atelier`/`hiérarchie` sont sous le seuil d'alias depuis le
    J3, volontairement, pour qu'I12 reste le cas pilote du canal 5.

    Elle a donc exactement le profil de N08, qui doit être rejeté : mêmes rôles, mêmes
    portées identiques, zéro objet partagé de part et d'autre. **Aucun séparateur symbolique
    ne les distingue** — mesuré, l'objet canonique de la clé de comparaison n'y parvient pas
    non plus, et il échoue en prime sur I02, I13, I14, I15 et N01.

    Il fallait choisir entre quatre faux positifs plus N08, et l'escalade d'I12. La précision
    à 1,00 et le zéro faux positif sont les critères durs de la journée : I12 escalade, et
    sera reprise à l'étage B ou C au J6.

    Ce test fige le comportement réel. La divergence d'avec `label.json` est signalée, pas
    corrigée : `corpus/fixtures/` n'est pas touché."""
    a, b = identifiants[("D1", "6.2")], identifiants[("D2", "6.2")]
    assert objets_partages(a, b, vocabulaire, pont) == 0

    verdict = juger("D1", "6.2", "D2", "6.2")
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert not verdict.ferme
    assert verdict.motif is Motif.OBJETS_SANS_RECOUVREMENT


def test_une_grandeur_imprecise_n_autorise_pas_un_verdict_ferme(juger) -> None:
    """CAP04 : « dans la semaine » produit une grandeur au statut IMPRECIS. Même créditée
    d'un recouvrement d'objets suffisant, elle ne peut pas fonder une affirmation ferme —
    604 800 s est une valeur nominale, pas une mesure.

    Second garde-fou, indépendant du premier : I12 escalade donc pour deux raisons, et le
    critère rouge tiendrait même si le recouvrement d'objets s'améliorait."""
    verdict = juger("D1", "6.2", "D2", "6.2", partages=2)
    assert verdict.type is TypeVerdict.CONTRADICTION
    assert not verdict.ferme
    assert verdict.motif is Motif.GRANDEUR_IMPRECISE


def test_deux_clauses_sans_grandeur_commune_ne_disent_rien(juger) -> None:
    """I04 : deux modalités opposées, aucune grandeur. C'est A1 qui traite, pas A2."""
    verdict = juger("D1", "7.4", "D2", "7.4")
    assert verdict.type is TypeVerdict.AUCUNE
    assert verdict.motif is Motif.PAS_DE_GRANDEUR_COMPARABLE
