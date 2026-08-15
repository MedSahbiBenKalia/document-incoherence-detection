"""Extraction des concepts d'une clause : acteur, action, objet.

Le J3 demande « acteur (gazetteer), objet et action (syntaxe spaCy : sujet / verbe / objet
direct) ». Ce module produit les nœuds `Concept` (architecture.md §5.2) et les mentions qui
les relient aux clauses, sur lesquels s'appuient ensuite le pont inter-documents et le
canal conceptuel du J4.

**Pourquoi les groupes nominaux ne viennent pas de `noun_chunks`.** Mesuré sur le corpus :
`fr_core_news_lg` découpe « chaque fiche de contrôle » en « chaque fiche » + « contrôle »,
et réduit « harnais antichute » à « harnais ». On reconstruit donc le groupe depuis le
**sous-arbre de dépendance** de sa tête, ce qui rend « fiche de contrôle » et « registre de
contrôle des EPI » d'un seul tenant.

**Décomposition tête + modifieurs.** Chaque groupe nominal produit *aussi* ses sous-groupes
`nmod`. « le port du casque » donne « port du casque » et « casque » ; « contrôle des EPI »
donne « contrôle des EPI », « contrôle » et « EPI ». C'est ce qui permet au pont de relier
« contrôle des EPI » à « vérification des équipements de protection » : les syntagmes
complets ne se ressemblent pas, mais leurs têtes et leurs modifieurs s'alignent deux à deux
— et le canal 3 du J4 exige justement **deux** concepts partagés.

**Deux défauts de `fr_core_news_lg` réparés ici**, l'un et l'autre mesurés sur le corpus et
tous deux fatals à la clé de comparaison de D1 §4.2 (le canal CLE que `label.json` attend
pour I01) :

1. *POS.* Dans « Le Responsable QSE valide chaque fiche de contrôle », « valide » est
   étiqueté ADJ. On le rattrape par la syntaxe — un adjectif français ne régit pas d'objet
   direct — et non par une liste de verbes.
2. *Lemme.* La table `lemma_rules` du modèle couvre « -es », « -ent », « -ait », « -é »…
   mais **pas** « -e » : tout verbe du 1er groupe au présent de 3ᵉ personne du singulier
   ressort lemmatisé sur sa propre forme fléchie (« valide », « anime », « applique »,
   « comporte » sur ce corpus). On complète la table et on ne retient qu'un infinitif
   attesté par l'index verbal de spaCy lui-même.

**Un acteur n'est pas du vocabulaire objet.** « Le Responsable QSE » produisait aussi
l'objet « Responsable », rare donc à fort IDF, qui raflait la position `objet` de la clé de
comparaison. On écarte le groupe dont la tête tombe dans un rôle du gazetteer — sans
toucher aux jetons, contrairement aux grandeurs : voir la mise en garde sur
:func:`objets_de`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, Field

from cohera import reglages
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.libelles import forme_canonique, normaliser_libelle
from cohera.ingestion.modeles import Clause, Segmentation

#: Relations dont la tête porte un groupe nominal digne d'un concept.
_RELATIONS_NOMINALES = frozenset(
    {"nsubj", "nsubj:pass", "obj", "iobj", "obl:arg", "obl:mod", "obl:agent", "obl"}
)

#: Étiquettes grammaticales exclues d'un libellé de concept.
_POS_EXCLUS = frozenset({"DET", "ADP", "PUNCT", "NUM", "CCONJ", "SCONJ", "AUX", "PRON"})

#: Un concept doit porter au moins un nom ou un nom propre.
_POS_PORTEUSES = frozenset({"NOUN", "PROPN"})


class TypeConcept(StrEnum):
    """Le rôle joué par le concept dans la clause — devient `role` sur l'arête MENTIONNE."""

    ACTEUR = "ACTEUR"
    ACTION = "ACTION"
    OBJET = "OBJET"


class Concept(BaseModel):
    """Un terme du vocabulaire du domaine (architecture.md §5.2)."""

    concept_id: str
    libelle: str
    libelle_canonique: str
    type: TypeConcept
    doc_ids: list[str] = Field(default_factory=list)
    frequence: int = 0
    idf: float = 0.0

    @property
    def inter_documents(self) -> bool:
        """Vrai si le concept apparaît dans plus d'un document."""
        return len(set(self.doc_ids)) > 1


class Mention(BaseModel):
    """Une arête `MENTIONNE` : la clause parle de ce concept."""

    clause_id: str
    concept_id: str
    role: TypeConcept
    poids: float = 1.0


class Vocabulaire(BaseModel):
    """Le résultat de l'extraction sur tout le corpus."""

    concepts: dict[str, Concept] = Field(default_factory=dict)
    mentions: list[Mention] = Field(default_factory=list)

    def par_libelle(self, libelle: str) -> Concept | None:
        """Retrouve un concept par n'importe quelle graphie de son libellé."""
        cherche = normaliser_libelle(libelle)
        for concept in self.concepts.values():
            if normaliser_libelle(concept.libelle) == cherche:
                return concept
        return None

    def concepts_de(self, clause_id: str) -> list[Concept]:
        return [
            self.concepts[m.concept_id]
            for m in self.mentions
            if m.clause_id == clause_id and m.concept_id in self.concepts
        ]


# ------------------------------------------------------------------------- gazetteer


def _roles_gazetteer() -> list[str]:
    """Les rôles QHSE connus, du plus long au plus court.

    Le tri importe : « Responsable QSE » doit être reconnu avant que « QSE » ne le soit,
    sinon deux rôles distincts s'effondreraient sur un même concept.
    """
    lexique = reglages.charger_config("lexique_qhse")
    roles = lexique.get("gazetteer_roles", [])
    return sorted(roles, key=len, reverse=True)


def acteurs_de(texte: str) -> list[str]:
    """Les rôles du gazetteer présents dans un texte, sans chevauchement.

    Travaille sur la forme normalisée pour absorber casse et accents, et masque chaque
    occurrence trouvée afin qu'un rôle plus court inclus dans un plus long ne soit pas
    compté deux fois.
    """
    reste = normaliser_libelle(texte)
    trouves: list[str] = []
    for role in _roles_gazetteer():
        cible = normaliser_libelle(role)
        if cible and cible in reste:
            trouves.append(role)
            reste = reste.replace(cible, " " * len(cible))
    return trouves


# --------------------------------------------------------------------------- syntaxe


def _descendre_xcomp(jeton):
    """Le verbe porteur du sens, sous les verbes support.

    « est chargé de valider » et « doit être renouvelé » ont pour racine un verbe vide de
    contenu ; l'action réelle est dans le `xcomp`. On descend tant qu'il y en a un.
    """
    courant = jeton
    vus = set()
    while True:
        enfants = [e for e in courant.children if e.dep_ == "xcomp" and e.pos_ == "VERB"]
        if not enfants or courant.i in vus:
            return courant
        vus.add(courant.i)
        courant = enfants[0]


#: Règle absente de la table `lemma_rules` de `fr_core_news_lg` : le présent de 3ᵉ personne
#: du singulier des verbes du 1er groupe. C'est de la morphologie du français, pas du
#: vocabulaire QHSE — sa place est dans le code et non dans `config/`.
_REGLE_MANQUANTE = ("e", "er")


@lru_cache(maxsize=1)
def _tables_verbales() -> tuple[tuple[tuple[str, str], ...], frozenset[str]]:
    """Les règles et l'index verbaux de spaCy, complétés de la règle manquante.

    Renvoie des tables vides si le modèle chargé n'expose pas ces ressources : la
    lemmatisation retombe alors sur celle de spaCy, sans lever.
    """
    from cohera.ingestion.phrases import analyseur

    try:
        lookups = analyseur().get_pipe("lemmatizer").lookups
        regles = [tuple(regle) for regle in lookups.get_table("lemma_rules").get("verb", [])]
        index = lookups.get_table("lemma_index").get("verb", [])
    except (KeyError, ValueError):
        return (), frozenset()
    return (*regles, _REGLE_MANQUANTE), frozenset(index)


def _lemme_verbal(forme: str) -> str | None:
    """L'infinitif d'une forme fléchie, ou `None` si aucun candidat n'est attesté.

    La validation contre l'index verbal de spaCy est ce qui rend la manœuvre sûre : « fiche »
    donnerait « ficher » et « zone » donnerait « zoner », deux infinitifs bien réels. Ce
    n'est pas ce filtre qui les écarte — c'est le fait qu'on n'appelle cette fonction que sur
    un jeton déjà reconnu comme verbe. Le filtre, lui, écarte « obligatoire » et
    « accessibles », qui ne mènent à aucun verbe.
    """
    forme = forme.lower()
    regles, index = _tables_verbales()
    if forme in index:
        return forme
    for ancien, nouveau in regles:
        if forme.endswith(ancien):
            candidat = f"{forme[: len(forme) - len(ancien)]}{nouveau}"
            if candidat in index:
                return candidat
    return None


def _est_verbe_mal_etiquete(jeton) -> bool:
    """Une racine non verbale qui régit un sujet **et** un objet direct est un verbe.

    « valide » est un homographe — l'adjectif existe — mais un adjectif français ne prend pas
    d'objet direct. Le double critère suffit donc à trancher sans lexique : sur le corpus, il
    ne retient que D1 §4.2, et laisse « conforme », « obligatoire » et « accessibles », qui
    ont bien un sujet mais aucun `obj`.
    """
    if jeton.pos_ in ("VERB", "AUX"):
        return False
    relations = {enfant.dep_ for enfant in jeton.children}
    return bool(relations & {"nsubj", "nsubj:pass"}) and "obj" in relations


def action_de(doc):
    """Le lemme du verbe principal, ou `None` si la clause n'en porte pas.

    Une clause comme « Le port du casque est obligatoire » a une racine adjectivale et donc
    aucune action : c'est la modalité qui la caractérise, déjà extraite au J2.
    """
    racines = [jeton for jeton in doc if jeton.dep_ == "ROOT"]
    if not racines:
        return None

    verbe = _descendre_xcomp(racines[0])
    etiquete_verbe = verbe.pos_ in ("VERB", "AUX")
    if not etiquete_verbe and not _est_verbe_mal_etiquete(verbe):
        return None

    # spaCy a traité le jeton en verbe et a produit autre chose que la forme fléchie : sa
    # réponse fait foi, elle couvre les irréguliers qu'aucune règle de suffixe n'atteindrait.
    lemme = verbe.lemma_.lower()
    if etiquete_verbe and lemme != verbe.text.lower():
        return lemme

    # Sinon la table de spaCy a rendu la main — POS erronée, ou lemme resté sur la forme
    # fléchie faute de la règle « -e ». On complète, et on garde son lemme en dernier
    # recours plutôt que de perdre l'action.
    return _lemme_verbal(verbe.text) or (lemme if etiquete_verbe else None)


def _groupe_nominal(tete, indices_exclus: frozenset[int] = frozenset()) -> str:
    """Reconstruit le groupe nominal d'une tête depuis son sous-arbre.

    Conserve l'ordre du texte et retire déterminants, ponctuation et nombres. Les
    prépositions **internes** sont gardées — « fiche *de* contrôle » — parce que les retirer
    ferait collisionner des syntagmes que rien ne rapproche. Celles de **tête et de queue**
    sont retirées : le sous-arbre de « hiérarchie » dans « remontés à la hiérarchie »
    embarque son « à », et « à hiérarchie » n'est pas un terme du domaine.

    `indices_exclus` porte les jetons déjà consommés par une `Grandeur`. Ce n'est pas un
    raffinement : sur « valide chaque fiche de contrôle sous 48 heures », `fr_core_news_lg`
    rattache « heures » en `nmod` de « contrôle », si bien que le sous-arbre de « fiche »
    avale la quantité et produit « fiche de contrôle sous heures ». Filtrer le groupe fini
    ne suffirait pas — il faut retirer les jetons avant de le reconstruire.
    """
    jetons = [
        jeton
        for jeton in tete.subtree
        if jeton.pos_ not in ("DET", "PUNCT", "NUM")
        and jeton.i not in indices_exclus
        and not jeton.is_space
    ]
    jetons.sort(key=lambda t: t.i)

    # Rogner prépositions et adverbes aux deux bouts. En queue, ce sont les orphelins
    # laissés par le retrait d'une quantité : « fiche de contrôle sous » -> « fiche de
    # contrôle ».
    while jetons and jetons[0].pos_ in ("ADP", "ADV"):
        jetons.pop(0)
    while jetons and jetons[-1].pos_ in ("ADP", "ADV"):
        jetons.pop()

    return " ".join(jeton.text for jeton in jetons).strip()


def indices_de_grandeurs(doc, surfaces: frozenset[str]) -> frozenset[int]:
    """Les indices des jetons couverts par un empan de `Grandeur`.

    Localise chaque surface dans le texte de la clause et convertit l'empan de caractères
    en jetons. `alignment_mode="expand"` absorbe les frontières qui ne tombent pas
    exactement sur un jeton.
    """
    indices: set[int] = set()
    for surface in surfaces:
        if not surface:
            continue
        depart = 0
        while (position := doc.text.find(surface, depart)) != -1:
            empan = doc.char_span(position, position + len(surface), alignment_mode="expand")
            if empan is not None:
                indices.update(jeton.i for jeton in empan)
            depart = position + 1
    return frozenset(indices)


def indices_de_roles(doc, surfaces: frozenset[str]) -> frozenset[int]:
    """Les indices des jetons couverts par un rôle du gazetteer.

    Pendant de :func:`indices_de_grandeurs`, mais l'appariement se fait sur la forme
    **normalisée**, jeton par jeton : le gazetteer écrit « chef d'atelier » là où un document
    écrit « Chef d'atelier », et spaCy découpe l'apostrophe en deux jetons. Un `find` littéral
    manquerait les deux cas.
    """
    mots = [normaliser_libelle(jeton.text) for jeton in doc]
    indices: set[int] = set()
    for surface in surfaces:
        cible = normaliser_libelle(surface).split()
        if not cible:
            continue
        for depart in range(len(mots) - len(cible) + 1):
            if mots[depart : depart + len(cible)] == cible:
                indices.update(range(depart, depart + len(cible)))
    return frozenset(indices)


def _sous_groupes(tete) -> list:
    """Les têtes des `nmod` d'un groupe : « port du casque » -> « casque ».

    C'est cette décomposition qui donne au pont ses points d'accroche : les syntagmes
    complets de deux documents ne se ressemblent presque jamais, leurs modifieurs si.
    """
    resultat = []
    for enfant in tete.children:
        if enfant.dep_ in ("nmod", "nmod:poss") and enfant.pos_ in _POS_PORTEUSES:
            resultat.append(enfant)
            resultat.extend(_sous_groupes(enfant))
    return resultat


def _est_recevable(libelle: str, tete) -> bool:
    """Écarte ce qui n'est pas du vocabulaire : nombres nus, mots vides, groupes vides."""
    if tete.pos_ not in _POS_PORTEUSES:
        return False
    normalise = normaliser_libelle(libelle)
    if len(normalise) < 3:
        return False
    if normalise.replace(" ", "").isdigit():
        return False
    return True


def objets_de(
    doc,
    surfaces_grandeurs: frozenset[str] = frozenset(),
    surfaces_acteurs: frozenset[str] = frozenset(),
) -> list[str]:
    """Les groupes nominaux d'une clause, syntagmes complets et têtes nues.

    `surfaces_grandeurs` porte les empans **littéraux** déjà consommés par une `Grandeur`
    (« 48 heures », « 85 dB(A) ») : ce sont des quantités réifiées en nœuds à part, pas du
    vocabulaire. Les voir aussi dans les concepts polluerait l'IDF et le canal conceptuel.

    `surfaces_acteurs` porte les rôles du gazetteer reconnus dans la clause, pour une raison
    voisine : un rôle est déjà un `Concept:Acteur`, le revoir en objet le compterait deux
    fois. Le paramètre est facultatif — sans lui, le module reste utilisable seul.

    ⚠️ Les deux ne s'appliquent **pas** de la même façon, et la différence est mesurée. Une
    grandeur se retire jeton par jeton avant reconstruction ; un rôle, non. Retirer ses
    jetons troue les groupes qui le contiennent sans être lui : « réseau des correspondants
    sécurité des ateliers » devenait « réseau des des ateliers », et « approuvée par le
    Directeur de site le 12 février » devenait « approuvée par février ». On écarte donc le
    seul groupe dont la **tête** tombe dans un rôle — celui qui *est* l'acteur — et on laisse
    intacts ceux qui ne font que l'inclure.
    """
    exclus = indices_de_grandeurs(doc, surfaces_grandeurs)
    tetes_acteurs = indices_de_roles(doc, surfaces_acteurs)
    normalisees = {normaliser_libelle(s) for s in surfaces_grandeurs}

    libelles: list[str] = []
    vus: set[str] = set()

    def retenir(libelle: str, tete) -> None:
        if tete.i in tetes_acteurs or not _est_recevable(libelle, tete):
            return
        cle = normaliser_libelle(libelle)
        if cle in vus or cle in normalisees:
            return
        vus.add(cle)
        libelles.append(libelle)

    for jeton in doc:
        if jeton.dep_ not in _RELATIONS_NOMINALES or jeton.pos_ not in _POS_PORTEUSES:
            continue
        if jeton.i in exclus:
            continue

        for tete in [jeton, *_sous_groupes(jeton)]:
            if tete.i in exclus:
                continue
            groupe = _groupe_nominal(tete, exclus)
            retenir(groupe, tete)
            # La tête nue, en plus du syntagme complet : « gants de manutention » donne
            # aussi « gants », « contrôle des EPI » donne aussi « contrôle ». C'est ce
            # niveau-là qui s'aligne d'un document à l'autre — les syntagmes complets,
            # presque jamais.
            if groupe and normaliser_libelle(groupe) != normaliser_libelle(tete.text):
                retenir(tete.text, tete)

    return libelles


# ------------------------------------------------------------------------ extraction


def _identifiant(libelle: str, type_concept: TypeConcept) -> str:
    """Identité déterministe d'un concept : son type et sa forme **de surface**.

    Déterministe et non aléatoire, parce que c'est la clé du `MERGE` : deux chargements
    successifs doivent viser exactement le même nœud, sinon l'idempotence tombe.

    ⚠️ La forme de surface, surtout pas la forme canonique lemmatisée. Clefer sur le lemme
    fusionnerait « fiche de contrôle » et « fiches de contrôle » **dès l'extraction**, en un
    seul nœud — et l'étage EXACT du pont (architecture.md §5.6, « identité normalisée →
    ALIAS_DE {EXACT, 1.00} ») n'aurait plus rien à relier. Le rapprochement doit rester
    visible sous forme d'arête, parce que c'est une hypothèse d'alignement que l'auditeur
    doit pouvoir réviser, pas une fusion silencieuse.
    """
    return f"{type_concept.value}:{normaliser_libelle(libelle)}"


def extraire_vocabulaire(
    segmentations: dict[str, Segmentation],
    frames: dict[str, ClauseFrame] | None = None,
    nlp=None,
) -> Vocabulaire:
    """Le vocabulaire de tout le corpus, avec l'IDF de chaque concept.

    `frames` sert uniquement à écarter les empans déjà consommés par une grandeur ; il est
    facultatif pour que le module reste utilisable seul.
    """
    if nlp is None:
        from cohera.ingestion.phrases import analyseur

        nlp = analyseur()

    clauses: list[tuple[str, Clause]] = [
        (doc_id, clause)
        for doc_id, segmentation in segmentations.items()
        for clause in segmentation.clauses
    ]
    docs = list(nlp.pipe(clause.texte_autonome for _, clause in clauses))

    concepts: dict[str, Concept] = {}
    mentions: list[Mention] = []
    clauses_par_concept: dict[str, set[str]] = defaultdict(set)

    for (doc_id, clause), doc in zip(clauses, docs):
        exclues = _surfaces_de_grandeurs(frames, clause.clause_id)
        trouves: list[tuple[str, TypeConcept]] = []

        roles = acteurs_de(clause.texte_autonome)
        trouves += [(role, TypeConcept.ACTEUR) for role in roles]

        action = action_de(doc)
        if action:
            trouves.append((action, TypeConcept.ACTION))

        deja_acteurs = {normaliser_libelle(r) for r, _ in trouves}
        for libelle in objets_de(doc, exclues, frozenset(roles)):
            if normaliser_libelle(libelle) not in deja_acteurs:
                trouves.append((libelle, TypeConcept.OBJET))

        for libelle, type_concept in trouves:
            concept_id = _identifiant(libelle, type_concept)
            concept = concepts.get(concept_id)
            if concept is None:
                concept = Concept(
                    concept_id=concept_id,
                    libelle=libelle,
                    libelle_canonique=forme_canonique(libelle, nlp=nlp),
                    type=type_concept,
                )
                concepts[concept_id] = concept
            concept.frequence += 1
            if doc_id not in concept.doc_ids:
                concept.doc_ids.append(doc_id)
            clauses_par_concept[concept_id].add(clause.clause_id)
            mentions.append(
                Mention(clause_id=clause.clause_id, concept_id=concept_id, role=type_concept)
            )

    _calculer_idf(concepts, clauses_par_concept, nb_clauses=len(clauses))
    return Vocabulaire(concepts=concepts, mentions=mentions)


def _surfaces_de_grandeurs(
    frames: dict[str, ClauseFrame] | None, clause_id: str
) -> frozenset[str]:
    """Les empans **littéraux** consommés par une `Grandeur` dans une clause.

    Littéraux et non normalisés : ils servent à localiser les jetons dans le texte, ce qui
    exige la graphie d'origine. La normalisation est refaite en aval, là où elle sert.
    """
    if not frames or clause_id not in frames:
        return frozenset()
    return frozenset(
        grandeur.surface for grandeur in frames[clause_id].quantites if grandeur.surface
    )


def _calculer_idf(
    concepts: dict[str, Concept],
    clauses_par_concept: dict[str, set[str]],
    nb_clauses: int,
) -> None:
    """IDF classique, en base logarithmique naturelle.

    Le canal 3 du J4 ne retient que `idf > 1,5` : un concept présent partout (« site »,
    « document ») ne dit rien de ce dont une clause parle, et l'apparier coûterait cher
    pour rien.
    """
    for concept_id, concept in concepts.items():
        portant = len(clauses_par_concept.get(concept_id, ())) or 1
        concept.idf = math.log(nb_clauses / portant) if nb_clauses else 0.0
