"""Étage C — le LLM juge, conditionné par le graphe.

Invariant : aucun verdict sans preuve littérale. `preuve_a` et `preuve_b`
doivent être des sous-chaînes exactes de `texte_source`, vérifiées en Python
APRÈS l'appel. I11 est le cas qui justifie cet étage : aucune grandeur, aucun
conflit déontique, seul le sens permet de trancher."""
