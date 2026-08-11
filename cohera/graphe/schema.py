"""Lecture et application de `schema.cypher`.

Découpage volontaire, calqué sur `compat.py` : :func:`instructions` est une fonction
**pure** — un texte en entrée, une liste d'instructions Cypher en sortie — donc testable
sans serveur. Seule :func:`appliquer` a besoin d'une session.

Le fichier `.cypher` porte le jeton ``__DIMENSION__`` là où Neo4j attend la dimension des
index vectoriels. Cypher n'accepte pas de paramètre dans un bloc ``OPTIONS`` : la valeur
doit être interpolée. Elle est donc lue dans `config/technique.yaml`, ce qui garantit que
l'index et le modèle d'embeddings partagent la même dimension au lieu de l'affirmer deux
fois. L'interpolation est bornée à un entier validé — jamais une chaîne venue du YAML
telle quelle, qui serait une injection Cypher.
"""

from __future__ import annotations

from pathlib import Path

from neo4j import Session

from cohera import reglages

#: Jeton substitué par la dimension des embeddings.
JETON_DIMENSION = "__DIMENSION__"


def chemin_schema() -> Path:
    """Emplacement de `schema.cypher`, à côté de ce module."""
    return Path(__file__).with_name("schema.cypher")


def _sans_commentaires(texte: str) -> str:
    """Retire les lignes de commentaire `//`.

    Retrait **ligne à ligne** et non par expression régulière sur tout le texte : un `//`
    en milieu de ligne appartiendrait à une instruction, et le fichier promet en en-tête de
    ne pas mettre de `;` dans un commentaire, ce qui rend ce traitement suffisant.
    """
    lignes = [ligne for ligne in texte.splitlines() if not ligne.lstrip().startswith("//")]
    return "\n".join(lignes)


def instructions(texte: str, dimension: int) -> list[str]:
    """Les instructions Cypher d'un schéma, commentaires retirés et dimension substituée.

    Fonction pure : c'est elle qui porte la logique, donc c'est elle qu'on teste, et aucun
    serveur n'est nécessaire pour le faire.

    Lève ``ValueError`` si la dimension n'est pas un entier strictement positif — une
    dimension nulle ou négative produirait un index vectoriel inutilisable, et le
    diagnostic n'arriverait qu'au J4, à l'insertion du premier vecteur.
    """
    if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1:
        raise ValueError(
            f"Dimension d'index vectoriel invalide : {dimension!r}. "
            "Attendu un entier strictement positif — voir embeddings.dimension "
            "dans config/technique.yaml."
        )

    corps = _sans_commentaires(texte).replace(JETON_DIMENSION, str(dimension))
    return [morceau.strip() for morceau in corps.split(";") if morceau.strip()]


def instructions_du_schema(dimension: int | None = None) -> list[str]:
    """Les instructions de `schema.cypher`, dimension prise dans la configuration."""
    if dimension is None:
        dimension = reglages.charger().embeddings.dimension
    return instructions(chemin_schema().read_text(encoding="utf-8"), dimension)


def appliquer(session: Session | None = None, dimension: int | None = None) -> int:
    """Applique le schéma et renvoie le nombre d'instructions exécutées.

    Idempotent par construction : toutes les instructions sont en ``IF NOT EXISTS``.
    Rejouer cette fonction ne crée rien de nouveau et ne lève pas.
    """
    ordres = instructions_du_schema(dimension)

    if session is not None:
        for ordre in ordres:
            session.run(ordre)
        return len(ordres)

    from cohera.graphe.connexion import session as ouvrir_session

    with ouvrir_session() as sess:
        for ordre in ordres:
            sess.run(ordre)
    return len(ordres)
