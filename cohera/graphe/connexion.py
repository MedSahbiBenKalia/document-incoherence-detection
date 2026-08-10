"""Fabrique de driver Neo4j, avec des erreurs qui disent quoi faire.

Le mot de passe ne vient jamais du YAML : ``config/technique.yaml`` désigne la variable
d'environnement (``mot_de_passe_env``), et c'est ``.env`` ou le shell qui la porte.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from neo4j import Driver, GraphDatabase, Session

from cohera import reglages


class ErreurNeo4j(Exception):
    """Échec de connexion au graphe, accompagné du geste qui le corrige."""

    def __init__(self, message: str, remede: str = "") -> None:
        super().__init__(message)
        self.remede = remede


def driver() -> Driver:
    """Construit un driver à partir de la configuration. Ne teste pas la connexion."""
    config = reglages.charger().neo4j
    mot_de_passe = reglages.secret(config.mot_de_passe_env)

    if not mot_de_passe:
        raise ErreurNeo4j(
            f"{config.mot_de_passe_env} est absent de l'environnement.",
            f"Copier .env.example vers .env et y renseigner {config.mot_de_passe_env} "
            "— la même valeur que celle utilisée par docker compose.",
        )

    return GraphDatabase.driver(
        config.uri,
        auth=(config.utilisateur, mot_de_passe),
        connection_timeout=config.timeout_s,
    )


@contextmanager
def session() -> Iterator[Session]:
    """Session Neo4j sur la base configurée, driver fermé en sortie."""
    config = reglages.charger().neo4j
    pilote = driver()
    try:
        with pilote.session(database=config.base) as sess:
            yield sess
    finally:
        pilote.close()


def verifier_connectivite() -> str:
    """Vérifie que le serveur répond et renvoie sa version.

    Lève ``ErreurNeo4j`` avec un remède si le service est injoignable ou refuse
    l'authentification.
    """
    from neo4j.exceptions import AuthError, ServiceUnavailable

    config = reglages.charger().neo4j
    try:
        pilote = driver()
        try:
            pilote.verify_connectivity()
            with pilote.session(database=config.base) as sess:
                resultat = sess.run(
                    "CALL dbms.components() YIELD name, versions "
                    "WHERE name = 'Neo4j Kernel' RETURN versions[0] AS version"
                ).single()
            return resultat["version"] if resultat else "inconnue"
        finally:
            pilote.close()
    except AuthError as exc:
        raise ErreurNeo4j(
            "Authentification refusée par Neo4j.",
            f"{config.mot_de_passe_env} ne correspond pas au mot de passe du conteneur. "
            "Si le volume a été créé avec un autre mot de passe : "
            "docker compose down -v puis docker compose up -d (efface les données).",
        ) from exc
    except ServiceUnavailable as exc:
        raise ErreurNeo4j(
            f"Neo4j injoignable sur {config.uri}.",
            "Démarrer Docker Desktop, puis : docker compose up -d",
        ) from exc
