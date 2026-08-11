"""Chargement du corpus dans Neo4j.

Invariant : **MERGE, jamais CREATE**. Le chargement doit être idempotent — on doit pouvoir
le rejouer sans dupliquer un seul nœud (`CLAUDE.md`). Le critère du J3 est vérifiable :
deux chargements successifs donnent le même nombre de nœuds *et* d'arêtes, comptés par
label et par type de relation.

**Ce qui rend l'idempotence vraie plutôt que probable.** Chaque nœud a une identité
déterministe, calculée à partir de son contenu :

* `Clause` / `Section` / `Document` — l'identifiant déjà produit par L0 ;
* `Concept` — son type et sa forme de surface normalisée (`concepts.py`) ;
* `Quantite` — `clause_id::Qn` : une grandeur appartient à sa clause, la numéroter dans son
  ordre d'extraction suffit et reste stable ;
* `Condition` — l'empreinte de sa surface normalisée et de son type, **sans** le
  `clause_id` : les conditions se dédupliquent volontairement à travers tout le corpus,
  c'est le rendement décrit en architecture.md §5.7 (un corpus de 2 000 clauses ne contient
  que 60 à 120 conditions distinctes, et le recouvrement se calcule une fois par paire de
  conditions au lieu d'une fois par paire de clauses).

Un identifiant aléatoire ou horodaté, ici, casserait tout : le second chargement viserait
d'autres nœuds et les compteurs doubleraient.
"""

from __future__ import annotations

import hashlib

from neo4j import Session
from pydantic import BaseModel, Field

from cohera import embeddings
from cohera.extraction.frames import ClauseFrame
from cohera.graphe.alias import Pont
from cohera.graphe.concepts import TypeConcept, Vocabulaire
from cohera.graphe.libelles import normaliser_libelle
from cohera.ingestion.modeles import Segmentation

#: Joker en position acteur d'une clé de comparaison (architecture.md §5.8).
JOKER_ACTEUR = "*"


class Bilan(BaseModel):
    """Comptage du graphe, par label et par type de relation."""

    noeuds: dict[str, int] = Field(default_factory=dict)
    aretes: dict[str, int] = Field(default_factory=dict)

    @property
    def total_noeuds(self) -> int:
        return sum(self.noeuds.values())

    @property
    def total_aretes(self) -> int:
        return sum(self.aretes.values())


def condition_id(surface: str, type_condition: str) -> str:
    """Identité d'une condition : son empreinte, indépendante de la clause qui la porte."""
    graine = f"{type_condition}\0{normaliser_libelle(surface)}".encode("utf-8")
    return f"C{hashlib.sha256(graine).hexdigest()[:16]}"


# ------------------------------------------------------------------- clé de comparaison


def cle_comparaison(
    clause_id: str,
    frames: dict[str, ClauseFrame],
    vocabulaire: Vocabulaire,
    pont: Pont,
) -> str:
    """La signature de ce dont parle une clause, en canoniques (architecture.md §5.8).

    ``(acteur, action, objet, dimension, role)``, chaque terme remplacé par le représentant
    canonique de sa classe d'équivalence — c'est ce qui permet à une clause parlant du
    « Responsable QSE » de rencontrer une clause parlant du « Référent sécurité ».

    Deux choix à connaître, tous deux simplificateurs et assumés pour le J3 :

    * l'acteur absent devient ``*``, le joker des tournures passives ;
    * l'objet retenu est celui de **plus fort IDF** parmi les concepts de la clause, et non
      le premier rencontré. Le plus discriminant est le plus stable : « site » ou
      « document » apparaissent partout et ne signeraient rien.
    """
    concepts = vocabulaire.concepts_de(clause_id)

    def canonique(concept) -> str:
        racine = pont.canoniques.get(concept.concept_id, concept.concept_id)
        cible = vocabulaire.concepts.get(racine)
        return normaliser_libelle(cible.libelle if cible else concept.libelle)

    acteurs = [c for c in concepts if c.type is TypeConcept.ACTEUR]
    actions = [c for c in concepts if c.type is TypeConcept.ACTION]
    objets = [c for c in concepts if c.type is TypeConcept.OBJET]

    acteur = canonique(acteurs[0]) if acteurs else JOKER_ACTEUR
    action = canonique(actions[0]) if actions else ""
    objet = canonique(max(objets, key=lambda c: (c.idf, c.libelle))) if objets else ""

    frame = frames.get(clause_id)
    grandeur = frame.quantites[0] if frame and frame.quantites else None
    dimension = grandeur.dimension.value if grandeur else ""
    role = grandeur.role if grandeur else ""

    return "|".join((acteur, action, objet, dimension, role))


# ------------------------------------------------------------------------ chargement


def charger(
    segmentations: dict[str, Segmentation],
    frames: dict[str, ClauseFrame],
    vocabulaire: Vocabulaire,
    pont: Pont,
    session: Session | None = None,
    *,
    avec_embeddings: bool = True,
) -> Bilan:
    """Écrit tout le corpus dans Neo4j et renvoie le comptage résultant."""
    if session is None:
        from cohera.graphe.connexion import session as ouvrir_session

        with ouvrir_session() as sess:
            return charger(
                segmentations, frames, vocabulaire, pont, sess,
                avec_embeddings=avec_embeddings,
            )

    from cohera.graphe.schema import appliquer

    appliquer(session)

    _charger_documents(session, segmentations)
    _charger_clauses(session, segmentations, frames, vocabulaire, pont, avec_embeddings)
    _charger_concepts(session, vocabulaire, avec_embeddings)
    _charger_mentions(session, vocabulaire)
    _charger_quantites(session, frames)
    _charger_conditions(session, frames)
    _charger_alias(session, pont)
    _charger_normes(session, frames)

    return compter(session)


def _charger_documents(session: Session, segmentations: dict[str, Segmentation]) -> None:
    documents = []
    sections = []
    for doc_id, segmentation in segmentations.items():
        doc = segmentation.document
        documents.append(
            {
                "doc_id": doc_id,
                "code": doc.code,
                "titre": doc.titre,
                "type": doc.type,
                "niveau_hierarchique": doc.niveau_hierarchique,
                "version": doc.version,
                "date_application": doc.date_application.isoformat()
                if doc.date_application
                else None,
                "statut": doc.statut,
                "fichier": doc.fichier,
            }
        )
        sections += [
            {
                "doc_id": doc_id,
                "section_id": s.section_id,
                "numero": s.numero,
                "titre": s.titre,
                "niveau": s.niveau,
            }
            for s in doc.sections
        ]

    session.run(
        """
        UNWIND $documents AS d
        MERGE (n:Document {doc_id: d.doc_id})
        SET n.code = d.code, n.titre = d.titre, n.type = d.type,
            n.niveau_hierarchique = d.niveau_hierarchique, n.version = d.version,
            n.date_application = d.date_application, n.statut = d.statut,
            n.fichier = d.fichier
        """,
        documents=documents,
    )
    session.run(
        """
        UNWIND $sections AS s
        MERGE (n:Section {section_id: s.section_id})
        SET n.numero = s.numero, n.titre = s.titre, n.niveau = s.niveau, n.doc_id = s.doc_id
        WITH n, s
        MATCH (d:Document {doc_id: s.doc_id})
        MERGE (d)-[:CONTIENT]->(n)
        """,
        sections=sections,
    )


def _charger_clauses(
    session: Session,
    segmentations: dict[str, Segmentation],
    frames: dict[str, ClauseFrame],
    vocabulaire: Vocabulaire,
    pont: Pont,
    avec_embeddings: bool,
) -> None:
    lignes = []
    for doc_id, segmentation in segmentations.items():
        sections = {s.numero: s.section_id for s in segmentation.document.sections}
        for clause in segmentation.clauses:
            frame = frames.get(clause.clause_id)
            lignes.append(
                {
                    "clause_id": clause.clause_id,
                    "doc_id": doc_id,
                    "ref": clause.ref,
                    "ordre": clause.ordre,
                    "texte_source": clause.texte_source,
                    "texte_autonome": clause.texte_autonome,
                    "debut": clause.debut,
                    "fin": clause.fin,
                    "origine": clause.origine.value,
                    "hash": clause.hash,
                    "autonomise": clause.autonomise,
                    "type_enonce": frame.type_enonce.value if frame and frame.type_enonce else None,
                    "modalite": frame.modalite.value if frame and frame.modalite else None,
                    "force": frame.force if frame else None,
                    "negation": frame.negation if frame else False,
                    "date_debut_validite": _iso(frame, "debut"),
                    "date_fin_validite": _iso(frame, "fin"),
                    "cle_comparaison": cle_comparaison(
                        clause.clause_id, frames, vocabulaire, pont
                    ),
                    "section_id": sections.get(clause.ref.split(".")[0]),
                }
            )

    if avec_embeddings:
        vecteurs = embeddings.encoder([ligne["texte_autonome"] for ligne in lignes])
        for ligne, vecteur in zip(lignes, vecteurs):
            ligne["embedding"] = [float(x) for x in vecteur]
    else:
        for ligne in lignes:
            ligne["embedding"] = None

    session.run(
        """
        UNWIND $clauses AS c
        MERGE (n:Clause {clause_id: c.clause_id})
        SET n.doc_id = c.doc_id, n.ref = c.ref, n.ordre = c.ordre,
            n.texte_source = c.texte_source, n.texte_autonome = c.texte_autonome,
            n.debut = c.debut, n.fin = c.fin, n.origine = c.origine, n.hash = c.hash,
            n.autonomise = c.autonomise, n.type_enonce = c.type_enonce,
            n.modalite = c.modalite, n.force = c.force, n.negation = c.negation,
            n.date_debut_validite = c.date_debut_validite,
            n.date_fin_validite = c.date_fin_validite,
            n.cle_comparaison = c.cle_comparaison, n.embedding = c.embedding
        WITH n, c
        MATCH (s:Section {section_id: c.section_id})
        MERGE (s)-[:CONTIENT]->(n)
        """,
        clauses=lignes,
    )

    # Ordre de lecture : SUIT relie chaque clause à la suivante du même document.
    suites = []
    for segmentation in segmentations.values():
        clauses = sorted(segmentation.clauses, key=lambda c: c.ordre)
        suites += [
            {"de": a.clause_id, "vers": b.clause_id} for a, b in zip(clauses, clauses[1:])
        ]
    session.run(
        """
        UNWIND $suites AS s
        MATCH (a:Clause {clause_id: s.de}), (b:Clause {clause_id: s.vers})
        MERGE (a)-[:SUIT]->(b)
        """,
        suites=suites,
    )


def _iso(frame: ClauseFrame | None, borne: str) -> str | None:
    if not frame or not frame.validite:
        return None
    valeur = getattr(frame.validite, borne, None)
    return valeur.isoformat() if valeur else None


def _charger_concepts(session: Session, vocabulaire: Vocabulaire, avec_embeddings: bool) -> None:
    concepts = list(vocabulaire.concepts.values())
    lignes = [
        {
            "concept_id": c.concept_id,
            "libelle": c.libelle,
            "libelle_canonique": c.libelle_canonique,
            "type": c.type.value,
            "idf": c.idf,
            "frequence": c.frequence,
        }
        for c in concepts
    ]
    if avec_embeddings and lignes:
        vecteurs = embeddings.encoder([c.libelle for c in concepts])
        for ligne, vecteur in zip(lignes, vecteurs):
            ligne["embedding"] = [float(x) for x in vecteur]
    else:
        for ligne in lignes:
            ligne["embedding"] = None

    session.run(
        """
        UNWIND $concepts AS k
        MERGE (n:Concept {concept_id: k.concept_id})
        SET n.libelle = k.libelle, n.libelle_canonique = k.libelle_canonique,
            n.type = k.type, n.idf = k.idf, n.frequence = k.frequence,
            n.embedding = k.embedding
        """,
        concepts=lignes,
    )
    # Sous-label des acteurs (architecture.md §5.1) : `SET` est idempotent, réappliquer un
    # label déjà posé ne crée rien.
    session.run(
        """
        UNWIND $ids AS cid
        MATCH (n:Concept {concept_id: cid})
        SET n:Acteur
        """,
        ids=[c.concept_id for c in concepts if c.type is TypeConcept.ACTEUR],
    )


def _charger_mentions(session: Session, vocabulaire: Vocabulaire) -> None:
    session.run(
        """
        UNWIND $mentions AS m
        MATCH (c:Clause {clause_id: m.clause_id}), (k:Concept {concept_id: m.concept_id})
        MERGE (c)-[r:MENTIONNE]->(k)
        SET r.role = m.role, r.poids = m.poids
        """,
        mentions=[
            {
                "clause_id": m.clause_id,
                "concept_id": m.concept_id,
                "role": m.role.value,
                "poids": m.poids,
            }
            for m in vocabulaire.mentions
        ],
    )


def _charger_quantites(session: Session, frames: dict[str, ClauseFrame]) -> None:
    lignes = [
        {
            "quantite_id": f"{clause_id}::Q{indice:02d}",
            "clause_id": clause_id,
            "role": g.role,
            "dimension": g.dimension.value,
            "valeur": g.valeur,
            "unite": g.unite,
            "valeur_si": g.valeur_si,
            "valeur_si_calendaire": g.valeur_si_calendaire,
            "operateur": g.operateur.value,
            "surface": g.surface,
            "monotonie": g.monotonie.value,
            "statut": g.statut.value,
        }
        for clause_id, frame in frames.items()
        for indice, g in enumerate(frame.quantites)
    ]
    session.run(
        """
        UNWIND $quantites AS q
        MERGE (n:Quantite {quantite_id: q.quantite_id})
        SET n.role = q.role, n.dimension = q.dimension, n.valeur = q.valeur,
            n.unite = q.unite, n.valeur_si = q.valeur_si,
            n.valeur_si_calendaire = q.valeur_si_calendaire, n.operateur = q.operateur,
            n.surface = q.surface, n.monotonie = q.monotonie, n.statut = q.statut
        WITH n, q
        MATCH (c:Clause {clause_id: q.clause_id})
        MERGE (c)-[:PORTE]->(n)
        """,
        quantites=lignes,
    )


def _charger_conditions(session: Session, frames: dict[str, ClauseFrame]) -> None:
    lignes = [
        {
            "condition_id": condition_id(cond.surface, cond.type.value),
            "clause_id": clause_id,
            "surface": cond.surface,
            "type": cond.type.value,
            "concept_cible": cond.concept_cible,
            "operateur": cond.operateur,
            "valeur": cond.valeur,
        }
        for clause_id, frame in frames.items()
        for cond in frame.conditions
    ]
    session.run(
        """
        UNWIND $conditions AS x
        MERGE (n:Condition {condition_id: x.condition_id})
        SET n.surface = x.surface, n.type = x.type, n.concept_cible = x.concept_cible,
            n.operateur = x.operateur, n.valeur = x.valeur
        WITH n, x
        MATCH (c:Clause {clause_id: x.clause_id})
        MERGE (c)-[:SOUS_CONDITION]->(n)
        """,
        conditions=lignes,
    )


def _charger_alias(session: Session, pont: Pont) -> None:
    """Les arêtes ALIAS_DE, orientées de façon déterministe.

    `ALIAS_DE` est symétrique par nature, mais une arête Neo4j a un sens. On l'oriente du
    plus petit `concept_id` vers le plus grand : sans cet ordre, un second chargement
    pourrait créer l'arête inverse et doubler le compte.
    """
    session.run(
        """
        UNWIND $aliases AS a
        MATCH (x:Concept {concept_id: a.de}), (y:Concept {concept_id: a.vers})
        MERGE (x)-[r:ALIAS_DE]->(y)
        SET r.score = a.score, r.methode = a.methode
        """,
        aliases=[
            {
                "de": min(a.concept_a, a.concept_b),
                "vers": max(a.concept_a, a.concept_b),
                "score": a.score,
                "methode": a.methode.value,
            }
            for a in pont.aretes
        ],
    )


def _charger_normes(session: Session, frames: dict[str, ClauseFrame]) -> None:
    lignes = [
        {
            "clause_id": clause_id,
            "code": ref.cible,
            "version": ref.version or "",
        }
        for clause_id, frame in frames.items()
        for ref in frame.references
        if ref.type.value == "NORME"
    ]
    session.run(
        """
        UNWIND $normes AS n
        MERGE (x:NormeExterne {code: n.code, version: n.version})
        WITH x, n
        MATCH (c:Clause {clause_id: n.clause_id})
        MERGE (c)-[r:CITE_NORME]->(x)
        SET r.version_citee = n.version
        """,
        normes=lignes,
    )


# -------------------------------------------------------------------------- comptage


def compter(session: Session) -> Bilan:
    """Compte les nœuds par label et les arêtes par type.

    Par label et par type, jamais en total : deux erreurs qui se compensent — un `Concept`
    perdu, une `Condition` dupliquée — laisseraient un total inchangé et l'idempotence
    passerait au vert à tort.
    """
    noeuds = {
        enregistrement["label"]: enregistrement["n"]
        for enregistrement in session.run(
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS n ORDER BY label"
        )
    }
    aretes = {
        enregistrement["type"]: enregistrement["n"]
        for enregistrement in session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type"
        )
    }
    return Bilan(noeuds=noeuds, aretes=aretes)


def vider(session: Session) -> None:
    """Efface tous les nœuds et arêtes. Réservé aux tests — jamais appelé par le pipeline."""
    session.run("MATCH (n) DETACH DELETE n")
