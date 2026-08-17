"""Vérification **bloquante** des preuves littérales du rapport.

Premier critère d'acceptation du J7 : « 100 % des preuves citées sont des sous-chaînes
littérales du texte source (vérification programmatique) ». C'est l'invariant #3 de
`CLAUDE.md` appliqué non plus à un verdict, mais au **rapport entier**, juste avant qu'il
ne soit publié.

**Pourquoi une seconde vérification, alors que la cascade en fait déjà une ?**
`cascade.sceller_preuves` protège chaque verdict au moment où il naît. Entre ce moment et
l'écriture du rapport, il se passe des choses : la consolidation regroupe, l'ordre change,
les occurrences sont recopiées, un futur détecteur pourra reformuler une explication. Une
vérification en sortie est la seule qui atteste ce que l'auditeur lira *effectivement*.

⚠️ **Cette vérification est STRICTE, là où `CoteClause.preuve_est_litterale` est permissive.**
Cette méthode rend `True` quand `texte_source` vaut `None` — bon comportement pour un
rapport partiel, mais ce serait ici un laissez-passer : « je n'ai pas de texte contre quoi
vérifier » deviendrait « la preuve est bonne ». Les deux coexistent, et la seconde ne
remplace pas la première.

Trois façons d'échouer, toutes trois nommées plutôt que comptées :

* ``PREUVE_ABSENTE`` — une constatation qui n'affirme rien de citable ne devrait pas être
  une constatation ;
* ``TEXTE_SOURCE_ABSENT`` — rien contre quoi vérifier, donc rien de vérifié ;
* ``PREUVE_NON_LITTERALE`` — la citation n'existe pas dans le texte : c'est la reformulation
  ou l'hallucination que le garde-fou n°1 d'architecture.md §7.4 doit arrêter.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from cohera.restitution.rapport_json import CoteClause, Rapport


class MotifEchecPreuve(StrEnum):
    PREUVE_ABSENTE = "PREUVE_ABSENTE"
    TEXTE_SOURCE_ABSENT = "TEXTE_SOURCE_ABSENT"
    PREUVE_NON_LITTERALE = "PREUVE_NON_LITTERALE"


class EchecPreuve(BaseModel):
    """Une preuve du rapport qui ne tient pas — nommée, jamais seulement comptée."""

    rubrique: str = ""
    identifiant: str = ""
    clause: str = ""
    motif: MotifEchecPreuve
    preuve: str = ""

    def __str__(self) -> str:
        return f"[{self.rubrique} {self.identifiant}] {self.clause} : {self.motif.value} — {self.preuve!r}"


class BilanPreuves(BaseModel):
    """Le verdict de la vérification, et de quoi l'afficher sans recalculer."""

    verifiees: int = 0
    echecs: list[EchecPreuve] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return self.verifiees + len(self.echecs)

    @property
    def conforme(self) -> bool:
        """100 %, ou rien. Le critère du plan ne tolère pas une preuve fausse sur cent."""
        return not self.echecs

    @property
    def taux(self) -> float:
        """Un rapport sans aucune preuve vaut 1,0 : il n'affirme rien, il ne ment pas."""
        return 1.0 if not self.total else self.verifiees / self.total


def _verifier_cote(
    cote: CoteClause | None, *, rubrique: str, identifiant: str, exiger_une_preuve: bool
) -> EchecPreuve | None:
    """Contrôle un côté de constatation. Rend `None` quand tout va bien."""
    if cote is None:
        return None

    preuve = cote.preuve.strip()
    commun = {"rubrique": rubrique, "identifiant": identifiant, "clause": cote.libelle()}

    if not preuve:
        if exiger_une_preuve:
            return EchecPreuve(**commun, motif=MotifEchecPreuve.PREUVE_ABSENTE)
        return None

    if cote.texte_source is None:
        return EchecPreuve(**commun, motif=MotifEchecPreuve.TEXTE_SOURCE_ABSENT, preuve=preuve)

    if cote.preuve not in cote.texte_source:
        return EchecPreuve(**commun, motif=MotifEchecPreuve.PREUVE_NON_LITTERALE, preuve=preuve)

    return None


def verifier(rapport: Rapport) -> BilanPreuves:
    """Contrôle toutes les preuves citées par le rapport.

    Les constatations doivent **porter** une preuve de chaque côté : c'est une affirmation,
    elle se justifie. Les occurrences regroupées et les dérogations ne sont contrôlées que
    si elles en citent une — leur rôle est d'informer, pas d'accuser.
    """
    bilan = BilanPreuves()

    def controler(cote, *, rubrique: str, identifiant: str, exiger: bool) -> None:
        echec = _verifier_cote(
            cote, rubrique=rubrique, identifiant=identifiant, exiger_une_preuve=exiger
        )
        if echec is not None:
            bilan.echecs.append(echec)
        elif cote is not None and cote.preuve.strip():
            bilan.verifiees += 1

    for constatation in rapport.constatations:
        for cote in (constatation.clause_a, constatation.clause_b):
            controler(cote, rubrique="constatation", identifiant=constatation.id, exiger=True)

        for occurrence in constatation.occurrences:
            # L'occurrence représentante est le constat lui-même : la contrôler une seconde
            # fois gonflerait le dénominateur sans rien vérifier de plus.
            if occurrence.id == constatation.id:
                continue
            for cote in (occurrence.clause_a, occurrence.clause_b):
                controler(cote, rubrique="occurrence", identifiant=occurrence.id, exiger=False)

    for index, derogation in enumerate(rapport.derogations_en_vigueur, start=1):
        identifiant = derogation.id or f"derogation-{index:03d}"
        for cote in (derogation.clause_a, derogation.clause_b):
            controler(cote, rubrique="dérogation", identifiant=identifiant, exiger=False)

    return bilan


def formater_bilan(bilan: BilanPreuves, couleur: bool = True) -> str:
    """Rend le bilan en texte — le chiffre que le critère d'acceptation du J7 réclame."""
    vert, rouge, fin = ("\033[32m", "\033[31m", "\033[0m") if couleur else ("", "", "")

    if bilan.conforme:
        return (
            f"{vert}Preuves littérales : {bilan.verifiees}/{bilan.total} vérifiées "
            f"({bilan.taux:.0%}){fin}"
        )

    lignes = [
        f"{rouge}Preuves littérales : {bilan.verifiees}/{bilan.total} vérifiées "
        f"({bilan.taux:.0%}) — {len(bilan.echecs)} échec(s){fin}"
    ]
    lignes += [f"  {echec}" for echec in bilan.echecs]
    lignes.append("")
    lignes.append(
        "Aucun rapport n'est publié tant qu'une preuve citée n'existe pas dans son texte "
        "source : c'est l'invariant #3 du projet."
    )
    return "\n".join(lignes)
