// Schéma du graphe COHERA : contraintes, index de filtrage, plein texte, vectoriels.
//
// Recopié de docs/architecture.md §5.5. Tout est en IF NOT EXISTS : rejouer ce fichier
// est sans effet, c'est la première moitié de l'idempotence du chargement (CLAUDE.md,
// « Neo4j : MERGE, jamais CREATE »). La seconde moitié est dans chargeur.py.
//
// L'index vectoriel créé ici est celui qu'interroge
// cohera/graphe/compat.py::recherche_vectorielle. __DIMENSION__ est substitué au
// chargement par embeddings.dimension de config/technique.yaml : la dimension de l'index
// et celle du modèle ne peuvent donc pas diverger. Les écrire toutes deux en dur, c'était
// se réserver une panne au J4 à l'insertion du premier vecteur.
//
// Les instructions sont séparées par « ; » et lues par cohera/graphe/schema.py, qui
// ignore les commentaires. Ne pas mettre de « ; » dans un commentaire.

// ─── Contraintes d'unicité (créent les index) ───────────────────────────────
CREATE CONSTRAINT doc_id      IF NOT EXISTS FOR (d:Document)    REQUIRE d.doc_id       IS UNIQUE;
CREATE CONSTRAINT section_id  IF NOT EXISTS FOR (s:Section)     REQUIRE s.section_id   IS UNIQUE;
CREATE CONSTRAINT clause_id   IF NOT EXISTS FOR (c:Clause)      REQUIRE c.clause_id    IS UNIQUE;
CREATE CONSTRAINT concept_id  IF NOT EXISTS FOR (k:Concept)     REQUIRE k.concept_id   IS UNIQUE;
CREATE CONSTRAINT cond_id     IF NOT EXISTS FOR (x:Condition)   REQUIRE x.condition_id IS UNIQUE;
CREATE CONSTRAINT quantite_id IF NOT EXISTS FOR (q:Quantite)    REQUIRE q.quantite_id  IS UNIQUE;
CREATE CONSTRAINT norme_code  IF NOT EXISTS FOR (n:NormeExterne) REQUIRE (n.code, n.version) IS UNIQUE;
CREATE CONSTRAINT exig_ref    IF NOT EXISTS FOR (e:ExigenceExterne) REQUIRE (e.reference, e.source) IS UNIQUE;
CREATE CONSTRAINT const_id    IF NOT EXISTS FOR (f:Constatation) REQUIRE f.constatation_id IS UNIQUE;

// ─── Index de filtrage ──────────────────────────────────────────────────────
CREATE INDEX clause_doc      IF NOT EXISTS FOR (c:Clause)   ON (c.doc_id);
CREATE INDEX clause_modalite IF NOT EXISTS FOR (c:Clause)   ON (c.modalite);
CREATE INDEX clause_cle      IF NOT EXISTS FOR (c:Clause)   ON (c.cle_comparaison);
CREATE INDEX clause_validite IF NOT EXISTS FOR (c:Clause)   ON (c.date_debut_validite, c.date_fin_validite);
CREATE INDEX doc_statut      IF NOT EXISTS FOR (d:Document) ON (d.statut, d.niveau_hierarchique);
CREATE INDEX qte_dim         IF NOT EXISTS FOR (q:Quantite) ON (q.dimension, q.role);
CREATE INDEX cond_type       IF NOT EXISTS FOR (x:Condition) ON (x.type);
CREATE INDEX const_statut    IF NOT EXISTS FOR (f:Constatation) ON (f.statut, f.criticite);
CREATE INDEX concept_canon   IF NOT EXISTS FOR (k:Concept)  ON (k.libelle_canonique);

// ─── Index plein texte (canal lexical) ──────────────────────────────────────
CREATE FULLTEXT INDEX clause_ft IF NOT EXISTS
FOR (c:Clause) ON EACH [c.texte_autonome]
OPTIONS { indexConfig: { `fulltext.analyzer`: 'french' } };

// ─── Index vectoriels ───────────────────────────────────────────────────────
CREATE VECTOR INDEX clause_vec IF NOT EXISTS
FOR (c:Clause) ON (c.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: __DIMENSION__, `vector.similarity_function`: 'cosine' }};

CREATE VECTOR INDEX concept_vec IF NOT EXISTS
FOR (k:Concept) ON (k.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: __DIMENSION__, `vector.similarity_function`: 'cosine' }};

CREATE VECTOR INDEX condition_vec IF NOT EXISTS
FOR (x:Condition) ON (x.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: __DIMENSION__, `vector.similarity_function`: 'cosine' }};
