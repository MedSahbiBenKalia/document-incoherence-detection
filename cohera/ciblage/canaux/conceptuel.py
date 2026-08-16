"""Canal 3 — conceptuel à deux sauts. Le canal principal en rappel.

Clause -> Concept -> ALIAS_DE -> Concept -> Clause.

**Le saut par `ALIAS_DE` est ce qui rend les concepts « canoniques »** au sens de
architecture.md §6.3. Le graphe ne porte pas de propriété `canonique_id` : les classes
d'équivalence vivent en Python dans `Pont.canoniques`, et le graphe n'en garde que les
arêtes. Traverser l'arête est donc la façon d'interroger les canoniques sans dénormaliser
un champ de plus au chargement — c'est aussi ce qui permet à une clause parlant du
« Responsable QSE » de rencontrer une clause parlant du « Référent sécurité ».

**Deux concepts partagés au minimum.** Un seul suffirait à apparier des dizaines de clauses
par un terme générique ayant survécu au filtre d'IDF. C'est ce seuil que reprend, tel quel,
la branche conceptuelle du filtre de comparabilité.

Mesuré sur les fixtures : 40 paires, dont I01, I02, I04, I05, I11, I14 et I15. I12 en est
absente — aucun mot commun, aucun alias — et c'est ce qui fait d'elle le cas pilote du
canal 5.
"""

from __future__ import annotations

from neo4j import Session

from cohera.ciblage import config_ciblage
from cohera.ciblage.canaux import classer
from cohera.ciblage.modeles import Appariement, Canal


def requete(avec_pont: bool = True) -> str:
    """Le Cypher du canal 3 (architecture.md §6.3).

    Fonction pure. ``idf_min`` et ``partages_min`` restent des **paramètres** ``$``, jamais
    interpolés : ce sont des valeurs métier, elles vivent dans `config/ciblage.yaml`.
    ``avec_pont`` n'est pas une valeur métier mais une variante de requête — d'où le choix
    d'une branche plutôt que d'un paramètre, un motif de chemin n'étant pas paramétrable en
    Cypher.

    ``avec_pont=False`` retire le saut par `ALIAS_DE` : c'est l'ablation exigée par le J4,
    « rappel du ciblage sans le pont inter-documents ». Elle se règle ici et nulle part
    ailleurs, ce qui garantit que l'ablation mesure bien le pont et pas autre chose.

    ``count(DISTINCT ka.concept_id)`` compte les concepts du côté A, pas les classes
    d'équivalence : une clause qui emploierait deux synonymes d'une même classe compterait
    deux partages là où il n'y en a qu'un. Le cas ne se produit pas sur ce corpus, et
    corriger l'approximation demanderait précisément le `canonique_id` qu'on a choisi de ne
    pas dénormaliser.
    """
    liaison = "(ka = kb OR (ka)-[:ALIAS_DE]-(kb))" if avec_pont else "ka = kb"
    return (
        "MATCH (a:Clause)-[ma:MENTIONNE]->(ka:Concept)\n"
        "MATCH (kb:Concept)<-[mb:MENTIONNE]-(b:Clause)\n"
        "WHERE a.doc_id < b.doc_id\n"
        f"  AND {liaison}\n"
        "  AND ka.idf > $idf_min AND kb.idf > $idf_min\n"
        "WITH a, b, sum(ma.poids * mb.poids * ka.idf) AS score,\n"
        "     count(DISTINCT ka.concept_id) AS partages\n"
        "WHERE partages >= $partages_min\n"
        "RETURN a.clause_id AS clause_a, b.clause_id AS clause_b, score"
    )


def apparier(session: Session, *, avec_pont: bool = True) -> list[Appariement]:
    """Les paires partageant au moins ``partages_min`` concepts canoniques discriminants."""
    brut = [
        (enregistrement["clause_a"], enregistrement["clause_b"], float(enregistrement["score"]))
        for enregistrement in session.run(
            requete(avec_pont),
            idf_min=config_ciblage.idf_min(),
            partages_min=config_ciblage.partages_min(),
        )
    ]
    return classer(brut, Canal.CONCEPTUEL)
