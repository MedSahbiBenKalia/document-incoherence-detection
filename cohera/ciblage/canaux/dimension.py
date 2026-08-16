"""Canal 5 — dimension seule. Le rattrapage du vocabulaire disjoint.

Cas pilote I12 : aucun mot commun, cos ~0,67 sous le seuil, seule l'égalité de
dimension et de rôle (un délai contre un délai) apparie la paire. Cas négatif
N08 : le canal apparie, et c'est à la cascade de rejeter.

**Le principe.** Deux clauses qui fixent un délai pour deux choses apparemment différentes
méritent un coup d'œil, même sans un mot en commun — parce qu'un délai est rare et qu'un
corpus n'en contient qu'une poignée par rôle. Mesuré ici : 31 grandeurs sur 78 clauses, dont
12 délais et 8 périodicités.

**Sans seuil de similarité, et c'est tout le point.** Le cosinus ne sert qu'à ordonner :
appliquer un seuil ici reviendrait à refaire le canal 4 et à reperdre exactement les paires
que ce canal existe pour rattraper. Le budget est tenu par le top-N par clause, pas par un
seuil.

**Ce que la mesure a établi sur I12.** D1 §6.2 (« sous 24 heures ») a quatre partenaires de
même dimension et même rôle dans D2 après exclusion des valeurs égales. D2 §6.2 (« dans la
semaine ») y arrive **au rang 3 sur 4**, à 0,009 du rang 4. La paire tient donc au top-3 de
justesse : c'est une fragilité réelle, figée par un test dédié, et le premier endroit à
regarder si le rappel du ciblage bouge.

**Sous-correctif indispensable (CAP04).** Le canal ne voit une clause que si une grandeur y a
été extraite : « dans la semaine » doit produire une Quantite `TEMPS / delai` au drapeau
IMPRECIS. Vérifié au J2 — sans elle, D2 §6.2 n'existe pas pour ce canal et I12 est perdue.
"""

from __future__ import annotations

from neo4j import Session

from cohera.ciblage import config_ciblage
from cohera.ciblage.canaux import classer
from cohera.ciblage.modeles import Appariement, Canal


def requete() -> str:
    """Le Cypher du canal 5 (architecture.md §6.5). Fonction pure.

    Trois écarts assumés au Cypher de l'architecture, tous les trois nécessaires :

    * ``a.doc_id <> b.doc_id`` au lieu de ``<`` — le top-N doit être calculé **par clause,
      des deux côtés**, sinon seules les clauses de D1 auraient droit à leurs trois
      meilleurs partenaires. La clé non ordonnée de la fusion refusionne les doublons.
    * ``LIMIT 3`` remplacé par une découpe ``[0..$top_n]`` après regroupement — le ``LIMIT``
      global du texte d'architecture ne garderait que trois paires pour tout le corpus,
      là où le commentaire du même paragraphe dit « top-3 **par clause** ».
    * ``valeur_si IS NOT NULL`` — une grandeur AMBIGU (bimensuel/bimestriel) n'a pas de
      valeur tranchée ; la comparer reviendrait à inventer un écart ou une égalité.
    """
    return (
        "MATCH (a:Clause)-[:PORTE]->(qa:Quantite), (b:Clause)-[:PORTE]->(qb:Quantite)\n"
        "WHERE a.doc_id <> b.doc_id\n"
        "  AND qa.dimension = qb.dimension AND qa.role = qb.role\n"
        "  AND qa.valeur_si IS NOT NULL AND qb.valeur_si IS NOT NULL\n"
        "  AND qa.valeur_si <> qb.valeur_si\n"
        "  AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL\n"
        "WITH DISTINCT a, b, vector.similarity.cosine(a.embedding, b.embedding) AS score\n"
        "ORDER BY a.clause_id, score DESC\n"
        "WITH a, collect({clause_b: b.clause_id, score: score})[0..$top_n] AS voisins\n"
        "UNWIND voisins AS voisin\n"
        "RETURN a.clause_id AS clause_a, voisin.clause_b AS clause_b, voisin.score AS score"
    )


def apparier(session: Session) -> list[Appariement]:
    """Les ``top_n`` partenaires de même grandeur de chaque clause, sans seuil.

    Le score renvoyé par Neo4j est normalisé ; on le reconvertit en cosinus brut pour rester
    sur l'échelle unique du projet. Ici la conversion ne change aucun classement — elle est
    monotone — mais un score de canal qui ne serait pas sur la même échelle que les autres
    serait un piège pour quiconque lira les rangs.
    """
    from cohera.ciblage.canaux.vectoriel import cosinus_brut

    brut = [
        (
            enregistrement["clause_a"],
            enregistrement["clause_b"],
            cosinus_brut(float(enregistrement["score"])),
        )
        for enregistrement in session.run(
            requete(), top_n=config_ciblage.top_n_dimension()
        )
    ]
    return classer(brut, Canal.DIMENSION)
