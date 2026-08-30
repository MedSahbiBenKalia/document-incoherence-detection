"""restitution/perimetre.py — le rapport se restreint, et il se passe de vérité terrain.

Trois exigences, et la dernière est la plus importante des trois :

1. **Avec un fichier d'annotations**, chaque détection est **jugée** — correcte ou erronée
   — et **aucune n'est masquée** : les correctes passent devant, les erronées suivent. Les
   rubriques de *contexte* (abstentions, hypothèses d'alignement) se restreignent au
   périmètre déclaré, et le rapport dit combien il a mis de côté ; une rubrique qui
   rétrécirait sans le dire laisserait croire que le système n'a rien trouvé d'autre.
2. **Une détection juste hors périmètre reste juste.** Le périmètre décide de ce qu'on
   *attend*, jamais de ce qui est *vrai*.
3. **Sans annotations**, le rapport se génère à l'identique sur tout ce qui a été détecté,
   et les éléments qui dépendent de la vérité terrain disparaissent — sans erreur, sans
   trou. C'est le cas d'usage réel : sur de vraies procédures, personne ne fournit
   d'annotations.

⚠️ **Le filtre porte sur la VUE, jamais sur le fichier.** `rapport.json` reste le contrat
que `cohera evaluer` mesure : l'amputer ferait tomber les faux positifs à zéro parce qu'on
les aurait effacés, pas parce qu'on les aurait corrigés. Un test l'exige explicitement.

Hors ligne : tout se joue sur un `Rapport` construit à la main et un fichier d'annotations
écrit dans `tmp_path`. `corpus/fixtures/` n'est jamais touché.
"""

from __future__ import annotations

import json

import pytest

from cohera.restitution import perimetre as portee
from cohera.restitution import rapport_html
from cohera.restitution.rapport_json import (
    Abstention,
    Constatation,
    CoteClause,
    HypotheseAlias,
    Rapport,
    RefClause,
)

ANNOTATIONS = {
    "incoherences": [
        {
            "id": "I01",
            "clause_a": {"doc": "D1", "ref": "4.2"},
            "clause_b": {"doc": "D2", "ref": "4.2"},
            "dans_perimetre_7j": True,
        },
        {
            "id": "I06",
            "clause_a": {"doc": "D1", "ref": "4.3"},
            "clause_b": {"doc": "D2", "ref": "4.4"},
            "dans_perimetre_7j": False,
        },
        {
            "id": "I12",
            "clause_a": {"doc": "D1", "ref": "6.2"},
            "clause_b": {"doc": "D2", "ref": "6.2"},
            "dans_perimetre_7j": True,
        },
    ],
    "contre_exemples": [
        {
            "id": "N04",
            "clause_a": {"doc": "D1", "ref": "5.2"},
            "clause_b": {"doc": "D2", "ref": "5.2"},
            "dans_perimetre_7j": True,
        }
    ],
}


@pytest.fixture
def annotations(tmp_path):
    chemin = tmp_path / "label.json"
    chemin.write_text(json.dumps(ANNOTATIONS, ensure_ascii=False), encoding="utf-8")
    return chemin


@pytest.fixture
def rapport() -> Rapport:
    """Trois constatations : une du périmètre, une sur un contre-exemple du périmètre —
    donc affichée, et fausse —, une hors périmètre."""
    return Rapport(
        corpus="fixtures",
        constatations=[
            Constatation(
                id="A2-001", type="NUMERIQUE", detecteur="A2", etage="A",
                clause_a=CoteClause(doc="D1", ref="4.2", preuve="48 heures",
                                    texte_source="Signalement sous 48 heures."),
                clause_b=CoteClause(doc="D2", ref="4.2", preuve="5 jours",
                                    texte_source="Signalement sous 5 jours."),
            ),
            Constatation(
                id="C-002", type="CONTENU", detecteur="C", etage="C",
                clause_a=CoteClause(doc="D1", ref="5.2", preuve="une fois par semaine",
                                    texte_source="Controle une fois par semaine."),
                clause_b=CoteClause(doc="D2", ref="5.2", preuve="chaque semaine",
                                    texte_source="Controle chaque semaine."),
            ),
            Constatation(
                id="C-003", type="CONTENU", detecteur="C", etage="C",
                clause_a=CoteClause(doc="D1", ref="9.9", preuve="hors sujet",
                                    texte_source="Une clause hors sujet."),
                clause_b=CoteClause(doc="D2", ref="9.9", preuve="hors sujet",
                                    texte_source="Une autre clause hors sujet."),
            ),
        ],
        abstentions=[
            Abstention(
                clause_a=RefClause(doc="D1", ref="6.2", texte_source="Anomalie signalee."),
                clause_b=RefClause(doc="D2", ref="6.2", texte_source="Ecart remonte."),
                motif="ABSTENTION_DU_JUGE",
            ),
            Abstention(
                clause_a=RefClause(doc="D1", ref="8.8", texte_source="Hors perimetre."),
                clause_b=RefClause(doc="D2", ref="8.8", texte_source="Hors perimetre aussi."),
                motif="ABSTENTION_DU_JUGE",
            ),
        ],
        hypotheses_alias=[
            HypotheseAlias(
                libelle_a="anomalie", libelle_b="ecart", methode="LEXIQUE", retenu=True,
                clauses_a=[RefClause(doc="D1", ref="6.2", texte_source="Anomalie signalee.")],
                clauses_b=[RefClause(doc="D2", ref="6.2", texte_source="Ecart remonte.")],
            ),
            HypotheseAlias(
                libelle_a="chariot", libelle_b="chariots", methode="EXACT", retenu=True,
                clauses_a=[RefClause(doc="D1", ref="8.8", texte_source="Hors perimetre.")],
                clauses_b=[RefClause(doc="D2", ref="8.8", texte_source="Hors perimetre aussi.")],
            ),
        ],
    )


# ═══════════════════════════════════════════════ avec annotations : la restriction


def test_aucune_constatation_n_est_masquee(rapport, annotations) -> None:
    """⭐ Test POSITIF : les **trois** détections sortent, y compris les deux fausses.

    Masquer une détection erronée rendrait le rapport flatteur et faux. Le périmètre
    *classe*, il ne filtre pas — c'est la différence entre un rapport d'audit et une
    vitrine.
    """
    restriction = portee.restreindre(rapport, portee.charger(annotations))

    assert [c.constatation.id for c in restriction.classements] == ["A2-001", "C-002", "C-003"]
    assert [c.identifiant for c in restriction.classements] == ["I01", "N04", ""]


def test_les_correctes_passent_devant_les_erronees(rapport, annotations) -> None:
    """Test POSITIF de l'ordre : correctes d'abord, erronées ensuite, sans réordonner
    l'intérieur de chaque groupe.

    `C-002` tombe sur le contre-exemple `N04` — un piège qui devait rester silencieux —,
    `C-003` sur rien du tout : les deux sont erronées, et pour deux raisons différentes
    que le rapport nomme séparément.
    """
    restriction = portee.restreindre(rapport, portee.charger(annotations))

    assert [c.constatation.id for c in restriction.correctes] == ["A2-001"]
    assert [c.constatation.id for c in restriction.erronees] == ["C-002", "C-003"]
    assert "contre-exemple N04" in restriction.erronees[0].motif
    assert "Aucune correspondance" in restriction.erronees[1].motif


def test_une_detection_juste_hors_perimetre_reste_juste(rapport, annotations) -> None:
    """⭐ Test NÉGATIF du classement, et le piège qu'il faut éviter.

    `I06` est une vraie incohérence **hors** du périmètre chiffré. Une détection qui tombe
    dessus est correcte — la déclarer erronée reviendrait à reprocher au système d'avoir
    trouvé mieux que demandé. C'est pour cela que le périmètre charge **toutes** les
    annotations, pas seulement les siennes.
    """
    trouvee = Constatation(
        id="C-006", type="CONTENU", detecteur="C", etage="C",
        clause_a=CoteClause(doc="D1", ref="4.3", texte_source="Une clause."),
        clause_b=CoteClause(doc="D2", ref="4.4", texte_source="Une autre clause."),
    )
    hors = rapport.model_copy(update={"constatations": [trouvee]})
    restriction = portee.restreindre(hors, portee.charger(annotations))

    assert restriction.correctes[0].identifiant == "I06"
    assert restriction.correctes[0].dans_perimetre is False
    assert "hors du périmètre chiffré" in restriction.correctes[0].motif


def test_les_abstentions_et_les_hypotheses_suivent_le_meme_perimetre(
    rapport, annotations
) -> None:
    """Une hypothèse d'alignement ne porte pas sur une paire mais sur deux termes : elle
    entre dans le périmètre dès qu'une clause du périmètre emploie l'un d'eux."""
    restriction = portee.restreindre(rapport, portee.charger(annotations))

    assert len(restriction.rapport.abstentions) == 1
    assert restriction.abstentions_ecartees == 1
    assert [h.libelle_a for h in restriction.rapport.hypotheses_alias] == ["anomalie"]
    assert restriction.hypotheses_ecartees == 1


def test_une_incoherence_hors_perimetre_n_est_pas_comptee_comme_attendue(
    rapport, annotations
) -> None:
    """Test NÉGATIF : `I06` est déclarée hors périmètre. Ni ses paires ni son identifiant
    ne doivent apparaître — sinon le rapport reprocherait au système de ne pas avoir
    trouvé ce qu'on ne lui demandait pas."""
    restriction = portee.restreindre(rapport, portee.charger(annotations))

    assert restriction.perimetre is not None
    assert restriction.perimetre.incoherences == ["I01", "I12"]
    assert restriction.non_detectees == ["I12"]
    assert restriction.detectees == 1


def test_le_rapport_source_n_est_jamais_ampute(rapport, annotations) -> None:
    """⭐ **Le filtre porte sur la vue, pas sur le fichier.**

    `cohera evaluer` mesure `rapport.json` : si la restriction mutait l'objet, les faux
    positifs disparaîtraient de la mesure au lieu d'être corrigés.
    """
    portee.restreindre(rapport, portee.charger(annotations))

    assert len(rapport.constatations) == 3
    assert len(rapport.abstentions) == 2
    assert len(rapport.hypotheses_alias) == 2


# ═════════════════════════════════════ sans annotations : le cas d'usage réel


def test_sans_annotations_rien_n_est_filtre(rapport) -> None:
    """Test NÉGATIF symétrique : pas de périmètre, pas de filtre, et aucune erreur."""
    restriction = portee.restreindre(rapport, portee.charger(None))

    assert not restriction.actif
    assert restriction.rapport is rapport
    assert restriction.ecartees == 0
    assert restriction.non_detectees == []
    assert len(restriction.classements) == 3
    assert all(c.jugement is None for c in restriction.classements)
    assert restriction.correctes == [] and restriction.erronees == []


def test_un_fichier_d_annotations_absent_vaut_absence_d_annotations(tmp_path) -> None:
    """Un corpus réel n'a pas de `label.json` : c'est le cas nominal, pas une panne."""
    assert portee.charger(tmp_path / "jamais_ecrit.json") is None


def test_le_html_sans_verite_terrain_ne_montre_aucune_comparaison(rapport) -> None:
    """⭐ L'exigence du J9 : les éléments qui dépendent de la vérité terrain
    **disparaissent**, ils ne se rendent pas vides.

    Trois marqueurs, un par élément : le bloc de périmètre, la colonne « Attendu » de la
    synthèse et l'étiquette « attendu : I01 » du dossier.
    """
    restriction = portee.restreindre(rapport, None)
    html = rapport_html.rendre(restriction.rapport, restriction=restriction)

    assert "Attendu et obtenu" not in html
    assert "<th>Vérité terrain</th>" not in html
    assert "détection correcte" not in html and "détection erronée" not in html
    # Et le rapport reste entier : les trois constatations sont là.
    assert html.count('<article class="constat') == 3


def test_le_html_avec_verite_terrain_montre_la_comparaison(rapport, annotations) -> None:
    """Test POSITIF miroir du précédent, pour que l'absence prouve quelque chose."""
    restriction = portee.restreindre(rapport, portee.charger(annotations))
    html = rapport_html.rendre(restriction.rapport, restriction=restriction)

    assert "Attendu et obtenu" in html
    assert "<th>Vérité terrain</th>" in html
    assert "Détections correctes — 1" in html
    assert "Détections erronées — 2" in html
    # Les trois sont là, jugées, aucune masquée.
    assert html.count('<article class="constat') == 3


# ═══════════════════════════════════ la bascule entre profils de jugement


def _rapport_distant(rapport) -> Rapport:
    """Le même corpus jugé par un autre modèle : une détection de plus, et fausse.

    Deux différences suffisent à prouver que la bascule montre bien deux choses : le nombre
    de détections et le profil déclaré.
    """
    from cohera.restitution.rapport_json import StatistiquesLLM

    de_plus = Constatation(
        id="C-009", type="CONTENU", detecteur="C", etage="C",
        clause_a=CoteClause(doc="D1", ref="7.7", preuve="propre au distant",
                            texte_source="Une clause propre au distant."),
        clause_b=CoteClause(doc="D2", ref="7.7", preuve="propre au distant",
                            texte_source="Une autre clause propre au distant."),
    )
    return rapport.model_copy(
        update={
            "constatations": rapport.constatations + [de_plus],
            "statistiques_llm": StatistiquesLLM(profil="groq", modele="llama-3.3-70b"),
        }
    )


@pytest.fixture
def deux_profils(rapport, annotations):
    """Les deux vues, telles que `cohera rapport --comparer` les construit."""
    from cohera.restitution.rapport_html import vue_profil
    from cohera.restitution.rapport_json import StatistiquesLLM

    local = rapport.model_copy(
        update={"statistiques_llm": StatistiquesLLM(profil="local", modele="saiga")}
    )
    perimetre = portee.charger(annotations)
    return [
        vue_profil(*_restreint(local, perimetre), actif=True),
        vue_profil(*_restreint(_rapport_distant(local), perimetre), actif=False),
    ]


def _restreint(presente, perimetre):
    restriction = portee.restreindre(presente, perimetre)
    return restriction.rapport, restriction


def test_la_bascule_embarque_les_deux_jeux_de_resultats(deux_profils) -> None:
    """⭐ Test POSITIF : les deux profils sont **dans la page**, pas rechargés.

    C'est ce qui permet à la bascule de fonctionner dans un fichier autonome, sans serveur
    et sans nouvel appel au modèle.
    """
    html = rapport_html.rendre(
        deux_profils[0].rapport, restriction=deux_profils[0].restriction, profils=deux_profils
    )

    assert 'data-cible="local"' in html and 'data-cible="distant"' in html
    # Le contenu propre au profil INACTIF est présent lui aussi — c'est tout l'intérêt.
    # La citation y est surlignée à sa place, d'où la marque au milieu de la phrase.
    assert "Une clause <mark>propre au distant</mark>." in html
    assert html.count('<article class="constat') == 3 + 4


def test_un_seul_profil_est_visible_a_la_fois(deux_profils) -> None:
    """⭐ Test NÉGATIF, et le défaut le plus probable : deux profils affichés ensemble.

    Sans JavaScript la page doit rester juste — le profil retenu visible, l'autre replié.
    C'est l'attribut `hidden`, posé au rendu, qui l'assure ; le script ne fait que le
    déplacer d'un bloc à l'autre.
    """
    html = rapport_html.rendre(
        deux_profils[0].rapport, restriction=deux_profils[0].restriction, profils=deux_profils
    )

    assert 'data-profil="distant" hidden' in html
    assert 'data-profil="local" hidden' not in html
    assert html.count('data-profil="local"') == html.count('data-profil="distant"')


def test_les_chiffres_de_l_entete_suivent_le_profil(deux_profils) -> None:
    """Rappel, détections correctes et erronées sont rendus **par profil**.

    Un en-tête qui ne bougerait pas ferait lire les chiffres du local sous les résultats du
    distant — l'erreur exacte que la bascule doit rendre impossible.
    """
    local, distant = deux_profils

    assert (len(local.correctes), len(local.erronees)) == (1, 2)
    assert (len(distant.correctes), len(distant.erronees)) == (1, 3)
    assert local.cle == "local" and distant.cle == "distant"
    assert local.libelle == "local" and distant.libelle == "distant (groq)"


def test_sans_second_profil_la_bascule_n_apparait_pas(rapport, annotations) -> None:
    """Test NÉGATIF : une bascule à un seul cran ne serait pas une bascule."""
    restriction = portee.restreindre(rapport, portee.charger(annotations))
    html = rapport_html.rendre(restriction.rapport, restriction=restriction)

    assert 'class="bascule"' not in html
    assert 'data-cible=' not in html


def test_les_deux_profils_ne_partagent_aucun_identifiant(deux_profils) -> None:
    """Les deux jeux portent les mêmes `id` de constatation : sans préfixe de profil, les
    ancres de la synthèse pointeraient sur la carte de l'autre profil."""
    import re as _re

    html = rapport_html.rendre(
        deux_profils[0].rapport, restriction=deux_profils[0].restriction, profils=deux_profils
    )
    identifiants = _re.findall(r'<article class="constat[^"]*"\s+id="([^"]+)"', html)

    assert len(identifiants) == len(set(identifiants))
    assert "local-A2-001" in identifiants and "distant-A2-001" in identifiants
