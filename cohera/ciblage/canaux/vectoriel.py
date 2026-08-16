"""Canal 4 — k plus proches voisins sur les embeddings. Le filet de sécurité.

Passe par `cohera.graphe.compat.recherche_vectorielle`. Piégé par N02 et N03 :
similarité élevée sans rapport réel — d'où les filtres en amont.

**L'échelle.** L'index vectoriel de Neo4j rend un score NORMALISÉ dans [0, 1], égal à
``(1 + cos) / 2``. Le reste du projet — `graphe/alias.py`, `config/lexique_qhse.yaml`,
`corpus/fixtures/label.json` — raisonne en **cosinus brut**. La conversion est faite ici,
une fois, par :func:`cosinus_brut`, et le seuil de `config/ciblage.yaml` s'applique après.
Comparer directement le score de l'index à un seuil pensé en cosinus brut — ce que fait le
Cypher de architecture.md §6.4 — laisse passer 81 % du corpus.

**Le k demandé à l'index est volontairement large.** L'index ignore `doc_id` : les voisins
d'une clause de D1 sont majoritairement dans D1, et le filtrage inter-documents n'intervient
qu'après. Un ``k`` serré dépenserait donc ses voisins dans le document d'origine et perdrait
du rappel sans qu'aucun test ne le montre — d'où `k_voisins` en configuration, et le test
qui vérifie que I08, dont c'est le seul canal, en ressort bien.
"""

from __future__ import annotations

from neo4j import Session

from cohera.ciblage import config_ciblage
from cohera.ciblage.canaux import classer
from cohera.ciblage.modeles import Appariement, Canal
from cohera.graphe.compat import recherche_vectorielle

#: Nom de l'index vectoriel des clauses, créé par `graphe/schema.cypher`.
INDEX_CLAUSES = "clause_vec"


def cosinus_brut(score_index: float) -> float:
    """Convertit un score d'index Neo4j en cosinus brut.

    Neo4j normalise : ``score = (1 + cos) / 2``. L'inverse est donc ``cos = 2·score - 1``.
    Fonction pure, testée hors ligne — c'est la seule ligne du canal qui puisse fausser
    silencieusement tous les seuils.
    """
    return 2.0 * score_index - 1.0


def requete_clauses() -> str:
    """Le Cypher qui rend les vecteurs à interroger. Fonction pure, sans valeur métier.

    Les clauses sans embedding sont écartées ici plutôt qu'au moment de l'appel : une
    recherche vectorielle sur un vecteur nul lèverait, et un chargement fait avec
    ``avec_embeddings=False`` est un cas de test légitime, pas une erreur.
    """
    return (
        "MATCH (c:Clause)\n"
        "WHERE c.embedding IS NOT NULL\n"
        "RETURN c.clause_id AS clause_id, c.doc_id AS doc_id, c.embedding AS embedding\n"
        "ORDER BY c.clause_id"
    )


def apparier(session: Session) -> list[Appariement]:
    """Les voisins inter-documents de chaque clause, au-dessus du seuil de cosinus brut."""
    seuil = config_ciblage.seuil_vectoriel()
    k = config_ciblage.k_voisins()

    clauses = list(session.run(requete_clauses()))
    brut: list[tuple[str, str, float]] = []

    for clause in clauses:
        voisins = recherche_vectorielle(
            INDEX_CLAUSES, k, clause["embedding"], session=session
        )
        for noeud, score_index in voisins:
            if noeud["doc_id"] == clause["doc_id"]:
                continue
            cosinus = cosinus_brut(float(score_index))
            if cosinus >= seuil:
                brut.append((clause["clause_id"], noeud["clause_id"], cosinus))

    return classer(brut, Canal.VECTORIEL)
