"""restitution/rapport_html.py — le repli des rubriques, et ce que montre une abstention.

Deux exigences y sont vérifiées, et la première est la plus facile à casser par accident :

1. **Le repli ne retire rien.** Les cinq rubriques s'ouvrent repliées pour que la page
   commence sur une vue d'ensemble, mais leur contenu est intégralement présent dans le
   document — rien n'est tronqué, résumé ni écrêté. Un rapport d'audit qui masquerait pour
   de bon une partie de ses lignes ne vaudrait rien, et le seul moyen de s'en assurer est
   de chercher chaque ligne dans le HTML rendu.
2. **Une abstention dit ce qui a été écarté.** Le verdict brut, la confiance que le juge
   s'accordait, la raison du rejet — et, pour une preuve inventée, la citation fabriquée,
   lisible sous le **texte intégral** des deux clauses que la carte affiche.
3. **Aucune clause n'est réduite à sa référence.** Partout — constatations, zones non
   couvertes, hypothèses d'alignement, dérogations — le texte de la clause accompagne son
   libellé. « D1 §6.5 » ne dit rien à qui n'a pas les procédures sous les yeux.

Aucun test ici ne touche le réseau : le rendu est une fonction pure du :class:`Rapport`.

⚠️ **Les chaînes attendues sont écrites telles qu'elles sortent du gabarit**, et les deux
cas ne se ressemblent pas : le texte **littéral** du gabarit (les titres de rubrique) passe
tel quel, tandis qu'une valeur **interpolée** est échappée par Jinja — l'apostrophe y
devient ``&#39;``. Une assertion écrite à l'envers échoue sur un rapport parfaitement
correct ; les données de test évitent donc l'apostrophe.
"""

from __future__ import annotations

import re

import pytest

from cohera.restitution import rapport_html
from cohera.restitution.rapport_json import (
    Abstention,
    CitationInvalide,
    Constatation,
    CoteClause,
    Derogation,
    HypotheseAlias,
    Rapport,
    RefClause,
)

TEXTE_REEL = "Les rapports internes sont conserves pendant trois ans."
CITATION_FABRIQUEE = "conserves pendant cinq ans"
#: Le texte d'une clause qu'aucune preuve ne cite : il ne peut apparaître dans le HTML que
#: parce que la rubrique montre le CONTENU de la clause, jamais par le détour d'une preuve.
TEXTE_AUTRE = "Le registre des ecarts est revu en revue de direction."


def _abstention_preuve_inventee() -> Abstention:
    """Le cas que la rubrique doit rendre lisible : le juge a inventé sa citation."""
    return Abstention(
        clause_a=RefClause(doc="D1", ref="9.2", clause_id="D1::S9::C02",
                           texte_source=TEXTE_REEL),
        clause_b=RefClause(doc="D2", ref="9.1", clause_id="D2::S9::C01",
                           texte_source=TEXTE_REEL),
        motif="PREUVE_INVENTEE",
        explication="preuve absente du texte source, verdict annule (COHERENT)",
        verdict_brut="COHERENT",
        confiance=0.95,
        preuve_invalide=[
            CitationInvalide(cote="A", clause="D1 §9.2", citation=CITATION_FABRIQUEE,
                             litterale=False, texte_source=TEXTE_REEL),
            CitationInvalide(cote="B", clause="D2 §9.1", citation="trois ans",
                             litterale=True, texte_source=TEXTE_REEL),
        ],
    )


@pytest.fixture
def rapport() -> Rapport:
    """Un rapport dont les **cinq** rubriques sont peuplées.

    Chaque rubrique porte une chaîne qui ne se trouve nulle part ailleurs dans le gabarit :
    c'est ce qui permet d'affirmer que la rubrique est présente, et non qu'un mot voisin
    l'est.
    """
    return Rapport(
        corpus="fixtures",
        constatations=[
            Constatation(
                id="A2-001", type="NUMERIQUE", detecteur="A2", etage="A", gravite="CRITIQUE",
                clause_a=CoteClause(doc="D1", ref="5.1", preuve="sous 48 heures",
                                    texte_source="Signalement sous 48 heures."),
                clause_b=CoteClause(doc="D2", ref="5.1", preuve="sous 5 jours",
                                    texte_source="Signalement sous 5 jours."),
                explication="Deux delais incompatibles pour le meme signalement.",
            )
        ],
        hypotheses_alias=[
            HypotheseAlias(libelle_a="Responsable QSE", libelle_b="Referent securite",
                           methode="LEXIQUE", score_vectoriel=0.546, retenu=True,
                           justification="Alias pose par le lexique metier.")
        ],
        abstentions=[
            _abstention_preuve_inventee(),
            Abstention(
                clause_a=RefClause(doc="D1", ref="6.5", texte_source=TEXTE_AUTRE),
                clause_b=RefClause(doc="D2", ref="6.5", texte_source=TEXTE_AUTRE),
                motif="ABSTENTION_DU_JUGE", explication="confiance 0.30 sous le plancher (0.70)",
                verdict_brut="INCOHERENCE", confiance=0.30,
            ),
            Abstention(
                clause_a=RefClause(doc="D1", ref="4.1"), clause_b=RefClause(doc="D2", ref="4.2"),
                motif="NON_VERIFIEE_BUDGET",
                explication="plafond de 200 appels reseau atteint",
            ),
        ],
        derogations_en_vigueur=[
            Derogation(id="DER-01", clause_a=CoteClause(doc="D1", ref="10.1"),
                       cible="PR-QSE-02 § 6.4", justification="Chantier pilote de Nantes",
                       approbateur="Direction QSE")
        ],
    )


@pytest.fixture
def html(rapport) -> str:
    return rapport_html.rendre(rapport)


# ═══════════════════════════════════════════════ le repli, et ce qu'il ne retire pas


def test_les_cinq_rubriques_sont_repliables(html) -> None:
    """Chaque rubrique est un `<details>` : elle s'ouvre au clic, sans script."""
    assert html.count('<details class="rubrique">') == 5


def test_la_page_s_ouvre_sur_une_vue_d_ensemble(html) -> None:
    """Aucune rubrique n'est ouverte au chargement — sinon la vue d'ensemble n'en est pas une.

    Le marqueur cherché est l'attribut `open` sur les rubriques : c'est lui, et lui seul,
    qui déciderait qu'une section s'affiche dépliée.
    """
    assert not re.search(r'<details class="rubrique"[^>]*\bopen\b', html)


def test_les_titres_portent_leur_compte(html) -> None:
    """La vue d'ensemble doit se lire seule : un titre sans son compte ne dit rien.

    Les titres sont du texte littéral du gabarit, donc **non échappés** — à la différence
    des valeurs interpolées, où Jinja transforme l'apostrophe en ``&#39;``.
    """
    assert "1. Constatations" in html and "— 1 détection" in html
    assert "2. Incohérences détectées" in html and "— 1, dossier complet" in html
    assert "3. Hypothèses d'alignement" in html
    assert "4. Zones non couvertes" in html and "— 3 paires" in html
    assert "5. Dérogations en vigueur" in html


def test_les_rubriques_ne_forment_pas_un_accordeon_exclusif(html) -> None:
    """⭐ Test NÉGATIF, et le piège exact du `<details>` moderne.

    Un attribut `name` partagé transforme un groupe de `<details>` en accordéon : ouvrir
    une rubrique en referme une autre. La consigne demande l'inverse — les trois rubriques
    doivent pouvoir être ouvertes **simultanément**. Sans ce test, la régression serait
    invisible dans le HTML rendu et ne se verrait qu'au clic.
    """
    for balise in re.findall(r"<details[^>]*>", html):
        assert "name=" not in balise


def test_le_repli_ne_retire_rien_du_contenu(html) -> None:
    """⭐ **L'exigence centrale** : replié n'est pas tronqué.

    Chaque rubrique est cherchée par une chaîne qui lui est propre. Si une future
    « amélioration » remplaçait un contenu replié par un extrait, un compteur ou un
    « voir plus », ce test tomberait — c'est le seul garde-fou contre la perte
    d'information déguisée en confort de lecture.
    """
    attendus = [
        "sous 48 heures",                       # rubrique 2 : la preuve littérale
        # Le texte INTÉGRAL de la clause, la preuve marquée à sa place : c'est la forme
        # exacte, marque comprise, qui atteste qu'on n'affiche ni la citation seule ni le
        # texte seul. Une régression du surlignage se verrait ici avant de se voir à l'œil.
        "Signalement <mark>sous 48 heures</mark>.",
        "Deux delais incompatibles",            # rubrique 2 : l'explication complète
        "Referent securite",                    # rubrique 3 : l'hypothèse d'alignement
        "Alias pose par le lexique metier.",    # rubrique 3 : sa justification
        CITATION_FABRIQUEE,                     # rubrique 4 : la citation inventée
        TEXTE_REEL,                             # rubrique 4 : le texte réel de la clause
        TEXTE_AUTRE,                            # rubrique 4 : une clause qu'aucune preuve ne cite
        "Chantier pilote de Nantes",            # rubrique 5 : la justification
    ]
    for attendu in attendus:
        assert attendu in html, attendu


def test_l_impression_rouvre_tout(html) -> None:
    """Une rubrique repliée sur le papier serait une perte, pas un confort."""
    assert "beforeprint" in html and "afterprint" in html


def test_la_page_reste_autonome(html) -> None:
    """Test NÉGATIF du J7, reconduit : aucune ressource externe, le fichier s'ouvre hors ligne.

    Le script ajouté pour le repli est en ligne comme le CSS ; il ne doit introduire ni
    `src`, ni ressource distante, ni appel réseau.
    """
    assert "http://" not in html and "https://" not in html
    assert "<script src" not in html and "fetch(" not in html


# ══════════════════════════════════════ ce qu'une abstention montre désormais


def test_l_abstention_montre_le_verdict_brut_et_sa_confiance(html) -> None:
    """Test POSITIF : le verdict écarté est nommé, chiffré, et dit écarté."""
    assert "verdict rendu : COHERENT" in html
    assert "confiance 0.95" in html
    assert "non retenu" in html


def test_le_verdict_brut_est_glose_pour_un_lecteur(html) -> None:
    """« SPECIALISATION » ne dit rien à un auditeur : le critère du rapport est un test de
    lecture, pas un vocabulaire interne.

    La glose s'enchaîne à « Le juge répondait : ». C'est ce qui interdit de la rédiger à la
    troisième personne — « le juge ne sait pas trancher » donnerait « Le juge répondait :
    le juge ne sait pas trancher », qui se lit deux fois.
    """
    assert "Le juge r&#233;pondait : les deux clauses ne se contredisent pas." in html         or "Le juge répondait : les deux clauses ne se contredisent pas." in html
    assert "Le juge r&#233;pondait : les deux clauses se contredisent." in html         or "Le juge répondait : les deux clauses se contredisent." in html
    for glose in rapport_html.LIBELLES_VERDICTS.values():
        assert not glose.startswith("le juge"), glose


def test_le_groupe_porte_la_raison_du_rejet(html) -> None:
    """Le motif brut est juste pour un développeur et opaque pour un auditeur : la rubrique
    dit pourquoi le verdict n'a pas été retenu, motif par motif."""
    assert "annule le verdict au lieu de le r&#233;trograder" in html \
        or "annule le verdict au lieu de le rétrograder" in html
    assert "plafond d&#39;appels" in html or "plafond d'appels" in html


def test_la_preuve_inventee_est_montree_en_regard_du_texte_reel(html) -> None:
    """⭐ **La preuve visuelle que le garde-fou travaille.**

    Les deux moitiés doivent être là, et étiquetées : la citation fabriquée, marquée
    introuvable, et le texte réel contre lequel la vérification a échoué. L'une sans
    l'autre ne démontre rien.
    """
    assert CITATION_FABRIQUEE in html
    assert TEXTE_REEL in html
    assert "citation introuvable dans la clause" in html
    assert "Texte de la clause" in html


def test_le_cote_correctement_cite_est_montre_aussi(html) -> None:
    """La moitié JUSTE compte autant que la moitié fausse.

    Sans elle, le lecteur voit une citation absente sans savoir si le modèle savait citer
    du tout — or c'est précisément ce qu'il doit pouvoir juger.
    """
    assert "citation litt&#233;rale, v&#233;rifi&#233;e" in html \
        or "citation littérale, vérifiée" in html


def test_une_abstention_sans_reponse_ne_pretend_pas_en_avoir_une(html) -> None:
    """⭐ Test NÉGATIF : « pas de réponse » et « une réponse refusée » ne se confondent pas.

    La paire non soumise faute de budget n'a produit aucun verdict. Afficher « verdict
    rendu : » suivi d'un blanc, ou une confiance de 0,00 tombée de nulle part, ferait
    croire à un jugement qui n'a jamais eu lieu.
    """
    assert "aucun verdict exploitable" in html
    # Deux abstentions sur trois portent un verdict : la troisième ne doit pas en inventer.
    assert html.count("verdict rendu :") == 2


def test_seules_les_preuves_inventees_portent_une_citation_ecartee(html) -> None:
    """Test NÉGATIF : une citation parfaitement littérale, écartée pour manque de confiance,
    n'est pas une « preuve invalide ». La ranger sous ce nom serait un contresens.

    Une seule abstention du rapport porte des citations, et elle en porte deux — une par
    côté. Quatre blocs signaleraient qu'on en a fabriqué pour les autres motifs.
    """
    assert len(re.findall(r'class="citation (?:vraie|faux)"', html)) == 2


def test_un_rapport_vide_se_rend_sans_rubrique_trompeuse() -> None:
    """Test NÉGATIF du cas limite : `Rapport()` est valide, et son rendu doit le dire."""
    html = rapport_html.rendre(Rapport())

    assert html.count('<details class="rubrique">') == 5
    assert "Aucune incoh&#233;rence constat&#233;e sur ce corpus." in html \
        or "Aucune incohérence constatée sur ce corpus." in html
    assert "Toutes les paires examin&#233;es ont re&#231;u un verdict." in html \
        or "Toutes les paires examinées ont reçu un verdict." in html
