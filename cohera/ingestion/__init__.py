"""L0 — ingestion et segmentation en unités normatives.

    texte brut
       ├─ 1. normalisation        substitutions 1:1, offsets préservés
       ├─ 2. structure            front-matter, sections, paragraphes numérotés
       ├─ 3. listes à chapeau     le chapeau est redistribué sur les items  (CAP02)
       ├─ 4. blocs tabulaires     une clause par ligne, l'en-tête donne les rôles (CAP03)
       ├─ 5. phrases spaCy        avec exceptions : codes, abréviations, décimales
       ├─ 6. qualification        déontique | grandeur | référence | définition (CAP08)
       └─ 7. autonomisation       anaphores résolues par règle                  (CAP01)

Sur les fixtures : 41 clauses pour D1, 37 pour D2.
"""

from __future__ import annotations

from pathlib import Path

from cohera import reglages
from cohera.ingestion import listes, tableaux
from cohera.ingestion.autonomisation import autonomiser, besoin_autonomisation
from cohera.ingestion.modeles import Clause, Document, OrigineClause, Segmentation
from cohera.ingestion.normalisation import lire_texte_origine, normaliser
from cohera.ingestion.phrases import analyseur, grouper_en_clauses, qualifier
from cohera.ingestion.structure import Unite, decouper_unites, lire_entete

__all__ = ["segmenter_document", "segmenter_jeu"]


def segmenter_document(doc_id: str, chemin: Path | str) -> Segmentation:
    """Segmente un `.txt` en clauses. C'est le point d'entrée de L0."""
    chemin = Path(chemin)
    origine = lire_texte_origine(chemin)
    normalise = normaliser(origine)

    document = lire_entete(doc_id, chemin.name, origine)
    unites, sections = decouper_unites(normalise, doc_id)
    document.sections = sections

    clauses: list[Clause] = []
    compteurs: dict[str, int] = {}

    for unite in unites:
        corps = normalise[unite.debut : unite.fin]

        # Une unité non numérotée doit mériter son statut de clause (CAP08). Écartée,
        # elle n'est pas perdue : elle reste lisible au pied de la clause précédente.
        if unite.ref is None and not qualifier(corps):
            _rattacher_en_contexte(clauses, corps)
            continue

        for brute in _clauses_de_l_unite(unite, origine, normalise):
            clauses.append(_materialiser(brute, unite, document, clauses, compteurs))

    _autonomiser_tout(clauses)
    return Segmentation(document=document, clauses=clauses)


def segmenter_jeu(jeu: str = "fixtures") -> dict[str, Segmentation]:
    """Segmente tous les documents d'un jeu déclaré dans `config/corpus.yaml`."""
    manifeste = reglages.charger_config("corpus")["jeux"]
    if jeu not in manifeste:
        connus = ", ".join(sorted(manifeste)) or "(aucun)"
        raise KeyError(f"Jeu de corpus inconnu : {jeu!r}. Jeux déclarés : {connus}")

    declaration = manifeste[jeu]
    dossier = reglages.racine_projet() / declaration["dossier"]
    return {
        entree["id"]: segmenter_document(entree["id"], dossier / entree["fichier"])
        for entree in declaration["documents"]
    }


# ------------------------------------------------------------ explosion d'une unité


def _clauses_de_l_unite(unite: Unite, origine: str, normalise: str) -> list[dict]:
    """Une unité donne une clause, ou plusieurs si elle porte une liste, un tableau, ou
    deux énoncés autonomes."""
    if lignes := tableaux.exploser(unite, origine):
        return [ligne | {"origine": OrigineClause.TABLEAU} for ligne in lignes]

    if items := listes.exploser(unite, origine):
        return [item | {"origine": OrigineClause.LISTE} for item in items]

    doc = analyseur()(normalise[unite.debut : unite.fin])
    return [
        {
            "debut": unite.debut + debut,
            "fin": unite.debut + fin,
            "texte_source": origine[unite.debut + debut : unite.debut + fin],
            "texte_autonome": normalise[unite.debut + debut : unite.debut + fin],
            "origine": OrigineClause.TEXTE,
        }
        for debut, fin in grouper_en_clauses(doc)
    ]


def _materialiser(
    brute: dict,
    unite: Unite,
    document: Document,
    clauses: list[Clause],
    compteurs: dict[str, int],
) -> Clause:
    section = unite.section
    numero = section.numero if section else "0"
    compteurs[numero] = compteurs.get(numero, 0) + 1

    return Clause(
        clause_id=f"{document.doc_id}::S{numero}::C{compteurs[numero]:02d}",
        doc_id=document.doc_id,
        ref=unite.ref or _ref_derivee(clauses, numero),
        section_path=[section.titre] if section else [],
        ordre=len(clauses) + 1,
        texte_source=brute["texte_source"],
        texte_autonome=brute["texte_autonome"],
        offset=(brute["debut"], brute["fin"]),
        origine=brute["origine"],
        chapeau=brute.get("chapeau"),
        attributs=brute.get("attributs", {}),
    )


def _ref_derivee(clauses: list[Clause], numero: str) -> str:
    """Référence d'un paragraphe non numéroté : « 1.2+ », la convention de `label.json`."""
    return f"{clauses[-1].ref}+" if clauses else f"{numero}.0"


# ------------------------------------------------------------------- rattachements


def _rattacher_en_contexte(clauses: list[Clause], texte: str) -> None:
    if clauses:
        clauses[-1].contexte.append(texte)


def _autonomiser_tout(clauses: list[Clause]) -> None:
    """Passe d'autonomisation, une fois toutes les clauses connues.

    Faite après coup et non au fil de l'eau : l'antécédent se cherche dans les clauses
    déjà matérialisées, pas dans les lignes brutes du fichier.
    """
    nlp = analyseur()
    docs = list(nlp.pipe(clause.texte_autonome for clause in clauses))

    for indice, (clause, doc) in enumerate(zip(clauses, docs)):
        # Une ligne de tableau n'a ni sujet ni verbe : son texte de travail est déjà
        # recomposé, l'y chercher une anaphore n'aurait aucun sens.
        if clause.origine is not OrigineClause.TEXTE:
            continue
        if not besoin_autonomisation(clause.texte_autonome, doc):
            continue

        precedents = [
            docs[j]
            for j in range(indice)
            if clauses[j].section_path == clause.section_path
            and clauses[j].origine is OrigineClause.TEXTE
        ]
        reecrit = autonomiser(clause.texte_autonome, doc, precedents)
        if reecrit:
            clause.texte_autonome = reecrit
            clause.autonomise = True
