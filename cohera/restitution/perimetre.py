"""Le périmètre de travail, et le **jugement** de chaque détection — quand des annotations
sont disponibles, et **rien du tout** quand il n'y en a pas.

Deux régimes, et un seul code :

* **Avec annotations** (`corpus/<jeu>/label.json`, ou tout fichier de même forme passé en
  `--annotations`) : chaque constatation est confrontée à la vérité terrain et dite
  **correcte** ou **erronée** ; les rubriques qui raisonnent par paire — zones non
  couvertes, hypothèses d'alignement — se restreignent au périmètre déclaré, et le rapport
  dit combien il a mis de côté.
* **Sans annotations** : le rapport se génère à l'identique, sans jugement et sans
  restriction. C'est le régime réel : sur de vraies procédures, personne ne fournit de
  vérité terrain, et un rapport qui exigerait la réponse pour poser la question ne
  servirait à rien.

⚠️ **Les constatations ne sont JAMAIS filtrées, même hors périmètre.** Elles sont
*classées*. Masquer une détection erronée rendrait le rapport flatteur et faux : un
auditeur doit voir ce que le système affirme à tort, c'est même la première chose qu'il
cherche. Seules les abstentions et les hypothèses d'alignement se restreignent au
périmètre — ce sont des rubriques de contexte, pas des affirmations.

⚠️ **Ce module ne mesure rien.** Il n'y a qu'un seul harnais de mesure, `cohera evaluer`,
qui travaille sur `rapport.json` — jamais filtré. Ce module en emprunte la clé
d'appariement (`evaluation.metriques.cle_entree` et `cle_constatation`), délibérément
importée plutôt que réécrite : deux définitions de « la même paire » finiraient par
diverger, et le rapport montrerait alors autre chose que ce que l'évaluation compte.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cohera.evaluation.metriques import Cle, cle_constatation, cle_entree, libelles
from cohera.restitution.rapport_json import Constatation, Rapport

#: Rubriques de `label.json` et ce qu'une correspondance y signifie pour une détection.
#: `limites_connues` décrit ce que le système ne peut PAS voir : une détection qui y
#: tomberait serait une surprise, on la nomme plutôt que de la ranger d'office en erreur.
RUBRIQUES = ("incoherences", "contre_exemples", "limites_connues")


class Jugement(StrEnum):
    """Ce que la vérité terrain dit d'une détection. Jamais posé sans annotations."""

    #: La paire correspond à une incohérence annotée — dans le périmètre ou hors de lui.
    CORRECTE = "CORRECTE"
    #: Aucune incohérence annotée ne correspond : soit la paire est un contre-exemple
    #: explicite (un piège, `N0x`), soit elle n'est nulle part dans la vérité terrain.
    ERRONEE = "ERRONEE"


class Annotation(BaseModel):
    """Une entrée de la vérité terrain, réduite à ce dont le rapport a besoin."""

    identifiant: str = ""
    rubrique: str = ""
    dans_perimetre: bool = False

    @property
    def est_une_incoherence(self) -> bool:
        return self.rubrique == "incoherences"


class Perimetre(BaseModel):
    """Ce que le fichier d'annotations déclare — **toutes** les rubriques, pas seulement
    le périmètre.

    Charger les entrées hors périmètre n'est pas un détail : sans elles, une détection
    juste mais hors barème (I06, I19…) serait déclarée erronée. Le périmètre décide de ce
    qu'on *attend*, pas de ce qui est *vrai*.
    """

    source: str = ""
    #: Clé d'appariement -> annotation, toutes rubriques confondues.
    annotations: dict[Cle, Annotation] = Field(default_factory=dict)
    #: Les identifiants d'incohérences **du périmètre**, dans l'ordre du fichier.
    incoherences: list[str] = Field(default_factory=list)
    #: Les couples ``(doc, ref)`` cités par le périmètre — sert aux rubriques qui
    #: raisonnent par clause et non par paire (les hypothèses d'alignement).
    clauses: set[tuple[str, str]] = Field(default_factory=set)

    model_config = {"arbitrary_types_allowed": True}

    def annotation(self, cle: Cle) -> Annotation | None:
        return self.annotations.get(cle)

    def contient(self, cle: Cle) -> bool:
        """La paire est-elle **dans le périmètre** ? Filtre des rubriques de contexte."""
        annotation = self.annotations.get(cle)
        return annotation is not None and annotation.dans_perimetre

    def identifiant(self, cle: Cle) -> str:
        annotation = self.annotations.get(cle)
        return annotation.identifiant if annotation else ""


def _chemin_lisible(chemin: Path) -> str:
    """``corpus/fixtures/label.json`` plutôt que le chemin absolu de la machine.

    Le rapport HTML est fait pour circuler : y imprimer ``C:\\Users\\…`` déborde de la
    page et renseigne sur le poste de travail, pas sur le corpus.
    """
    from cohera import reglages

    try:
        return chemin.resolve().relative_to(reglages.racine_projet().resolve()).as_posix()
    except ValueError:
        return chemin.name


def charger(chemin: Path | str | None) -> Perimetre | None:
    """Lit un fichier d'annotations. ``None`` en entrée comme en sortie = pas de périmètre.

    Un chemin **absent du disque** rend `None` plutôt qu'une erreur : c'est le cas nominal
    d'un corpus réel, pas une panne. Un fichier présent mais illisible, en revanche, lève —
    on ne fait pas passer une erreur de saisie pour une absence d'annotations.
    """
    if chemin is None:
        return None
    chemin = Path(chemin)
    if not chemin.is_file():
        return None

    brut: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
    perimetre = Perimetre(source=_chemin_lisible(chemin))

    for rubrique in RUBRIQUES:
        for entree in brut.get(rubrique, []):
            cle = cle_entree(entree)
            if cle is None:
                continue
            dans_perimetre = bool(entree.get("dans_perimetre_7j"))
            identifiant = str(entree.get("id", "")).strip()
            perimetre.annotations[cle] = Annotation(
                identifiant=identifiant, rubrique=rubrique, dans_perimetre=dans_perimetre
            )
            if not dans_perimetre:
                continue
            perimetre.clauses |= set(cle)
            if rubrique == "incoherences":
                perimetre.incoherences.append(identifiant)

    return perimetre


# ─────────────────────────────────────────────────── le jugement d'une détection


class Classement(BaseModel):
    """Une détection, et ce que la vérité terrain en dit — quand elle en dit quelque chose.

    ``jugement`` vaut `None` sans annotations : c'est ce `None` qui fait **disparaître**
    l'étiquette du rapport plutôt que d'afficher un « statut inconnu », qui laisserait
    croire à une mesure ratée là où il n'y a simplement rien à mesurer.
    """

    constatation: Constatation
    jugement: Jugement | None = None
    #: « I08 », « N04 »… vide quand la paire ne correspond à aucune annotation.
    identifiant: str = ""
    rubrique: str = ""
    dans_perimetre: bool = False

    @property
    def correcte(self) -> bool:
        return self.jugement is Jugement.CORRECTE

    @property
    def erronee(self) -> bool:
        return self.jugement is Jugement.ERRONEE

    @property
    def motif(self) -> str:
        """Pourquoi ce jugement — en une phrase lisible sans le dépôt."""
        if self.jugement is None:
            return ""
        if self.correcte:
            hors = "" if self.dans_perimetre else ", hors du périmètre chiffré"
            return f"Correspond à l'incohérence {self.identifiant} de la vérité terrain{hors}."
        if self.rubrique == "contre_exemples":
            return (
                f"Correspond au contre-exemple {self.identifiant} : cette paire est un "
                f"piège, elle devait rester silencieuse."
            )
        if self.rubrique == "limites_connues":
            return (
                f"Correspond à la limite connue {self.identifiant}, que la vérité terrain "
                f"déclare hors de portée du système."
            )
        return "Aucune correspondance dans la vérité terrain."


def classer(rapport: Rapport, perimetre: Perimetre | None) -> list[Classement]:
    """Range les constatations : les correctes d'abord, les erronées ensuite.

    L'ordre à l'intérieur de chaque groupe est celui que la consolidation a produit — la
    criticité décroissante d'architecture.md §8.3. Le tri est **stable** : il partitionne,
    il ne réordonne pas.

    Sans périmètre, tout sort dans l'ordre d'origine, sans jugement. C'est l'unique
    différence entre les deux régimes, et elle tient en une ligne.
    """
    classements = []
    for constatation in rapport.constatations:
        if perimetre is None:
            classements.append(Classement(constatation=constatation))
            continue

        annotation = perimetre.annotation(cle_constatation(constatation))
        correcte = annotation is not None and annotation.est_une_incoherence
        classements.append(
            Classement(
                constatation=constatation,
                jugement=Jugement.CORRECTE if correcte else Jugement.ERRONEE,
                identifiant=annotation.identifiant if annotation else "",
                rubrique=annotation.rubrique if annotation else "",
                dans_perimetre=annotation.dans_perimetre if annotation else False,
            )
        )

    if perimetre is None:
        return classements
    return [c for c in classements if c.correcte] + [c for c in classements if not c.correcte]


# ─────────────────────────────────────────── la restriction des rubriques de contexte


def _cle_paire(clause_a, clause_b) -> Cle:
    couples = [clause_a.couple()] if clause_a is not None else []
    if clause_b is not None:
        couples.append(clause_b.couple())
    return frozenset(couples)


class Restriction(BaseModel):
    """Le rapport restreint, ses détections classées, et le compte de ce qui a été écarté.

    Les compteurs ne sont pas décoratifs : une rubrique qui rétrécirait sans le dire
    laisserait croire que le système n'a rien trouvé d'autre, ce qui est faux. Ils sont
    affichés en tête de page.
    """

    rapport: Rapport
    perimetre: Perimetre | None = None

    classements: list[Classement] = Field(default_factory=list)

    abstentions_ecartees: int = 0
    hypotheses_ecartees: int = 0

    #: Identifiants du périmètre qu'aucune constatation ne couvre — la moitié « attendu »
    #: de la comparaison attendu / obtenu. Vide sans annotations, et la rubrique disparaît.
    non_detectees: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def actif(self) -> bool:
        return self.perimetre is not None

    @property
    def correctes(self) -> list[Classement]:
        return [c for c in self.classements if c.correcte]

    @property
    def erronees(self) -> list[Classement]:
        return [c for c in self.classements if c.erronee]

    @property
    def ecartees(self) -> int:
        return self.abstentions_ecartees + self.hypotheses_ecartees

    @property
    def detectees(self) -> int:
        """Combien d'incohérences **du périmètre** sont couvertes par une détection."""
        if self.perimetre is None:
            return 0
        return len(self.perimetre.incoherences) - len(self.non_detectees)

    @property
    def precision(self) -> float:
        """Part des détections qui correspondent à une incohérence annotée.

        Calculée sur **toutes** les détections, périmètre compris ou non — c'est ce que le
        lecteur voit à l'écran. Elle ne remplace pas les deux barèmes de `cohera evaluer`,
        qui neutralisent les trouvailles hors périmètre ; les deux chiffres répondent à
        deux questions différentes et le rapport le dit.
        """
        total = len(self.classements)
        return len(self.correctes) / total if total else 0.0


def restreindre(rapport: Rapport, perimetre: Perimetre | None) -> Restriction:
    """Classe les détections et restreint les rubriques de contexte au périmètre.

    Rend une **copie** du rapport : `rapport.json` reste le contrat d'évaluation et n'est
    jamais amputé. Filtrer le fichier plutôt que la vue ferait mentir `cohera evaluer`, qui
    compterait alors zéro faux positif parce qu'on les aurait effacés.

    Les **constatations ne sont pas filtrées** — voir l'en-tête du module. Les
    **dérogations non plus**, et c'est délibéré : ce sont des conflits *apparents* que le
    rapport doit lister pour que l'auditeur sache qu'ils sont couverts. Les retirer parce
    que la vérité terrain les range hors du barème chiffré reviendrait à masquer une
    exemption en vigueur — exactement ce que la rubrique existe pour éviter.
    """
    classements = classer(rapport, perimetre)

    if perimetre is None:
        return Restriction(rapport=rapport, classements=classements)

    abstentions = [
        abstention
        for abstention in rapport.abstentions
        if perimetre.contient(_cle_paire(abstention.clause_a, abstention.clause_b))
    ]

    hypotheses = [
        hypothese
        for hypothese in rapport.hypotheses_alias
        # Une hypothèse d'alignement ne porte pas sur une paire mais sur deux termes :
        # elle est dans le périmètre dès qu'une clause du périmètre emploie l'un d'eux.
        # Une hypothèse dont on ne sait pas quelles clauses l'emploient est conservée —
        # taire faute d'information vaudrait moins que montrer.
        if not hypothese.clauses()
        or any(ref.couple() in perimetre.clauses for ref in hypothese.clauses())
    ]

    couvertes = {c.identifiant for c in classements if c.correcte}
    restreint = rapport.model_copy(
        update={"abstentions": abstentions, "hypotheses_alias": hypotheses}
    )
    # Les classements portent les constatations du rapport, inchangées : la copie n'en
    # modifie aucune, elle ne remplace que les deux rubriques de contexte.

    return Restriction(
        rapport=restreint,
        perimetre=perimetre,
        classements=classements,
        abstentions_ecartees=len(rapport.abstentions) - len(abstentions),
        hypotheses_ecartees=len(rapport.hypotheses_alias) - len(hypotheses),
        non_detectees=[i for i in perimetre.incoherences if i not in couvertes],
    )


def resume(restriction: Restriction) -> str:
    """Une ligne pour la console : ce qui a été jugé, et ce qui a été mis de côté."""
    if not restriction.actif:
        return (
            "Aucun fichier d'annotations : le rapport présente tout ce qui a été détecté, "
            "sans jugement."
        )
    perimetre = restriction.perimetre
    assert perimetre is not None
    return "\n".join(
        (
            f"Périmètre lu dans {perimetre.source} : "
            f"{len(perimetre.annotations)} paires annotées, dont "
            f"{len(perimetre.incoherences)} incohérences attendues dans le périmètre.",
            f"{restriction.detectees}/{len(perimetre.incoherences)} incohérences du "
            f"périmètre détectées"
            + (
                f" — non détectées : {', '.join(restriction.non_detectees)}."
                if restriction.non_detectees
                else "."
            ),
            f"Détections : {len(restriction.correctes)} correcte(s), "
            f"{len(restriction.erronees)} erronée(s) — toutes affichées.",
            f"Mis de côté comme hors périmètre : {restriction.abstentions_ecartees} "
            f"abstention(s), {restriction.hypotheses_ecartees} hypothèse(s).",
        )
    )


__all__ = [
    "Annotation",
    "Classement",
    "Jugement",
    "Perimetre",
    "Restriction",
    "charger",
    "classer",
    "libelles",
    "restreindre",
    "resume",
]
