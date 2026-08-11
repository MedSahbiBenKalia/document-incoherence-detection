"""Construction des arêtes ALIAS_DE entre concepts — le pont inter-documents.

C'est la pièce maîtresse du J3 (architecture.md §5.6). Sans elle, D1 et D2 forment deux
composantes connexes disjointes : aucune paire candidate ne sort du graphe au J4, et aucune
incohérence inter-documents n'est visible.

**Cascade de coût croissant**, sur les paires de concepts issus de documents différents :

1. identité normalisée et lemmatisée      -> ALIAS_DE {EXACT, 1.00}
2. lexique métier + gazetteer des rôles   -> ALIAS_DE {LEXIQUE, 0.95}
3. similarité vectorielle                 -> ALIAS_DE {VECTEUR, cos} si cos >= seuil
                                             sinon zone grise, arbitrée par le LLM au J6

**Le veto passe avant tout.** La liste noire est consultée en premier, pas en dernier : une
paire interdite ne doit jamais produire d'arête, quel que soit son cosinus et quel que soit
le niveau qui l'aurait acceptée. Un alias erroné rend comparables des dizaines de clauses
sans rapport — c'est le risque n°1 du projet (architecture.md §13, R1).

**Ce que la mesure du J3 a établi, et qu'il faut savoir en lisant ce module.** Sur ce
corpus, l'étage 3 ne produit *aucune* arête. Les deux paires que le plan attendait en
VECTEUR (« Responsable QSE » ~ « Référent sécurité », « contrôle » ~ « vérification »)
scorent 0,55 et 0,62 avec bge-m3, quand deux paires de la liste noire scorent 0,54 — aucun
seuil ne les sépare, et Solon-embeddings-large ne fait pas mieux. Elles sont donc portées
par l'étage 2. Le détail du calibrage, chiffres à l'appui, est dans
`config/lexique_qhse.yaml`. L'étage 3 reste implémenté parce qu'il est la seule voie de
passage à l'échelle, et son apport nul sur les fixtures se chiffrera en ablation au J7.

Les alias forment des classes d'équivalence (union-find) dont on élit un **représentant
canonique** : toutes les requêtes de ciblage passeront par lui.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from cohera import embeddings, reglages
from cohera.graphe.concepts import Concept, Vocabulaire
from cohera.graphe.config_alias import (
    SCORE_EXACT,
    SCORE_LEXIQUE,
    charger_config_alias,
    couples_interdits,
    paires_lexicales,
)
from cohera.graphe.libelles import normaliser_libelle


class Methode(StrEnum):
    """Comment l'alias a été établi — propriété `methode` de l'arête ALIAS_DE."""

    EXACT = "EXACT"
    LEXIQUE = "LEXIQUE"
    VECTEUR = "VECTEUR"
    LLM = "LLM"


class AliasArete(BaseModel):
    """Une arête `ALIAS_DE` entre deux concepts."""

    concept_a: str
    concept_b: str
    libelle_a: str
    libelle_b: str
    methode: Methode
    score: float

    @property
    def couple(self) -> frozenset[str]:
        return frozenset((normaliser_libelle(self.libelle_a), normaliser_libelle(self.libelle_b)))


class PaireGrise(BaseModel):
    """Une paire non tranchée, laissée à l'arbitrage LLM du J6."""

    concept_a: str
    concept_b: str
    libelle_a: str
    libelle_b: str
    score: float
    raison: str = ""


class Veto(BaseModel):
    """Une paire écartée par la liste noire — tracée, pour que le veto soit auditable."""

    libelle_a: str
    libelle_b: str
    score: float
    niveau_qui_aurait_accepte: str


class Pont(BaseModel):
    """Le résultat du pont : arêtes, zone grise, classes canoniques, traces."""

    aretes: list[AliasArete] = Field(default_factory=list)
    zone_grise: list[PaireGrise] = Field(default_factory=list)
    vetos: list[Veto] = Field(default_factory=list)
    #: concept_id -> concept_id du représentant canonique de sa classe.
    canoniques: dict[str, str] = Field(default_factory=dict)
    #: Cosinus mesuré pour chaque paire examinée, clé « a||b » sur libellés normalisés.
    cosinus: dict[str, float] = Field(default_factory=dict)

    def alias_de(self, libelle_a: str, libelle_b: str) -> AliasArete | None:
        """L'arête reliant deux libellés, dans un sens ou dans l'autre."""
        cible = frozenset((normaliser_libelle(libelle_a), normaliser_libelle(libelle_b)))
        return next((a for a in self.aretes if a.couple == cible), None)

    def sont_allies(self, libelle_a: str, libelle_b: str, vocabulaire: Vocabulaire) -> bool:
        """Les deux libellés partagent-ils une classe canonique ?

        Distinct de :meth:`alias_de` : deux concepts peuvent se retrouver dans la même
        classe **sans arête directe**, par transitivité via un troisième. Pour la liste
        noire, c'est cette question-là qui compte — un alias transitif est tout aussi
        destructeur qu'un alias direct.
        """
        a = vocabulaire.par_libelle(libelle_a)
        b = vocabulaire.par_libelle(libelle_b)
        if a is None or b is None:
            return False
        return self.canoniques.get(a.concept_id) == self.canoniques.get(b.concept_id)

    def cosinus_de(self, libelle_a: str, libelle_b: str) -> float | None:
        return self.cosinus.get(_cle_cosinus(libelle_a, libelle_b))


def _cle_cosinus(a: str, b: str) -> str:
    gauche, droite = sorted((normaliser_libelle(a), normaliser_libelle(b)))
    return f"{gauche}||{droite}"


# ------------------------------------------------------------------------- union-find


class UnionFind:
    """Classes d'équivalence, avec compression de chemin."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def ajouter(self, element: str) -> None:
        self._parent.setdefault(element, element)

    def trouver(self, element: str) -> str:
        self.ajouter(element)
        racine = element
        while self._parent[racine] != racine:
            racine = self._parent[racine]
        while self._parent[element] != racine:
            self._parent[element], element = racine, self._parent[element]
        return racine

    def unir(self, a: str, b: str) -> None:
        racine_a, racine_b = self.trouver(a), self.trouver(b)
        if racine_a != racine_b:
            # Ordre stable : la plus petite racine gagne, pour que deux exécutions
            # produisent exactement la même structure.
            gagnante, perdante = sorted((racine_a, racine_b))
            self._parent[perdante] = gagnante

    def classes(self) -> dict[str, list[str]]:
        groupes: dict[str, list[str]] = {}
        for element in self._parent:
            groupes.setdefault(self.trouver(element), []).append(element)
        return {racine: sorted(membres) for racine, membres in groupes.items()}


# ------------------------------------------------------------------ cascade des niveaux


def _est_interdit(a: Concept, b: Concept) -> bool:
    """La paire figure-t-elle sur la liste noire ?

    Comparaison sur la forme de **surface** normalisée, celle qu'écrit l'auteur du YAML :
    un veto doit être prévisible par qui le pose, pas dépendre de ce qu'un lemmatiseur
    décidera un jour de faire de « gants ».
    """
    couple = frozenset((normaliser_libelle(a.libelle), normaliser_libelle(b.libelle)))
    return couple in couples_interdits()


def _paires_lexicales_normalisees() -> frozenset[frozenset[str]]:
    return frozenset(
        frozenset((normaliser_libelle(a), normaliser_libelle(b)))
        for a, b in paires_lexicales()
    )


def _niveau_lexique(a: Concept, b: Concept, declarees: frozenset[frozenset[str]]) -> bool:
    couple = frozenset((normaliser_libelle(a.libelle), normaliser_libelle(b.libelle)))
    return couple in declarees


def _niveau_exact(a: Concept, b: Concept) -> bool:
    """Identité après normalisation **et** lemmatisation.

    C'est ce qui rapproche « fiche de contrôle » de « fiches de contrôle » sans rien
    rapprocher d'autre : le seul écart que la forme de surface ne sait pas absorber.
    """
    return bool(a.libelle_canonique) and a.libelle_canonique == b.libelle_canonique


# ------------------------------------------------------------------------ construction


def construire_pont(
    vocabulaire: Vocabulaire,
    *,
    encodeur=None,
    seuils=None,
) -> Pont:
    """Applique la cascade à toutes les paires inter-documents et élit les canoniques."""
    seuils = seuils or charger_config_alias().seuils
    declarees = _paires_lexicales_normalisees()
    concepts = list(vocabulaire.concepts.values())

    couples = _couples_inter_documents(concepts)
    cosinus = _cosinus_des_couples(couples, encodeur=encodeur)

    pont = Pont(cosinus=cosinus)
    candidats_gris: list[PaireGrise] = []

    for a, b in couples:
        score = cosinus.get(_cle_cosinus(a.libelle, b.libelle), 0.0)

        if _est_interdit(a, b):
            pont.vetos.append(
                Veto(
                    libelle_a=a.libelle,
                    libelle_b=b.libelle,
                    score=score,
                    niveau_qui_aurait_accepte=_niveau_hypothetique(a, b, declarees, seuils, score),
                )
            )
            continue

        if _niveau_exact(a, b):
            pont.aretes.append(_arete(a, b, Methode.EXACT, SCORE_EXACT))
        elif _niveau_lexique(a, b, declarees):
            pont.aretes.append(_arete(a, b, Methode.LEXIQUE, SCORE_LEXIQUE))
        elif score >= seuils.alias_vecteur:
            pont.aretes.append(_arete(a, b, Methode.VECTEUR, score))
        else:
            candidats_gris.append(
                PaireGrise(
                    concept_a=a.concept_id,
                    concept_b=b.concept_id,
                    libelle_a=a.libelle,
                    libelle_b=b.libelle,
                    score=score,
                    raison=(
                        "dans la bande [zone_grise_min, alias_vecteur)"
                        if score >= seuils.zone_grise_min
                        else "retenue par le budget, hors bande"
                    ),
                )
            )

    pont.zone_grise = _retenir_zone_grise(candidats_gris, seuils.zone_grise_budget)
    pont.canoniques = _elire_canoniques(concepts, pont.aretes)
    return pont


def _arete(a: Concept, b: Concept, methode: Methode, score: float) -> AliasArete:
    return AliasArete(
        concept_a=a.concept_id,
        concept_b=b.concept_id,
        libelle_a=a.libelle,
        libelle_b=b.libelle,
        methode=methode,
        score=round(float(score), 4),
    )


def _niveau_hypothetique(a, b, declarees, seuils, score: float) -> str:
    """Quel niveau aurait accepté cette paire sans le veto ? Rend le veto auditable.

    Sans cette trace, on ne saurait pas si la liste noire a réellement servi ou si la paire
    aurait de toute façon été rejetée — et le test de la liste noire serait tautologique.
    """
    if _niveau_exact(a, b):
        return Methode.EXACT.value
    if _niveau_lexique(a, b, declarees):
        return Methode.LEXIQUE.value
    if score >= seuils.alias_vecteur:
        return Methode.VECTEUR.value
    if score >= seuils.zone_grise_min:
        return "ZONE_GRISE"
    return "AUCUN"


def _couples_inter_documents(concepts: list[Concept]) -> list[tuple[Concept, Concept]]:
    """Les paires de concepts dont les **couvertures documentaires diffèrent**.

    Première version écrite ici : « aucun document en commun ». Elle était trop stricte et
    ratait silencieusement deux alias attendus. « contrôle » apparaît dans D1 *et* D2,
    « vérification » dans D2 seul : l'intersection étant non vide, la paire n'était jamais
    examinée — alors que c'est précisément l'alias dont I02 dépend. Même effet sur
    « fiche de contrôle » / « fiches de contrôle ».

    Le bon critère est la **différence** des couvertures : il faut qu'un document contienne
    l'un sans l'autre, sinon les rapprocher n'ouvre aucun passage. Deux concepts confinés au
    même unique document ont des couvertures identiques et sont donc écartés — les aliaser
    ne relierait rien et ne ferait qu'ajouter du risque.
    """
    couples: list[tuple[Concept, Concept]] = []
    for i, a in enumerate(concepts):
        for b in concepts[i + 1 :]:
            if not a.doc_ids or not b.doc_ids:
                continue
            if set(a.doc_ids) == set(b.doc_ids):
                continue
            couples.append((a, b) if a.concept_id <= b.concept_id else (b, a))
    return couples


def _cosinus_des_couples(couples, *, encodeur=None) -> dict[str, float]:
    """Cosinus de chaque couple, en n'encodant chaque libellé qu'une fois."""
    if not couples:
        return {}

    libelles = list(dict.fromkeys(c.libelle for paire in couples for c in paire))
    vecteurs = embeddings.encoder(libelles, encodeur=encodeur)
    index = {libelle: i for i, libelle in enumerate(libelles)}

    return {
        _cle_cosinus(a.libelle, b.libelle): embeddings.cosinus(
            vecteurs[index[a.libelle]], vecteurs[index[b.libelle]]
        )
        for a, b in couples
    }


def _retenir_zone_grise(candidats: list[PaireGrise], budget: int) -> list[PaireGrise]:
    """Les `budget` meilleures paires non tranchées, du cosinus le plus élevé au plus bas.

    La bande [zone_grise_min, alias_vecteur) de architecture.md §5.6 ne sélectionne rien sur
    ce corpus — les deux paires attendues valent 0,61 et 0,60, sous le plancher de 0,72. Le
    budget prend donc le relais, sur le modèle du top-k employé partout ailleurs dans le
    ciblage. Départage alphabétique à cosinus égal, pour que deux exécutions donnent
    exactement la même liste.
    """
    ordonnes = sorted(candidats, key=lambda p: (-p.score, p.libelle_a, p.libelle_b))
    return ordonnes[:budget]


def _elire_canoniques(concepts: list[Concept], aretes: list[AliasArete]) -> dict[str, str]:
    """Un représentant par classe d'équivalence : le libellé le plus fréquent.

    Départage par ordre alphabétique du `concept_id` à fréquence égale — sans quoi le
    canonique dépendrait de l'ordre de parcours, et deux chargements successifs
    écriraient des `cle_comparaison` différentes. L'idempotence en dépend.
    """
    union = UnionFind()
    for concept in concepts:
        union.ajouter(concept.concept_id)
    for arete in aretes:
        union.unir(arete.concept_a, arete.concept_b)

    par_id = {concept.concept_id: concept for concept in concepts}
    canoniques: dict[str, str] = {}

    for membres in union.classes().values():
        representant = min(
            membres,
            key=lambda cid: (-par_id[cid].frequence, cid),
        )
        for membre in membres:
            canoniques[membre] = representant
    return canoniques


# ------------------------------------------------------------------------ zone grise


def chemin_zone_grise() -> Path:
    """`zone_grise.jsonl` à la racine du dépôt — consommé par le J6."""
    return reglages.racine_projet() / "zone_grise.jsonl"


def ecrire_zone_grise(pont: Pont, chemin: Path | None = None) -> Path:
    """Écrit les paires non tranchées, une par ligne, pour l'arbitrage LLM du J6."""
    chemin = chemin or chemin_zone_grise()
    lignes = [
        json.dumps(paire.model_dump(mode="json"), ensure_ascii=False)
        for paire in pont.zone_grise
    ]
    chemin.write_text("\n".join(lignes) + ("\n" if lignes else ""), encoding="utf-8")
    return chemin


def lire_zone_grise(chemin: Path | None = None) -> list[PaireGrise]:
    """Relit `zone_grise.jsonl`. Fichier absent = liste vide, pas une erreur."""
    chemin = chemin or chemin_zone_grise()
    if not chemin.is_file():
        return []
    return [
        PaireGrise.model_validate_json(ligne)
        for ligne in chemin.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]
