"""Rendu HTML du rapport par gabarit Jinja2.

Quatre rubriques, dans l'ordre où un auditeur les lit (plan §J7, architecture.md §8) :

1. **les constatations**, triées par criticité — ce qui est en cause, et pourquoi ;
2. **les hypothèses d'alignement** — les alias qui ont permis de rapprocher deux clauses de
   documents différents. Elles sont *révisables* (architecture.md §13, R1) : c'est le
   premier levier de réglage quand la précision dérive, et les taire reviendrait à faire
   passer une hypothèse pour un fait ;
3. **les zones non couvertes** — ce que le système n'a pas tranché, nommé motif par motif.
   « Un système d'audit qui abstient 8 % est infiniment plus utile qu'un système qui tranche
   à tort 8 % » (§7.4) ; encore faut-il que les 8 % soient visibles ;
4. **les dérogations en vigueur** — les conflits apparents qui sont couverts.

**Page autonome.** Tout le CSS est en ligne, aucune ressource externe : le fichier doit
s'ouvrir depuis une clé USB, en soutenance, sans réseau.

**Le critère d'acceptation est un test de lecture**, pas un chiffre : « quelqu'un qui ne
connaît pas le projet lit le rapport et sait, pour chaque ligne, quelles clauses sont en
cause et pourquoi ». D'où le parti pris du gabarit : chaque constatation montre ses deux
preuves littérales côte à côte, avec le document et le numéro de paragraphe — jamais un
`clause_id` interne, qui ne veut rien dire pour un lecteur.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cohera.restitution.rapport_json import Rapport

DOSSIER_GABARITS = Path(__file__).parent / "templates"

#: Libellés lisibles des motifs d'abstention. Le motif brut (`PREUVE_INVENTEE`) est juste
#: pour un développeur et opaque pour un auditeur : la rubrique « zones non couvertes »
#: n'a d'intérêt que si elle se lit.
LIBELLES_MOTIFS = {
    "PREUVE_INVENTEE": "Le juge a cité un extrait qui n'existe pas dans le texte — verdict annulé",
    "ABSTENTION_DU_JUGE": "Le juge s'est déclaré incapable de trancher",
    "NON_VERIFIEE_BUDGET": "Plafond d'appels atteint — la paire n'a pas été soumise",
    "LLM_INJOIGNABLE": "Service de jugement injoignable",
    "EXTRACTION_INCERTAINE": "Réponse non conforme au format attendu, même après réparation",
    "PREUVE_LITTERALE_ABSENTE": "Aucune preuve littérale disponible pour fonder un verdict",
}


def _environnement() -> Environment:
    return Environment(
        loader=FileSystemLoader(DOSSIER_GABARITS),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _abstentions_par_motif(rapport: Rapport) -> list[dict]:
    """Regroupe les abstentions par motif, du plus fréquent au moins fréquent.

    Vingt-cinq lignes brutes ne se lisent pas ; cinq motifs comptés et expliqués, oui.
    """
    groupes: dict[str, list] = {}
    for abstention in rapport.abstentions:
        groupes.setdefault(abstention.motif, []).append(abstention)

    return [
        {
            "motif": motif,
            "libelle": LIBELLES_MOTIFS.get(motif, motif),
            "nombre": len(paires),
            "paires": paires,
        }
        for motif, paires in sorted(groupes.items(), key=lambda item: -len(item[1]))
    ]


def _niveaux(rapport: Rapport) -> dict[str, int]:
    return {
        document.id: document.niveau_hierarchique
        for document in rapport.documents
        if document.niveau_hierarchique is not None
    }


def rendre(
    rapport: Rapport,
    *,
    bilan_preuves=None,
    ablation_profils: list[dict] | None = None,
    motif_du_profil: str = "",
) -> str:
    """Rend le rapport en une page HTML autonome.

    ``ablation_profils`` porte le tableau A/B du J6 : le rapport de référence dit lequel des
    deux profils il présente **et** ce que l'autre aurait donné. Présenter un seul profil
    sans son alternative reviendrait à cacher l'arbitrage.
    """
    gabarit = _environnement().get_template("rapport.html.j2")
    return gabarit.render(
        rapport=rapport,
        bilan=bilan_preuves,
        abstentions=_abstentions_par_motif(rapport),
        niveaux=_niveaux(rapport),
        ablation_profils=ablation_profils or [],
        motif_du_profil=motif_du_profil,
        alias_retenus=[h for h in rapport.hypotheses_alias if h.retenu],
        alias_ecartes=[h for h in rapport.hypotheses_alias if not h.retenu],
    )


def ecrire(chemin: Path | str, contenu: str) -> Path:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")
    return chemin
