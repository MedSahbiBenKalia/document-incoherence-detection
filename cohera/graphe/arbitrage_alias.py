"""Arbitrage LLM de la zone grise des alias — usage n°1 du J6.

Le J3 range chaque paire de concepts dans l'une de trois cases : alias (arête écrite),
liste noire (veto tracé), ou **zone grise** — la bande où le cosinus ne tranche pas. Cette
bande est écrite dans `zone_grise.jsonl` et attend ici son arbitre.

**Pourquoi le LLM et pas un seuil de plus.** Abaisser le seuil vectoriel pour absorber la
bande introduirait des alias erronés — le risque n°1 de `architecture.md` §13 — et la
mesure du J3 le confirme : `anomalie`/`écart` (0,541) est *au-dessus* de paires légitimes.
Le vecteur a atteint sa limite ; c'est un jugement lexical qu'il faut, pas un curseur.

**Ce que l'arbitrage produit, et ce qu'il ne produit pas.** Une arête `ALIAS_DE` de méthode
``LLM``, tracée comme **hypothèse révisable** et exposée dans le rapport. Jamais un verdict :
`architecture.md` §13 (R1) pose qu'un alias n'est « jamais suffisant seul pour un verdict
ferme ». Le module ne touche pas non plus aux seuils — la bande est ce qu'elle est.

⚠️ **Mesuré au J6 : les deux paires de la zone grise ne sont PAS celles qu'I03 demande.**
`label.json` associe à I03 les alias `archiver ~ conserver` et
`registre de contrôle des EPI ~ enregistrements de vérification`. Le J3 a mesuré
`archiver ~ conserver` à **0,613**, sous le plancher de la bande : la paire n'est donc pas
dans `zone_grise.jsonl`, et aucun arbitrage ne peut la faire apparaître. La bande n'a pas
été élargie pour l'y forcer — ce serait relâcher un seuil pour fabriquer un résultat
attendu. I03 n'a sa chance que par le juge de paires (`detection/juge_llm.py`). C'est le
critère rouge (b) du J3, inchangé.
"""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, Field

from cohera import llm
from cohera.graphe.alias import AliasArete, Methode, PaireGrise, Pont, lire_zone_grise

CONSIGNE = """Tu es terminologue dans un système documentaire QHSE (qualité, hygiène, \
sécurité, environnement).

On te soumet deux libellés extraits de deux procédures différentes. Ta seule question :
désignent-ils **exactement la même chose** dans ce domaine, au point qu'une exigence \
portant sur l'un s'applique telle quelle à l'autre ?

Réponds `true` seulement si la substitution est sûre dans les deux sens. En cas de doute, \
réponds `false` : un alias erroné propage des fausses incohérences sur des dizaines de \
clauses, alors qu'un alias manqué n'en coûte qu'une.

Exemples de ce qui n'est PAS un alias : deux équipements de protection différents \
(casque / gants), deux notions voisines mais de portée différente (anomalie / accident), \
un terme et son hyperonyme quand l'exigence ne se transporte pas."""


class SortieAlias(BaseModel):
    """Contrat de sortie de l'arbitrage. `str` pour `justification`, jamais d'énumération."""

    alias: bool = False
    confiance: float = 0.0
    justification: str = ""


class AliasArbitre(BaseModel):
    """Un arbitrage rendu — conservé même négatif, pour que la décision soit auditable."""

    libelle_a: str
    libelle_b: str
    score_vectoriel: float
    alias: bool
    confiance: float
    justification: str = ""
    #: Renseigné quand le LLM n'a pas répondu : panne, budget, JSON irréparable.
    abstention: str = ""

    @property
    def retenu(self) -> bool:
        return self.alias and not self.abstention


class ResultatArbitrage(BaseModel):
    arbitrages: list[AliasArbitre] = Field(default_factory=list)
    compteurs: llm.Compteurs = Field(default_factory=llm.Compteurs)
    abstentions: int = 0

    @property
    def aretes_ajoutees(self) -> list[AliasArbitre]:
        return [a for a in self.arbitrages if a.retenu]


def _messages(paire: PaireGrise) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CONSIGNE},
        {
            "role": "user",
            "content": (
                f"Libellé A : « {paire.libelle_a} »\n"
                f"Libellé B : « {paire.libelle_b} »\n"
                f"Similarité vectorielle mesurée : {paire.score:.3f} "
                f"(sous le seuil d'alias automatique, d'où cet arbitrage)."
            ),
        },
    ]


def arbitrer(
    paires: list[PaireGrise],
    *,
    profil: str | None = None,
    confiance_min: float = 0.70,
    transport: Callable[..., llm.ReponseLLM] | None = None,
    compteurs: llm.Compteurs | None = None,
    budget_disponible: Callable[[], bool] | None = None,
) -> ResultatArbitrage:
    """Un appel par paire de la zone grise. **Ne lève jamais.**

    Comme le juge, toute panne devient une abstention tracée : la zone grise reste alors ce
    qu'elle était, et le rapport le dit. Aucun alias n'est inventé par défaut — l'échec
    d'arbitrage se lit « non tranché », jamais « pas alias ».
    """
    resultat = ResultatArbitrage(compteurs=compteurs or llm.Compteurs())

    for paire in paires:
        def abstenir(raison: str) -> None:
            resultat.arbitrages.append(
                AliasArbitre(
                    libelle_a=paire.libelle_a, libelle_b=paire.libelle_b,
                    score_vectoriel=paire.score, alias=False, confiance=0.0,
                    abstention=raison,
                )
            )
            resultat.abstentions += 1

        try:
            statut = llm.completer_json(
                _messages(paire), SortieAlias, nom_schema="alias_cohera", profil=profil,
                temperature=0.0, compteurs=resultat.compteurs, transport=transport,
                budget_disponible=budget_disponible,
            )
        except llm.BudgetEpuise:
            abstenir("plafond d'appels atteint")
            continue
        except llm.ErreurLLM as exc:
            abstenir(f"service injoignable : {exc}")
            continue

        if not statut.ok:
            abstenir("réponse non conforme au schéma, après une tentative de réparation")
            continue

        sortie: SortieAlias = statut.objet
        # Un « oui » peu assuré ne vaut pas mieux qu'un « je ne sais pas » : un alias erroné
        # est le risque n°1 (architecture.md §13, R1).
        retenu = sortie.alias and sortie.confiance >= confiance_min
        resultat.arbitrages.append(
            AliasArbitre(
                libelle_a=paire.libelle_a, libelle_b=paire.libelle_b,
                score_vectoriel=paire.score, alias=retenu, confiance=sortie.confiance,
                justification=sortie.justification,
            )
        )

    return resultat


def appliquer(
    pont: Pont,
    paires: list[PaireGrise],
    resultat: ResultatArbitrage,
    vocabulaire=None,
) -> int:
    """Écrit dans le pont les arêtes retenues, de méthode ``LLM``. Renvoie leur nombre.

    Les classes canoniques sont **réélues** quand le vocabulaire est fourni : un alias
    ajouté peut fusionner deux classes, et c'est précisément ce qu'on en attend — c'est ce
    qui change `objets_partages`, donc ce qui peut débloquer une paire à l'étage A. Sans
    réélection, l'arête serait écrite sans jamais rien changer au reste du pipeline.
    """
    from cohera.graphe.alias import _elire_canoniques

    par_libelles = {(p.libelle_a, p.libelle_b): p for p in paires}
    retenues: list[PaireGrise] = []

    for arbitrage in resultat.aretes_ajoutees:
        paire = par_libelles.get((arbitrage.libelle_a, arbitrage.libelle_b))
        if paire is None:
            continue
        pont.aretes.append(
            AliasArete(
                concept_a=paire.concept_a, concept_b=paire.concept_b,
                libelle_a=paire.libelle_a, libelle_b=paire.libelle_b,
                methode=Methode.LLM, score=arbitrage.confiance,
            )
        )
        retenues.append(paire)

    if retenues:
        arbitrees = {(p.libelle_a, p.libelle_b) for p in retenues}
        pont.zone_grise = [
            p for p in pont.zone_grise if (p.libelle_a, p.libelle_b) not in arbitrees
        ]
        if vocabulaire is not None:
            pont.canoniques = _elire_canoniques(
                list(vocabulaire.concepts.values()), pont.aretes
            )

    return len(retenues)


def arbitrer_la_zone_grise(
    pont: Pont, vocabulaire=None, **kwargs
) -> tuple[ResultatArbitrage, int]:
    """Lit `zone_grise.jsonl`, arbitre, applique. Le point d'entrée de la CLI.

    La zone grise du pont en mémoire fait foi si elle est renseignée ; le fichier n'est lu
    qu'à défaut, pour que la commande reste utilisable sans avoir rejoué `graphe charger`.
    """
    paires = list(pont.zone_grise) or lire_zone_grise()
    resultat = arbitrer(paires, **kwargs)
    return resultat, appliquer(pont, paires, resultat, vocabulaire)
