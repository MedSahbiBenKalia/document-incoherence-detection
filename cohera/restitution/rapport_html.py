"""Rendu HTML du rapport par gabarit Jinja2.

Cinq rubriques, dans l'ordre où un auditeur les lit (plan §J7, architecture.md §8) :

1. **les constatations** — la synthèse : une ligne par constat, pour embrasser d'un coup
   d'œil ce qui est en cause ;
2. **les incohérences détectées** — le dossier complet de chaque constat : les deux clauses
   *avec leur texte intégral*, les deux citations exactes surlignées à l'endroit où elles
   se trouvent, le type, le détecteur, l'étage, la criticité et l'explication. La synthèse
   se parcourt, ce dossier se lit ;

**Les deux premières rubriques basculent d'un profil de jugement à l'autre**, local et
distant, sans serveur : les deux jeux de résultats sont rendus dans la même page et un seul
est visible à la fois. Le choix du modèle change ce que le système affirme — 18 détections
contre 26 sur ce corpus, 9 incohérences retrouvées contre 11 — et un rapport qui n'en
montrerait qu'une moitié ferait passer un arbitrage pour un fait. Les rubriques 3 à 5
décrivent le corpus et le ciblage, que le profil ne change pas : elles ne basculent pas.

**Tout ce que le système a détecté est affiché, y compris ce qu'il affirme à tort.** Les
détections sont **classées**, jamais masquées : correctes d'abord, erronées ensuite, avec
l'étiquette qui dit laquelle est laquelle. Un rapport d'audit qui cacherait ses faux
positifs serait flatteur et faux — c'est la première chose qu'un lecteur cherche. Cette
étiquette dépend de la vérité terrain : sans annotations, elle disparaît, l'ordre redevient
celui de la criticité, et rien d'autre ne change.
3. **les hypothèses d'alignement** — les alias qui ont permis de rapprocher deux clauses de
   documents différents, avec **les clauses qui emploient chacun des deux termes**. Elles
   sont *révisables* (architecture.md §13, R1) : c'est le premier levier de réglage quand
   la précision dérive, et les taire reviendrait à faire passer une hypothèse pour un fait ;
4. **les zones non couvertes** — ce que le système n'a pas tranché, nommé motif par motif.
   « Un système d'audit qui abstient 8 % est infiniment plus utile qu'un système qui tranche
   à tort 8 % » (§7.4) ; encore faut-il que les 8 % soient visibles. Chaque abstention
   montre les deux clauses en cause, le **verdict brut** que le juge avait rendu, la
   confiance qu'il s'accordait et la raison pour laquelle ce verdict n'a pas été retenu ;
   pour les ``PREUVE_INVENTEE``, la citation fabriquée est montrée sous le texte réel de la
   clause. C'est la seule forme sous laquelle un lecteur peut vérifier que le garde-fou n°1
   travaille au lieu de le croire sur parole — et elle ne coûte aucun appel ;
5. **les dérogations en vigueur** — les conflits apparents qui sont couverts.

**Aucune clause n'est jamais réduite à sa référence.** « D1 §6.5 » ne dit rien à qui n'a
pas les deux procédures ouvertes à côté ; partout où le rapport désigne une clause, il en
montre le texte, et il le montre **entier** — aucune troncature, dans aucune rubrique.

**Page autonome.** Tout le CSS et le seul script sont en ligne, aucune ressource externe :
le fichier doit s'ouvrir depuis une clé USB, en soutenance, sans réseau.

**Les rubriques sont repliées à l'ouverture**, pour que la page s'ouvre sur une vue
d'ensemble — les titres, leurs comptes, et le bandeau de chiffres. Elles reposent sur
``<details>`` natif : elles s'ouvrent sans script, indépendamment les unes des autres (pas
d'attribut ``name``, qui en ferait un accordéon exclusif), et l'impression les rouvre
toutes. **Le repli ne retire rien** : aucune rubrique n'est tronquée, résumée ni écrêtée —
c'est une commodité de lecture, et un rapport d'audit qui cacherait pour de bon une partie
de son contenu ne vaudrait rien.

**La vérité terrain est facultative, et le rapport ne s'y adosse jamais pour exister.**
Passé un fichier d'annotations, le rapport se restreint au périmètre déclaré et affiche la
comparaison attendu / obtenu ; sans lui, il présente tout ce que le système a trouvé et la
comparaison disparaît, sans erreur ni trou. C'est le cas d'usage réel : sur de vraies
procédures, personne ne fournit d'annotations.

**Le critère d'acceptation est un test de lecture**, pas un chiffre : « quelqu'un qui ne
connaît pas le projet lit le rapport et sait, pour chaque ligne, quelles clauses sont en
cause et pourquoi ». D'où le parti pris du gabarit : chaque constatation montre ses deux
preuves littérales à leur place dans le texte, avec le document et le numéro de paragraphe
— jamais un `clause_id` interne, qui ne veut rien dire pour un lecteur.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from pydantic import BaseModel

from cohera.ingestion.normalisation import normaliser
from cohera.restitution.perimetre import Restriction, restreindre
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


def surligner(texte: str | None, preuve: str | None) -> Markup:
    """Le texte **entier** de la clause, la citation marquée à sa place.

    Montrer la citation seule oblige le lecteur à croire sur parole qu'elle vient bien de
    là ; montrer le texte seul lui cache ce que le système a retenu. La marque résout les
    deux d'un coup : on voit la phrase complète *et* la portion qui fonde le verdict.

    La position est cherchée sur les textes **normalisés** — même critère que
    `citation_litterale`, donc une citation acceptée par le garde-fou se retrouve toujours.
    `normaliser` étant strictement conservatrice en longueur, l'indice trouvé sur le texte
    normalisé découpe correctement le texte d'origine, apostrophes typographiques comprises.
    Citation introuvable : le texte est rendu tel quel, jamais amputé.
    """
    texte = texte or ""
    if not preuve:
        return Markup(escape(texte))

    debut = normaliser(texte).find(normaliser(preuve))
    if debut < 0:
        return Markup(escape(texte))
    fin = debut + len(preuve)
    return Markup(
        f"{escape(texte[:debut])}<mark>{escape(texte[debut:fin])}</mark>{escape(texte[fin:])}"
    )


def _environnement() -> Environment:
    environnement = Environment(
        loader=FileSystemLoader(DOSSIER_GABARITS),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environnement.filters["surligner"] = surligner
    return environnement


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


class VueProfil(BaseModel):
    """Un profil de jugement tel que la page l'affiche — bascule comprise.

    La page en embarque **deux**, rendus tous les deux dans le HTML, et n'en montre qu'un
    à la fois. C'est ce qui permet à la bascule de fonctionner dans un fichier autonome,
    sans serveur et sans nouvel appel : les deux jeux de résultats sont déjà là. Sans
    JavaScript, le profil actif reste visible et l'autre reste replié — la page ne ment
    jamais, elle offre simplement moins.
    """

    #: Identifiant DOM, court et stable : « local », « distant ».
    cle: str
    #: Ce que le bouton affiche.
    libelle: str
    #: Le modèle derrière le profil, pour que « local » ne soit pas qu'une étiquette.
    modele: str = ""
    actif: bool = False

    rapport: Rapport
    restriction: Restriction
    bilan: object | None = None

    model_config = {"arbitrary_types_allowed": True}

    @property
    def classements(self):
        return self.restriction.classements

    @property
    def correctes(self):
        return self.restriction.correctes

    @property
    def erronees(self):
        return self.restriction.erronees

    @property
    def juge(self):
        return self.rapport.statistiques_llm


def _nature(rapport: Rapport) -> tuple[str, str]:
    """« local » ou « distant », lu dans le profil que le rapport déclare.

    Le nom du profil est celui de `--llm` (`local`, `groq`, `gemini`…) : tout ce qui n'est
    pas `local` sort du réseau. Le rapport JSON ne transporte pas d'URL de service, et il
    n'a pas à en transporter — le nom suffit à dire de quel côté du réseau on juge.
    """
    statistiques = rapport.statistiques_llm
    if statistiques is None or not statistiques.profil:
        return ("sans-juge", "sans étage C")
    if statistiques.profil == "local":
        return ("local", "local")
    return ("distant", f"distant ({statistiques.profil})")


def vue_profil(
    rapport: Rapport, restriction: Restriction, *, bilan=None, actif: bool = False
) -> VueProfil:
    """Assemble la vue d'un profil. ``rapport`` est le rapport **déjà restreint**."""
    cle, libelle = _nature(rapport)
    modele = rapport.statistiques_llm.modele if rapport.statistiques_llm else ""
    return VueProfil(
        cle=cle, libelle=libelle, modele=modele, actif=actif,
        rapport=rapport, restriction=restriction, bilan=bilan,
    )


def rendre(
    rapport: Rapport,
    *,
    bilan_preuves=None,
    ablation_profils: list[dict] | None = None,
    motif_du_profil: str = "",
    restriction: Restriction | None = None,
    profils: list[VueProfil] | None = None,
) -> str:
    """Rend le rapport en une page HTML autonome.

    ``ablation_profils`` porte le tableau A/B du J6 : le rapport de référence dit lequel des
    deux profils il présente **et** ce que l'autre aurait donné. Présenter un seul profil
    sans son alternative reviendrait à cacher l'arbitrage.

    ``restriction`` est **facultatif**, et c'est tout l'enjeu : renseigné, il apporte le
    périmètre déclaré, le jugement de chaque détection et la comparaison attendu / obtenu ;
    absent, la page se rend à l'identique sur tout ce que le système a trouvé et ces
    éléments-là n'apparaissent tout simplement pas. ``rapport`` doit alors être le rapport
    **déjà restreint** — filtrer la vue, jamais le fichier JSON, qui reste le contrat
    d'évaluation.

    ``profils`` porte la **bascule** : deux jeux de résultats rendus dans la même page, dont
    un seul visible. Omis, la page se rend sur le seul ``rapport``, et la bascule n'apparaît
    pas — une bascule à un cran ne serait pas une bascule.

    Les rubriques 3 à 5 — hypothèses d'alignement, zones non couvertes, dérogations — ne
    basculent pas : elles décrivent le **corpus** et le ciblage, que le profil de jugement
    ne change pas. Les faire basculer suggérerait une variation qui n'existe pas.
    """
    # Sans restriction fournie, on en construit une SANS périmètre : elle ne juge rien et
    # ne filtre rien, mais elle porte les classements — donc les détections. Un
    # `Restriction(rapport=...)` nu aurait une liste de classements vide, et la rubrique 2
    # se rendrait déserte sur un rapport plein.
    restriction = restriction if restriction is not None else restreindre(rapport, None)
    if not profils:
        profils = [vue_profil(rapport, restriction, bilan=bilan_preuves, actif=True)]

    actif = next((p for p in profils if p.actif), profils[0])

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
        restriction=restriction,
        perimetre=restriction.perimetre,
        profils=profils,
        profil_actif=actif,
    )


def ecrire(chemin: Path | str, contenu: str) -> Path:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")
    return chemin
