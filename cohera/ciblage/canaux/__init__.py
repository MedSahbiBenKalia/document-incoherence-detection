"""Les cinq canaux de ciblage.

Chaque canal expose deux fonctions, selon la convention du dépôt (`graphe/compat.py`,
`graphe/schema.py`) :

* ``requete() -> str`` — **pure**, rend le Cypher, testable sans serveur ;
* ``apparier(session) -> list[Appariement]`` — exécute et classe.

**Le rang est global au canal, jamais local.** La fusion RRF consomme
``rang_c(a,b)``, « le rang de la paire dans la liste ordonnée du canal c » : c'est la
définition de la méthode. Un canal qui rendrait des rangs par clause (1, 2, 3 répétés pour
chaque clause) donnerait à toutes ses paires un poids quasi identique et écraserait le
signal que la fusion cherche justement à exploiter. Le top-3 par clause du canal 5 est donc
une règle de **sélection**, pas de classement : les paires sélectionnées sont ensuite
classées globalement par leur cosinus, comme partout ailleurs.
"""

from __future__ import annotations

from cohera.ciblage.modeles import Appariement, Canal, cle_paire


def classer(
    brut: list[tuple[str, str, float]], canal: Canal
) -> list[Appariement]:
    """Ordonne les propositions d'un canal par score décroissant et leur pose un rang.

    Déduplique au passage sur la clé non ordonnée : un canal qui voit une paire des deux
    côtés — le vectoriel interroge l'index clause par clause — ne doit la proposer qu'une
    fois, avec son meilleur score.

    Le tri secondaire porte sur les identifiants : à score égal, l'ordre doit être
    déterministe, sinon deux exécutions du même ciblage produiraient des rangs différents et
    donc des scores de fusion différents.
    """
    meilleurs: dict[tuple[str, str], tuple[str, str, float]] = {}
    for clause_a, clause_b, score in brut:
        cle = cle_paire(clause_a, clause_b)
        precedent = meilleurs.get(cle)
        if precedent is None or score > precedent[2]:
            meilleurs[cle] = (cle[0], cle[1], score)

    ordonnees = sorted(meilleurs.values(), key=lambda t: (-t[2], t[0], t[1]))
    return [
        Appariement(clause_a=a, clause_b=b, canal=canal, score=score, rang=rang)
        for rang, (a, b, score) in enumerate(ordonnees, start=1)
    ]
