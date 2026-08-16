"""Canal 2 — clé de comparaison. Coût nul, précision très élevée.

Deux clauses partageant (concept, dimension, rôle) sont appariées sans calcul.

La clé est calculée au chargement par `graphe/chargeur.py::cle_comparaison` et stockée sur
la clause : ce canal n'est qu'une égalité de chaînes, sans le moindre modèle. C'est ce qui
lui vaut son poids de 3,0 dans la fusion et son exemption du plafond par clause.

**Mesuré sur les fixtures : une seule paire, D1 §4.2 / D2 §4.2 (I01).** `label.json` déclare
pourtant `CLE` dans le `canal_attendu` de I02, I13, I14 et I15. L'écart est réel et
consigné : leurs clés divergent sur la position acteur ou objet. Il ne coûte aucun rappel —
les quatre remontent par d'autres canaux — et se corrigerait en amont, dans la clé du J3,
pas en relâchant l'égalité ici.
"""

from __future__ import annotations

from neo4j import Session

from cohera.ciblage.canaux import classer
from cohera.ciblage.modeles import Appariement, Canal


def requete() -> str:
    """Le Cypher du canal 2 (architecture.md §6.2).

    Fonction pure : aucune valeur métier n'y est interpolée, donc rien à paramétrer. Le
    garde-fou ``a.cle_comparaison <> ''`` écarte le cas dégénéré d'une clause dont aucune
    position n'a pu être remplie — deux clés vides seraient « égales » et apparieraient deux
    clauses qui n'ont rien en commun.
    """
    return (
        "MATCH (a:Clause)-[:PORTE]->(qa:Quantite), (b:Clause)-[:PORTE]->(qb:Quantite)\n"
        "WHERE a.doc_id < b.doc_id\n"
        "  AND a.cle_comparaison = b.cle_comparaison\n"
        "  AND a.cle_comparaison <> ''\n"
        "  AND qa.dimension = qb.dimension AND qa.role = qb.role\n"
        "RETURN DISTINCT a.clause_id AS clause_a, b.clause_id AS clause_b, 1.0 AS score"
    )


def apparier(session: Session) -> list[Appariement]:
    """Les paires de clés identiques, toutes au même score : l'égalité ne se nuance pas."""
    brut = [
        (enregistrement["clause_a"], enregistrement["clause_b"], float(enregistrement["score"]))
        for enregistrement in session.run(requete())
    ]
    return classer(brut, Canal.CLE)
