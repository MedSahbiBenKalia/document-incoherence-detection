"""Étage B — inférence en langue naturelle, bidirectionnelle.

architecture.md §7.3. Placé entre les détecteurs symboliques et le LLM juge, il ne voit
que les paires que l'étage A n'a **ni conclues ni fermées** — les mêmes que celles que
`juge_llm.paires_a_juger` soumettrait.

**Ce que cet étage a le droit de faire, et c'est tout : fermer une paire par le bas.**
Quand `max P(contradiction)` tombe sous `seuil_rejet`, les deux sens de l'inférence
s'accordent à ne voir aucune opposition, et la paire n'atteint pas le LLM. Au-dessus, il
**journalise et se tait** — il ne produit aucune citation, et l'invariant #3 de `CLAUDE.md`
interdit un verdict sans preuve littérale. C'est aussi ce que la mesure du J8 recommande :
la bande haute des 57 paires du corpus contient autant de vrais que de faux, et affirmer
depuis là ajouterait des constatations fausses. Le détail chiffré est dans
`config/detection.yaml`, section `nli`.

**Bidirectionnel.** Le NLI n'est pas symétrique : on calcule `P(contradiction | A→B)` et
`P(contradiction | B→A)` et on retient le maximum (§7.3). Pour la fermeture, retenir le
maximum revient à exiger que **les deux** sens soient bas — c'est la borne prudente.

**Le découpage suit la convention du dépôt** (`embeddings.py`, `compat.py`) : la logique
de zonage est séparée du modèle, et :func:`scorer` accepte un `inferer` injectable. Toute
la plomberie se teste ainsi sans charger 250 Mo.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Callable, Sequence

from pydantic import BaseModel, Field

from cohera import reglages
from cohera.detection import config_detection
from cohera.ingestion.modeles import Clause

#: Un inféreur reçoit deux listes alignées (prémisses, hypothèses) et rend, pour chaque
#: couple, la seule quantité dont §7.3 se sert : `P(contradiction)`.
Infereur = Callable[[list[str], list[str]], Sequence[float]]

DETECTEUR = "NLI"


class ZoneNLI(StrEnum):
    """Les trois bandes de §7.3. Une seule est fermante, et c'est `REJET`."""

    CONTRADICTION_FERME = "CONTRADICTION_FERME"
    ZONE_GRISE = "ZONE_GRISE"
    REJET = "REJET"


class ScoreNLI(BaseModel):
    """Ce que le NLI a dit d'une paire — les deux sens conservés, pas seulement le maximum.

    Garder les deux sens n'est pas décoratif : sur le corpus, 23 paires sur 57 changent de
    bande selon l'ordre, et l'écart atteint 0,84. C'est la seule façon de répondre à
    « cette paire est-elle vraiment contradictoire, ou le modèle est-il instable ? ».
    """

    clause_a: str
    clause_b: str
    p_contradiction_ab: float
    p_contradiction_ba: float
    #: Le maximum des deux sens — la valeur de §7.3, celle qui décide de la zone.
    p_contradiction: float
    zone: ZoneNLI

    @property
    def stable(self) -> bool:
        """Les deux sens tombent-ils dans la même zone ?

        Observation du J8, sans effet opérationnel mais consignée : dans la bande haute du
        corpus, les paires stables étaient les vraies incohérences, et les instables le
        faux positif et le contre-exemple. Le maximum de §7.3 promeut l'instabilité en
        confiance.
        """
        return zone_de(self.p_contradiction_ab) is zone_de(self.p_contradiction_ba)


class ResultatNLI(BaseModel):
    """Le journal de l'étage B — tous les scores, y compris ceux qui n'ont rien fermé."""

    modele: str = ""
    seuil_rejet: float = 0.0
    seuil_contradiction: float = 0.0
    scores: list[ScoreNLI] = Field(default_factory=list)

    @property
    def paires_soumises(self) -> int:
        return len(self.scores)

    @property
    def paires_fermees(self) -> int:
        """Le gain de l'étage B, et le seul : autant de paires que le LLM ne verra pas."""
        return sum(1 for s in self.scores if s.zone is ZoneNLI.REJET)

    @property
    def repartition(self) -> dict[ZoneNLI, int]:
        return {zone: sum(1 for s in self.scores if s.zone is zone) for zone in ZoneNLI}

    @property
    def paires_instables(self) -> int:
        """Combien de paires changent de zone selon le sens de l'inférence."""
        return sum(1 for s in self.scores if not s.stable)


# --------------------------------------------------------------------- entrée du modèle


def entree_nli(clause: Clause) -> str:
    """`texte_autonome` préfixé du chemin de section (§7.3).

    Deux décisions, toutes deux dictées par la décontextualisation de L0 :

    * `texte_autonome` et non `texte_source` — D1 §1.2 commence par « Elle s'applique… »
      dans le fichier ; sans l'autonomisation, le modèle n'a pas le sujet de la phrase.
      Les preuves littérales, elles, se vérifient toujours contre `texte_source`, mais
      l'étage B n'en produit aucune.
    * le chemin de section restitue le contexte que la segmentation a retiré, exactement
      comme le fait `juge_llm._bloc_clause` pour le prompt du LLM.
    """
    chemin = " ".join(clause.section_path) if clause.section_path else ""
    entete = f"{clause.doc_id} §{clause.ref}" + (f" {chemin}" if chemin else "")
    return f"[{entete}] {clause.texte_autonome}"


# ---------------------------------------------------------------------------- le modèle


@lru_cache(maxsize=2)
def _modele(nom: str, device: str):
    """Charge le modèle une fois par processus. Import différé : ~1,4 s et 250 Mo."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    modele = AutoModelForSequenceClassification.from_pretrained(nom).to(device)
    modele.eval()
    return AutoTokenizer.from_pretrained(nom), modele


def _indice_contradiction(modele) -> int:
    """L'indice de l'étiquette « contradiction », **lu dans le modèle**, jamais supposé.

    `cmarkea/distilcamembert-base-nli` range la contradiction en 0, mais les alternatives
    de §7.3 (`camembert-base-xnli`, `mDeBERTa-…-xnli`) la rangent en 2. Coder l'indice en
    dur donnerait des probabilités inversées sans lever la moindre erreur — exactement le
    genre de panne silencieuse que le cache par nom de modèle évite côté embeddings.
    """
    for indice, etiquette in modele.config.id2label.items():
        if str(etiquette).lower().startswith("contradict"):
            return int(indice)
    raise ValueError(
        f"aucune étiquette « contradiction » dans {modele.config.id2label} — "
        "le modèle configuré n'est pas un modèle NLI à trois classes"
    )


def _infereur_par_defaut(premisses: list[str], hypotheses: list[str]) -> list[float]:
    """Inférence réelle, par lots, sans gradient. Rend `P(contradiction)` par couple."""
    import torch

    nom = reglages.charger().nli.modele
    tokenizer, modele = _modele(nom, reglages.device_effectif())
    indice = _indice_contradiction(modele)
    lot = config_detection.taille_lot_nli()

    probabilites: list[float] = []
    with torch.no_grad():
        for debut in range(0, len(premisses), lot):
            entrees = tokenizer(
                premisses[debut:debut + lot], hypotheses[debut:debut + lot],
                return_tensors="pt", truncation=True, padding=True, max_length=512,
            ).to(modele.device)
            sorties = torch.softmax(modele(**entrees).logits, dim=-1)
            probabilites += sorties[:, indice].tolist()
    return probabilites


# ---------------------------------------------------------------------------- le zonage


def zone_de(p_contradiction: float) -> ZoneNLI:
    """Range une probabilité dans l'une des trois bandes. Bornes **inclusives**.

    `<= seuil_rejet` ferme la paire ; `>= seuil_contradiction` ne fait que la ranger.
    """
    rejet, contradiction = config_detection.seuils_nli()
    if p_contradiction <= rejet:
        return ZoneNLI.REJET
    if p_contradiction >= contradiction:
        return ZoneNLI.CONTRADICTION_FERME
    return ZoneNLI.ZONE_GRISE


def scorer(
    paires: Sequence[tuple[str, str]],
    clauses: dict[str, Clause],
    *,
    inferer: Infereur | None = None,
) -> list[ScoreNLI]:
    """Score toutes les paires, **les deux sens en un seul appel groupé**.

    Grouper n'est pas une micro-optimisation : c'est ce qui rend tenable le coût annoncé
    par §7.3 (lots de 32). Les paires dont une clause manque sont ignorées silencieusement
    — c'est le même contrat que `cascade.detecter`, qui saute une paire sans frame.
    """
    retenues = [(a, b) for a, b in paires if a in clauses and b in clauses]
    if not retenues:
        return []

    premisses: list[str] = []
    hypotheses: list[str] = []
    for a, b in retenues:
        entree_a, entree_b = entree_nli(clauses[a]), entree_nli(clauses[b])
        premisses += [entree_a, entree_b]
        hypotheses += [entree_b, entree_a]

    probabilites = list((inferer or _infereur_par_defaut)(premisses, hypotheses))

    scores: list[ScoreNLI] = []
    for rang, (a, b) in enumerate(retenues):
        ab, ba = float(probabilites[2 * rang]), float(probabilites[2 * rang + 1])
        maximum = max(ab, ba)
        scores.append(
            ScoreNLI(
                clause_a=a, clause_b=b,
                p_contradiction_ab=ab, p_contradiction_ba=ba,
                p_contradiction=maximum, zone=zone_de(maximum),
            )
        )
    return scores
