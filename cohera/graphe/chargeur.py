"""Chargement du corpus dans Neo4j.

Invariant : MERGE, jamais CREATE. Le chargement doit être idempotent — on doit
pouvoir le rejouer sans dupliquer un seul nœud."""
