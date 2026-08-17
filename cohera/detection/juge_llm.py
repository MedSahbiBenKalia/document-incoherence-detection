"""Étage C — le LLM juge, conditionné par le graphe.

Invariant : aucun verdict sans preuve littérale. `preuve_a` et `preuve_b`
doivent être des sous-chaînes exactes de `texte_source`, vérifiées en Python
APRÈS l'appel. I11 est le cas qui justifie cet étage : aucune grandeur, aucun
conflit déontique, seul le sens permet de trancher.

**Deux garde-fous, et deux seulement** (`docs/plan-1-semaine.md` §J6) :

1. **Filtre contraint** — une preuve absente du texte **annule** le verdict, là où les
   gardes de l'étage A se contentent de le rétrograder. La paire part en abstention et le
   taux d'annulation est journalisé. Un LLM qui invente sa preuve ne peut pas polluer le
   rapport.
2. **Abstention** — ``INDECIDABLE`` est une sortie légitime, qui remonte dans le rapport.

**⚠️ Écart assumé à architecture.md §7.4**, consigné au Journal : les garde-fous n°2
(anti-biais de position, ordre (A,B) puis (B,A)) et n°3 (auto-cohérence bornée, 3
échantillons à T = 0,2) ne sont **pas** implémentés. Ils multiplient les appels par 2 et
par 3 ; à 59 appels mesurés pour un plafond de 60, ils sont hors d'atteinte. Ce n'est pas
un oubli : c'est le premier candidat à la reprise si le budget se desserre. Le garde-fou
n°5 (plafond de budget), lui, est implémenté — le plafond l'exige.

**Le budget dégrade, il n'interrompt jamais.** Plafond atteint, service éteint, JSON
irréparable : chacun de ces cas produit une abstention **nommée** dans le rapport, jamais
une exception qui avorte l'exécution. C'est la forme opérationnelle du garde-fou n°5 :
« paires marquées NON_VERIFIEE_BUDGET, jamais silencieusement rejetées ».
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from pydantic import BaseModel, Field

from cohera import llm
from cohera.detection import config_detection
from cohera.detection.cascade import Detection, ranger
from cohera.detection.modeles import Motif, TypeVerdict, Verdict, verifier_preuves
from cohera.detection.portees import RelationPortees, relation_portees
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.conditions import Algebre
from cohera.ingestion.modeles import Clause

DETECTEUR = "C"
ETAGE = "C"


# ------------------------------------------------------------------ contrat de sortie


class SortieJuge(BaseModel):
    """Le JSON contraint d'architecture.md §7.4, mot pour mot.

    Les valeurs sont volontairement des `str` et non des énumérations pydantic : un modèle
    qui rend « INCOHERENT » au lieu d'« INCOHERENCE » doit produire une **abstention
    traçable**, pas une `ValidationError` qui déclencherait une réparation inutile. La
    normalisation se fait en Python, où elle est lisible et testable.
    """

    verdict: str = ""
    type: str = ""
    preuve_a: str = ""
    preuve_b: str = ""
    relation_portees: str = ""
    clause_fautive: str = ""
    explication: str = ""
    confiance: float = 0.0


#: Les quatre issues du contrat, et ce qu'elles deviennent dans le vocabulaire du dépôt.
_VERDICTS = {
    "INCOHERENCE": TypeVerdict.CONTRADICTION,
    "COHERENT": TypeVerdict.COHERENT,
    "SPECIALISATION": TypeVerdict.SPECIALISATION,
    "INDECIDABLE": TypeVerdict.INDECIDABLE,
}


class ResultatJuge(BaseModel):
    """Ce que l'étage C a produit, et ce qu'il a coûté — auditable comme le reste."""

    verdicts: list[Verdict] = Field(default_factory=list)
    compteurs: llm.Compteurs = Field(default_factory=llm.Compteurs)

    paires_soumises: int = 0
    verdicts_annules: int = 0
    #: Paires jamais soumises parce que le PLAFOND était atteint.
    non_verifiees_budget: int = 0
    #: Paires jamais soumises parce que le coupe-circuit avait sauté. Compté à part :
    #: confondre les deux ferait lire une panne de service comme un manque de budget, et
    #: la conclusion à en tirer n'est pas la même — l'une se corrige en payant, l'autre non.
    non_verifiees_service: int = 0
    echecs_transport: int = 0
    coupe_circuit: bool = False

    @property
    def taux_annulation(self) -> float:
        """Part des réponses du modèle dont la preuve n'existait pas dans le texte.

        Journalisé parce que c'est la mesure directe de la crédibilité du juge : un taux
        élevé disqualifie le profil bien avant que le rappel ne le montre.
        """
        return self.verdicts_annules / self.paires_soumises if self.paires_soumises else 0.0


# ------------------------------------------------------------------------ le périmètre


class PaireAJuger(BaseModel):
    clause_a: str
    clause_b: str
    #: Le verdict de l'étage A qui explique pourquoi la paire remonte — le « signal amont »
    #: du prompt de §7.4. `None` quand l'étage A n'avait aucune donnée (I11).
    amont: Verdict | None = None

    @property
    def motif_amont(self) -> str:
        return self.amont.motif.value if self.amont else "AUCUN_SIGNAL_SYMBOLIQUE"


def paires_a_juger(
    detection: Detection,
    frames: dict[str, ClauseFrame],
    algebre: Algebre,
    scores: dict[frozenset, float] | None = None,
) -> list[PaireAJuger]:
    """Les paires que l'étage A n'a pas conclues, et qu'il n'a pas non plus fermées.

    Trois exclusions, dans cet ordre :

    1. une paire portant un verdict **ferme** est conclue ;
    2. une paire dont les **portées sont disjointes** ne peut pas se contredire — testé sur
       la paire et non sur le motif d'un détecteur, parce qu'aucun détecteur ne pose
       `PORTEES_DISJOINTES` quand il s'arrête plus tôt (mesuré sur N04) ;
    3. une paire portant un motif **fermant** — le symbolique a établi la compatibilité.

    Tout le reste est soumis, y compris les paires dont tous les verdicts sont `AUCUNE`
    faute de données : c'est ce qui fait entrer I11, que `label.json` désigne comme le cas
    qui justifie cet étage.

    **L'ordre est celui du score de fusion RRF, décroissant.** Ce n'est pas un détail de
    présentation : si le plafond de budget mord, il mord la fin de la liste. Trier par
    identifiant de clause — ce que faisait la première version — rendait la coupure
    alphabétique, et **I03 (D1 §9.2) n'a jamais été soumise** pour cette seule raison. Cela
    vidait de son sens la décision d'élargir le périmètre « pour qu'aucune cible ne soit
    écartée par construction ». À défaut de score, on retombe sur l'ordre des identifiants,
    qui a le seul mérite d'être stable.
    """
    fermants = config_detection.motifs_fermants()
    par_paire: dict[frozenset, list[Verdict]] = {}
    for rubrique in detection.rubriques:
        for verdict in rubrique:
            if verdict.clause_b is None:
                continue  # anomalie mono-clause : rien à juger, A5 a conclu seul
            par_paire.setdefault(frozenset((verdict.clause_a, verdict.clause_b)), []).append(verdict)

    retenues: list[PaireAJuger] = []
    for cle, verdicts in par_paire.items():
        if any(v.ferme for v in verdicts):
            continue
        clause_a, clause_b = verdicts[0].clause_a, verdicts[0].clause_b
        if config_detection.ecarter_les_portees_disjointes():
            frame_a, frame_b = frames.get(clause_a), frames.get(clause_b)
            if frame_a is not None and frame_b is not None:
                if relation_portees(frame_a, frame_b, algebre) is RelationPortees.DISJOINTE:
                    continue
        if any(v.motif.value in fermants for v in verdicts):
            continue
        escalades = [v for v in verdicts if v.type is not TypeVerdict.AUCUNE]
        retenues.append(
            PaireAJuger(clause_a=clause_a, clause_b=clause_b,
                        amont=escalades[0] if escalades else None)
        )

    # Score RRF décroissant d'abord — les paires que le ciblage juge les plus prometteuses
    # passent en premier. Les identifiants départagent, pour que deux exécutions soumettent
    # les mêmes paires dans le même ordre : sans cela le plafond couperait ailleurs et le
    # rapport ne serait pas rejouable.
    scores = scores or {}
    retenues.sort(
        key=lambda p: (-scores.get(frozenset((p.clause_a, p.clause_b)), 0.0),
                       p.clause_a, p.clause_b)
    )
    return retenues


# --------------------------------------------------------------- le sous-graphe injecté


#: Gabarit de sortie, **mesuré au J6 et non deviné**. Le profil `local` ne sait pas
#: contraindre son décodage (voir `config/technique.yaml`) : c'est le prompt qui doit tenir
#: la forme. Sans ce gabarit explicite, le modèle rend un JSON partiel — `preuve_a` et
#: `preuve_b` absentes — puis verse le reste en prose ; le filtre contraint annule alors
#: *tous* les verdicts, et l'étage C ne mesure plus que sa propre inutilité. Avec, sur le
#: même cas : un seul appel au lieu de deux, et deux preuves littérales.
CONSIGNE = """Tu es un auditeur de système documentaire QHSE. On te soumet deux clauses \
issues de deux documents différents, avec leur contexte de graphe.

Ta seule question : ces deux clauses SE CONTREDISENT-ELLES ?

Réponds UNIQUEMENT par un objet JSON, sans aucun texte avant ni après, avec EXACTEMENT \
ces huit clés :
{"verdict":"...","type":"...","preuve_a":"...","preuve_b":"...",\
"relation_portees":"...","clause_fautive":"...","explication":"...","confiance":0.0}

- preuve_a : recopie un fragment EXACT du texte de la CLAUSE A — copier-coller, mêmes \
accents, même ponctuation. Ne reformule jamais, ne corrige jamais. OBLIGATOIRE : un \
extrait inventé ou absent annule ton verdict.
- preuve_b : idem, pour la CLAUSE B. OBLIGATOIRE.
- verdict : INCOHERENCE | COHERENT | SPECIALISATION | INDECIDABLE
- type : NEGATION | NUMERIQUE | CONTENU | RELATION | FACTUEL | CAUSAL | PERSPECTIVE \
| HIERARCHIQUE | TEMPOREL
- relation_portees : IDENTIQUE | INCLUSION | DISJOINTE | INDETERMINEE
- clause_fautive : A | B | AUCUNE
- explication : deux phrases maximum, en français. Elle doit être COHÉRENTE avec le \
verdict que tu donnes.
- confiance : un nombre entre 0.0 et 1.0.

Comment trancher :
- Si les deux clauses portent sur des OBJETS DIFFÉRENTS, elles ne se contredisent pas, \
même si leurs valeurs diffèrent : réponds COHERENT.
- Si leurs périmètres d'application ne se recouvrent jamais : COHERENT.
- Si la clause de périmètre le plus étroit est aussi la plus stricte : SPECIALISATION.
- Si tu n'as pas de quoi trancher : INDECIDABLE. C'est une réponse légitime et attendue — \
mieux vaut t'abstenir que te tromper."""


def _ligne(etiquette: str, valeur: str) -> str:
    return f"  ↳ {etiquette} : {valeur}" if valeur else ""


def _bloc_clause(
    nom: str,
    clause: Clause,
    frame: ClauseFrame,
    objets: Iterable[str],
    niveau: int | None,
) -> str:
    """Le bloc de contexte d'une clause, sur le modèle d'architecture.md §7.4.

    Le **texte** vient de `texte_autonome` — c'est lui qui restitue le contexte perdu par la
    décontextualisation (« Il est archivé » devenu « Le registre est archivé »). Les
    **preuves**, elles, se vérifient contre `texte_source` : le modèle doit donc citer dans
    la portion qui en provient, et la consigne le lui demande explicitement.
    """
    limite = config_detection.longueur_max_texte()
    entete = f"{clause.doc_id}" + (f" · niveau {niveau}" if niveau is not None else "")
    chemin = " / ".join(clause.section_path) if clause.section_path else ""

    grandeurs = " ; ".join(
        f"{q.role} = {q.surface} ({q.valeur_si} SI, plus strict = {q.monotonie.value.lower()})"
        for q in frame.quantites
    )
    conditions = " ; ".join(f"{c.surface} [{c.type.value}]" for c in frame.conditions)
    normes = " ; ".join(r.cible for r in frame.references)

    lignes = [
        f"CLAUSE {nom}  [{entete} · §{clause.ref}" + (f" {chemin}" if chemin else "") + "]",
        f'"{clause.texte_autonome[:limite]}"',
        _ligne("modalité", frame.modalite.value if frame.modalite else ""),
        _ligne("acteur", frame.acteur.surface if frame.acteur else ""),
        _ligne("objets canoniques", ", ".join(sorted(objets))),
        _ligne("grandeurs", grandeurs),
        _ligne("conditions", conditions or "aucune"),
        _ligne("référentiels cités", normes),
    ]
    return "\n".join(ligne for ligne in lignes if ligne)


def contexte_de_paire(
    paire: PaireAJuger,
    clauses: dict[str, Clause],
    frames: dict[str, ClauseFrame],
    algebre: Algebre,
    objets: dict[str, set[str]],
    niveaux: dict[str, int] | None = None,
) -> str:
    """Le prompt utilisateur : deux blocs de clause, puis ce que le graphe sait de la paire.

    C'est l'emprunt à GraphCheck sans GNN (§7.4) : le modèle ne redécouvre pas ce que le
    pipeline a déjà établi — alias, portées, hiérarchie, signal amont — il en dispose.
    """
    niveaux = niveaux or {}
    clause_a, clause_b = clauses[paire.clause_a], clauses[paire.clause_b]
    frame_a, frame_b = frames[paire.clause_a], frames[paire.clause_b]

    objets_a = objets.get(paire.clause_a, set())
    objets_b = objets.get(paire.clause_b, set())
    communs = sorted(objets_a & objets_b)

    relation = relation_portees(frame_a, frame_b, algebre)
    niveau_a, niveau_b = niveaux.get(clause_a.doc_id), niveaux.get(clause_b.doc_id)

    hierarchie = "documents de même niveau"
    if niveau_a is not None and niveau_b is not None and niveau_a != niveau_b:
        inferieur = "A" if niveau_a > niveau_b else "B"
        hierarchie = (
            f"la clause {inferieur} appartient au document de niveau inférieur — "
            f"elle décline l'autre et ne peut pas être plus permissive"
        )

    return "\n\n".join(
        (
            _bloc_clause("A", clause_a, frame_a, objets_a, niveau_a),
            _bloc_clause("B", clause_b, frame_b, objets_b, niveau_b),
            "\n".join(
                (
                    f"OBJETS EN COMMUN     : {', '.join(communs) if communs else 'AUCUN'}"
                    + ("" if communs else "  ← les deux clauses ne parlent pas de la même chose"),
                    f"RELATION DES PORTÉES : {relation.value}",
                    f"HIÉRARCHIE           : {hierarchie}",
                    f"SIGNAL AMONT         : {paire.motif_amont}"
                    + (f" — {paire.amont.explication}" if paire.amont else ""),
                )
            ),
        )
    )


# ---------------------------------------------------------------- le filtre contraint


def _abstention(paire: PaireAJuger, motif: Motif, explication: str) -> Verdict:
    return Verdict(
        detecteur=DETECTEUR, type=TypeVerdict.INDECIDABLE, motif=motif,
        explication=explication, clause_a=paire.clause_a, clause_b=paire.clause_b,
        etage=ETAGE, ferme=False,
    )


def interpreter(paire: PaireAJuger, sortie: SortieJuge, textes: dict[str, str]) -> Verdict:
    """Traduit la réponse du modèle en :class:`Verdict`, **filtre contraint appliqué**.

    L'ordre des contrôles est celui de leur sévérité :

    1. verdict hors du vocabulaire fermé → abstention (le modèle n'a pas répondu à la
       question posée) ;
    2. abstention explicite → abstention ;
    3. **preuve non littérale → verdict ANNULÉ**, abstention, et le compteur d'annulation
       s'incrémente. C'est le garde-fou n°1, et il annule au lieu de rétrograder :
       `cascade.sceller_preuves` escalade parce qu'un détecteur symbolique ne ment pas sur
       ses preuves ; un LLM, si ;
    4. confiance sous le plancher → abstention.

    Une `SPECIALISATION` ou un `COHERENT` du juge sont des conclusions fermes : ils closent
    la paire sans rien affirmer d'incohérent.
    """
    type_verdict = _VERDICTS.get(sortie.verdict.strip().upper())
    if type_verdict is None:
        return _abstention(
            paire, Motif.EXTRACTION_INCERTAINE,
            f"verdict hors vocabulaire : {sortie.verdict!r}",
        )
    if type_verdict is TypeVerdict.INDECIDABLE:
        return _abstention(
            paire, Motif.ABSTENTION_DU_JUGE,
            sortie.explication or "le juge s'est abstenu",
        )

    candidat = Verdict(
        detecteur=DETECTEUR, type=type_verdict, motif=Motif.VERDICT_DU_JUGE,
        explication=sortie.explication,
        clause_a=paire.clause_a, clause_b=paire.clause_b,
        preuve_a=sortie.preuve_a or None, preuve_b=sortie.preuve_b or None,
        type_taxonomie=sortie.type, confiance=sortie.confiance,
        relation_portees=sortie.relation_portees,
        plus_permissive=sortie.clause_fautive if sortie.clause_fautive in ("A", "B") else None,
        etage=ETAGE, ferme=True,
    )

    # --- garde-fou n°1 : la preuve doit exister dans le texte, des DEUX côtés
    manquante = not sortie.preuve_a or not sortie.preuve_b
    if manquante or not verifier_preuves(candidat, textes):
        return _abstention(
            paire, Motif.PREUVE_INVENTEE,
            "preuve absente du texte source — verdict annulé"
            + (f" ({sortie.verdict})" if sortie.verdict else ""),
        )

    if sortie.confiance < config_detection.confiance_min_juge():
        return candidat.model_copy(
            update={
                "type": TypeVerdict.INDECIDABLE, "ferme": False,
                "motif": Motif.ABSTENTION_DU_JUGE,
                "explication": f"confiance {sortie.confiance:.2f} sous le plancher "
                               f"({config_detection.confiance_min_juge():.2f})",
            }
        )

    return candidat


# ------------------------------------------------------------------------- la boucle


def juger(
    detection: Detection,
    clauses: dict[str, Clause],
    frames: dict[str, ClauseFrame],
    textes: dict[str, str],
    algebre: Algebre,
    objets: dict[str, set[str]],
    *,
    niveaux: dict[str, int] | None = None,
    scores: dict[frozenset, float] | None = None,
    profil: str | None = None,
    budget: int | None = None,
    transport: Callable[..., llm.ReponseLLM] | None = None,
    compteurs: llm.Compteurs | None = None,
) -> ResultatJuge:
    """Soumet au LLM les paires que l'étage A n'a pas conclues. **Ne lève jamais.**

    Les verdicts sont rangés dans ``detection`` au fil de l'eau, ce qui rend le résultat
    lisible par les mêmes accesseurs que l'étage A (`Detection.verdicts_de`).

    Trois façons de ne pas juger une paire, toutes trois **nommées dans le rapport** :
    plafond de budget atteint, service injoignable, JSON irréparable. Aucune n'interrompt
    le parcours ; à la fin, chaque paire soumise a un verdict ou une abstention motivée.
    """
    resultat = ResultatJuge(compteurs=compteurs or llm.Compteurs())
    plafond = budget if budget is not None else config_detection.max_appels_juge()
    seuil_echecs = config_detection.echecs_consecutifs_max()
    temperature = config_detection.temperature_juge()

    paires = paires_a_juger(detection, frames, algebre, scores)
    echecs_consecutifs = 0

    def budget_disponible() -> bool:
        """Consulté par `llm.completer` **après** le cache, juste avant le réseau.

        C'est ce qui fait qu'une paire déjà mémorisée passe même à budget nul : sans cela,
        la seconde exécution du pipeline marquerait tout en NON_VERIFIEE_BUDGET sans avoir
        rien dépensé, et les deux rapports du même corpus différeraient.
        """
        return resultat.compteurs.appels_reseau < plafond

    for paire in paires:
        if paire.clause_a not in clauses or paire.clause_b not in clauses:
            continue

        # Le coupe-circuit, lui, se lit AVANT : il n'y a rien à espérer d'un service éteint,
        # et le cache aurait de toute façon été consulté sans succès aux essais précédents.
        if resultat.coupe_circuit:
            verdict = _abstention(
                paire, Motif.LLM_INJOIGNABLE, "service injoignable, coupe-circuit déclenché"
            )
            resultat.verdicts.append(verdict)
            ranger(detection, verdict)
            resultat.non_verifiees_service += 1
            continue

        messages = [
            {"role": "system", "content": CONSIGNE},
            {
                "role": "user",
                "content": contexte_de_paire(paire, clauses, frames, algebre, objets, niveaux),
            },
        ]

        try:
            statut = llm.completer_json(
                messages, SortieJuge, nom_schema="verdict_cohera", profil=profil,
                temperature=temperature, compteurs=resultat.compteurs, transport=transport,
                budget_disponible=budget_disponible,
            )
        except llm.BudgetEpuise:
            # Garde-fou n°5 : la paire est NOMMÉE dans le rapport, jamais rejetée en silence.
            verdict = _abstention(
                paire, Motif.NON_VERIFIEE_BUDGET,
                f"plafond de {plafond} appels réseau atteint — paire non vérifiée, pas rejetée",
            )
            resultat.verdicts.append(verdict)
            ranger(detection, verdict)
            resultat.non_verifiees_budget += 1
            continue
        except llm.ErreurLLM as exc:
            # Une panne de service n'avorte pas le run : elle devient une abstention motivée.
            echecs_consecutifs += 1
            resultat.echecs_transport += 1
            verdict = _abstention(
                paire, Motif.LLM_INJOIGNABLE, f"{exc} — {getattr(exc, 'remede', '')}".strip(" —")
            )
            resultat.verdicts.append(verdict)
            ranger(detection, verdict)
            if echecs_consecutifs >= seuil_echecs:
                # Coupe-circuit : sans lui, un service éteint coûte N × timeout_s pour rien.
                resultat.coupe_circuit = True
            continue

        echecs_consecutifs = 0
        resultat.paires_soumises += 1

        if not statut.ok:
            verdict = _abstention(
                paire, Motif.EXTRACTION_INCERTAINE,
                "réponse non conforme au schéma, après une tentative de réparation",
            )
        else:
            verdict = interpreter(paire, statut.objet, textes)
            if verdict.motif is Motif.PREUVE_INVENTEE:
                resultat.verdicts_annules += 1

        resultat.verdicts.append(verdict)
        ranger(detection, verdict)

    return resultat
