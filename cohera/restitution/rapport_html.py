"""Rendu HTML du rapport par gabarit Jinja2.

Quatre rubriques, dans l'ordre où un auditeur les lit (plan §J7, architecture.md §8) :

1. **les constatations**, triées par criticité — ce qui est en cause, et pourquoi ;
2. **les hypothèses d'alignement** — les alias qui ont permis de rapprocher deux clauses de
   documents différents. Elles sont *révisables* (architecture.md §13, R1) : c'est le
   premier levier de réglage quand la précision dérive, et les taire reviendrait à faire
   passer une hypothèse pour un fait ;
3. **les zones non couvertes** — ce que le système n'a pas tranché, nommé motif par motif.
   « Un système d'audit qui abstient 8 % est infiniment plus utile qu'un système qui tranche
   à tort 8 % » (§7.4) ; encore faut-il que les 8 % soient visibles. Chaque abstention
   montre le **verdict brut** que le juge avait rendu, la confiance qu'il s'accordait et la
   raison pour laquelle ce verdict n'a pas été retenu ; pour les ``PREUVE_INVENTEE``, la
   citation fabriquée est mise **en regard du texte réel de la clause**. C'est la seule
   forme sous laquelle un lecteur peut vérifier que le garde-fou n°1 travaille au lieu de
   le croire sur parole — et elle ne coûte aucun appel, la réponse étant déjà mémorisée ;
4. **les dérogations en vigueur** — les conflits apparents qui sont couverts.

**Page autonome.** Tout le CSS et le seul script sont en ligne, aucune ressource externe :
le fichier doit s'ouvrir depuis une clé USB, en soutenance, sans réseau.

**Les quatre rubriques sont repliées à l'ouverture**, pour que la page s'ouvre sur une vue
d'ensemble — les titres, leurs comptes, et le bandeau de chiffres. Elles reposent sur
``<details>`` natif : elles s'ouvrent sans script, indépendamment les unes des autres (pas
d'attribut ``name``, qui en ferait un accordéon exclusif), et l'impression les rouvre
toutes. **Le repli ne retire rien** : aucune rubrique n'est tronquée, résumée ni écrêtée —
c'est une commodité de lecture, et un rapport d'audit qui cacherait pour de bon une partie
de son contenu ne vaudrait rien.

**Le critère d'acceptation est un test de lecture**, pas un chiffre : « quelqu'un qui ne
connaît pas le projet lit le rapport et sait, pour chaque ligne, quelles clauses sont en
cause et pourquoi ». D'où le parti pris du gabarit : chaque constatation montre ses deux
preuves littérales côte à côte, avec le document et le numéro de paragraphe — jamais un
`clause_id` interne, qui ne veut rien dire pour un lecteur.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cohera.restitution.rapport_json import Rapport

DOSSIER_GABARITS = Path(__file__).parent / "templates"

#: Libellés lisibles des motifs d'abstention. Le motif brut (`PREUVE_INVENTEE`) est juste
#: pour un développeur et opaque pour un auditeur : la rubrique « zones non couvertes »
#: n'a d'intérêt que si elle se lit.
LIBELLES_MOTIFS = {
    "PREUVE_INVENTEE": "Le juge a cité un extrait qui n'existe pas dans le texte — verdict annulé",
    "ABSTENTION_DU_JUGE": "Le juge s'est déclaré incapable de trancher",
    "NON_VERIFIEE_BUDGET": "Plafond d'appels atteint — la paire n'a pas été soumise",
    "LLM_INJOIGNABLE": "Service de jugement injoignable",
    "EXTRACTION_INCERTAINE": "Réponse non conforme au format attendu, même après réparation",
    "PREUVE_LITTERALE_ABSENTE": "Aucune preuve littérale disponible pour fonder un verdict",
}

#: Pourquoi le verdict brut n'a pas été retenu, motif par motif. Distinct de
#: :data:`LIBELLES_MOTIFS`, qui **titre** un groupe replié : celui-ci se lit *à côté d'un
#: verdict affiché*, et doit donc expliquer ce qui a été écarté et à quel titre. Les deux
#: se ressembleraient s'ils disaient la même chose ; ils ne répondent pas à la même
#: question — « qu'y a-t-il là-dedans ? » contre « pourquoi ce verdict-là est-il tombé ? ».
RAISONS_DU_REJET = {
    "PREUVE_INVENTEE": (
        "La citation produite n'existe pas dans le texte de la clause. Le garde-fou n°1 "
        "annule le verdict au lieu de le rétrograder : un détecteur symbolique ne ment pas "
        "sur sa preuve, un modèle de langue si."
    ),
    "ABSTENTION_DU_JUGE": (
        "Le juge s'est déclaré incapable de trancher, ou n'a pas atteint le plancher de "
        "confiance exigé. L'abstention est une réponse prévue par le contrat, pas un échec."
    ),
    "EXTRACTION_INCERTAINE": (
        "La réponse n'était pas exploitable — format non conforme après une tentative de "
        "réparation, ou verdict hors du vocabulaire fermé. Il n'y a rien à retenir."
    ),
    "NON_VERIFIEE_BUDGET": (
        "Le plafond d'appels était atteint : la paire n'a jamais été soumise. Elle n'est "
        "pas rejetée — elle n'est pas vérifiée, ce qui n'est pas la même chose."
    ),
    "LLM_INJOIGNABLE": (
        "Le service de jugement n'a pas répondu. Une panne se lit dans le rapport, elle "
        "n'avorte pas l'exécution et elle ne se confond pas avec un manque de budget."
    ),
    "PREUVE_LITTERALE_ABSENTE": (
        "Aucune citation n'était disponible pour fonder un verdict — invariant #3 du "
        "projet : rien n'est affirmé sans preuve littérale."
    ),
}

#: Glose des quatre issues du contrat de sortie (architecture.md §7.4). Le mot brut est
#: montré tel quel — c'est ce que le modèle a écrit —, mais « SPECIALISATION » ne dit rien
#: à un auditeur, et le critère d'acceptation du rapport est un test de lecture.
#:
#: Les valeurs sont écrites pour s'enchaîner à « Le juge répondait : » ; une glose
#: rédigée à la troisième personne (« le juge ne sait pas trancher ») produirait la phrase
#: « Le juge concluait que le juge ne sait pas trancher », qui se lit deux fois.
LIBELLES_VERDICTS = {
    "COHERENT": "les deux clauses ne se contredisent pas",
    "INCOHERENCE": "les deux clauses se contredisent",
    "SPECIALISATION": "la clause la plus étroite est aussi la plus stricte, donc compatible",
    "INDECIDABLE": "il ne savait pas trancher",
}


def _environnement() -> Environment:
    return Environment(
        loader=FileSystemLoader(DOSSIER_GABARITS),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _abstentions_par_motif(rapport: Rapport) -> list[dict]:
    """Regroupe les abstentions par motif, du plus fréquent au moins fréquent.

    Vingt-cinq lignes brutes ne se lisent pas ; cinq motifs comptés et expliqués, oui.
    """
    groupes: dict[str, list] = {}
    for abstention in rapport.abstentions:
        groupes.setdefault(abstention.motif, []).append(abstention)

    return [
        {
            "motif": motif,
            "libelle": LIBELLES_MOTIFS.get(motif, motif),
            "raison": RAISONS_DU_REJET.get(motif, ""),
            "nombre": len(paires),
            "paires": paires,
            # Un groupe où le juge a bel et bien répondu se lit autrement qu'un groupe où
            # rien n'est arrivé : le gabarit n'affiche la colonne « verdict écarté » que
            # là où il y a quelque chose à écarter.
            "avec_verdict": any(a.verdict_brut for a in paires),
        }
        for motif, paires in sorted(groupes.items(), key=lambda item: -len(item[1]))
    ]


def _niveaux(rapport: Rapport) -> dict[str, int]:
    return {
        document.id: document.niveau_hierarchique
        for document in rapport.documents
        if document.niveau_hierarchique is not None
    }


def rendre(
    rapport: Rapport,
    *,
    bilan_preuves=None,
    ablation_profils: list[dict] | None = None,
    motif_du_profil: str = "",
) -> str:
    """Rend le rapport en une page HTML autonome.

    ``ablation_profils`` porte le tableau A/B du J6 : le rapport de référence dit lequel des
    deux profils il présente **et** ce que l'autre aurait donné. Présenter un seul profil
    sans son alternative reviendrait à cacher l'arbitrage.
    """
    gabarit = _environnement().get_template("rapport.html.j2")
    return gabarit.render(
        rapport=rapport,
        bilan=bilan_preuves,
        abstentions=_abstentions_par_motif(rapport),
        niveaux=_niveaux(rapport),
        ablation_profils=ablation_profils or [],
        motif_du_profil=motif_du_profil,
        alias_retenus=[h for h in rapport.hypotheses_alias if h.retenu],
        alias_ecartes=[h for h in rapport.hypotheses_alias if not h.retenu],
        libelles_verdicts=LIBELLES_VERDICTS,
    )


def ecrire(chemin: Path | str, contenu: str) -> Path:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")
    return chemin
