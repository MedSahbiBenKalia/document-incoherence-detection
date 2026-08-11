"""graphe/schema.py — lecture de `schema.cypher`.

Aucun serveur n'est nécessaire : `instructions` est une fonction pure, isolée de son
exécution exactement comme `compat.requete_vectorielle`. Le fichier `.cypher` réel est lu
tel quel, de sorte qu'une faute de frappe dedans échoue ici plutôt qu'au premier
chargement.

Critère du J3 (docs/plan-1-semaine.md §J3) : « schema.cypher (contraintes + index + index
vectoriel 1024) ; chargement idempotent par MERGE ». L'idempotence du schéma tient au
`IF NOT EXISTS` de chaque instruction — c'est testé ici, sans serveur.
"""

from __future__ import annotations

import pytest

from cohera.graphe.schema import (
    JETON_DIMENSION,
    chemin_schema,
    instructions,
    instructions_du_schema,
)

# ------------------------------------------------------------------- découpage, pureté


def test_les_commentaires_ne_produisent_aucune_instruction() -> None:
    texte = """
    // un commentaire
    CREATE INDEX a IF NOT EXISTS FOR (n:N) ON (n.x);
    // un autre
    CREATE INDEX b IF NOT EXISTS FOR (n:N) ON (n.y);
    """
    assert instructions(texte, 1024) == [
        "CREATE INDEX a IF NOT EXISTS FOR (n:N) ON (n.x)",
        "CREATE INDEX b IF NOT EXISTS FOR (n:N) ON (n.y)",
    ]


def test_le_point_virgule_final_ne_produit_pas_d_instruction_vide() -> None:
    assert instructions("CREATE INDEX a IF NOT EXISTS FOR (n:N) ON (n.x);", 1024) == [
        "CREATE INDEX a IF NOT EXISTS FOR (n:N) ON (n.x)"
    ]


def test_la_dimension_est_substituee() -> None:
    texte = f"CREATE VECTOR INDEX v FOR (n:N) ON (n.e) OPTIONS {{ d: {JETON_DIMENSION} }};"
    assert instructions(texte, 768) == [
        "CREATE VECTOR INDEX v FOR (n:N) ON (n.e) OPTIONS { d: 768 }"
    ]


@pytest.mark.parametrize("dimension", [0, -1, 1.5, "1024", None, True])
def test_une_dimension_invalide_leve(dimension: object) -> None:
    """Une dimension qui n'est pas un entier positif produirait un index inutilisable, et
    le diagnostic n'arriverait qu'au J4 à l'insertion du premier vecteur. `True` est
    explicitement refusé : `isinstance(True, int)` vaut vrai en Python."""
    with pytest.raises(ValueError):
        instructions("CREATE INDEX a FOR (n:N) ON (n.x);", dimension)  # type: ignore[arg-type]


# --------------------------------------------------------- le fichier réel du dépôt


def test_le_fichier_du_depot_existe_et_produit_des_instructions() -> None:
    assert chemin_schema().is_file()
    assert len(instructions_du_schema(1024)) >= 20


def test_toute_instruction_du_schema_est_idempotente() -> None:
    """C'est la moitié « schéma » de l'idempotence exigée par CLAUDE.md.

    Sans `IF NOT EXISTS`, un second chargement lèverait sur contrainte déjà existante.
    """
    for ordre in instructions_du_schema(1024):
        assert "IF NOT EXISTS" in ordre, f"instruction non idempotente : {ordre}"


def test_le_schema_ne_contient_aucun_create_de_donnees() -> None:
    """Le cas négatif : `schema.cypher` ne crée que des contraintes et des index.

    Un `CREATE (n:Clause …)` qui s'y glisserait violerait « MERGE, jamais CREATE » et
    dupliquerait des nœuds à chaque exécution.
    """
    autorises = ("CREATE CONSTRAINT", "CREATE INDEX", "CREATE FULLTEXT INDEX", "CREATE VECTOR INDEX")
    for ordre in instructions_du_schema(1024):
        assert ordre.startswith(autorises), f"instruction inattendue dans le schéma : {ordre}"


def test_les_trois_index_vectoriels_portent_la_dimension_configuree() -> None:
    """La dimension de l'index et celle du modèle ne peuvent pas diverger : elles viennent
    de la même source (`config/technique.yaml`). C'est ce que vérifie aussi la ligne
    « Embeddings » de `cohera doctor`."""
    from cohera import reglages

    dimension = reglages.charger().embeddings.dimension
    vectoriels = [o for o in instructions_du_schema() if "VECTOR INDEX" in o]

    assert len(vectoriels) == 3, "attendu clause_vec, concept_vec, condition_vec"
    for ordre in vectoriels:
        assert f"`vector.dimensions`: {dimension}" in ordre
        assert JETON_DIMENSION not in ordre, "jeton non substitué"


def test_les_contraintes_couvrent_les_noeuds_charges_au_j3() -> None:
    """Chaque nœud écrit par `chargeur.py` doit avoir une contrainte d'unicité, sinon le
    `MERGE` porterait sur une clé non indexée et l'idempotence ne tiendrait que par
    chance."""
    schema = "\n".join(instructions_du_schema(1024))
    for label in ("Document", "Section", "Clause", "Concept", "Condition", "Quantite"):
        assert f"(n:{label})" in schema or f":{label})" in schema, f"{label} sans contrainte"
