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

__all__ = [
    "date_reference",
    "materialiser_jeu_derive",
    "segmenter_document",
    "segmenter_jeu",
]


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


def _declaration(jeu: str) -> dict:
    manifeste = reglages.charger_config("corpus")["jeux"]
    if jeu not in manifeste:
        connus = ", ".join(sorted(manifeste)) or "(aucun)"
        raise KeyError(f"Jeu de corpus inconnu : {jeu!r}. Jeux déclarés : {connus}")
    return manifeste[jeu]


def date_reference(jeu: str = "fixtures"):
    """La date à laquelle ce jeu est jugé — échéances dépassées, documents en vigueur.

    Déclarée par jeu dans `config/corpus.yaml`, jamais prise à `date.today()` : un rapport
    dont le contenu change d'un jour à l'autre sans qu'aucun code n'ait bougé n'est pas
    reproductible, et la mesure d'hier ne se compare plus à celle d'aujourd'hui.

    Rend `None` si le jeu n'en déclare pas — l'appelant décide alors quoi faire, plutôt que
    de se voir imposer une date silencieusement.
    """
    declaration = _declaration(jeu)
    if "derive_de" in declaration and "date_reference" not in declaration:
        return date_reference(declaration["derive_de"])
    return declaration.get("date_reference")


def materialiser_jeu_derive(jeu: str) -> Path:
    """Copie le corpus source d'un jeu dérivé et y applique ses substitutions.

    C'est ce qui permet au scénario incrémental du J7 de modifier une clause **sans jamais
    toucher à `corpus/fixtures/`**, qui est en lecture seule. La copie va dans `.cache/`,
    hors dépôt et reconstructible.

    ⚠️ **Chaque `ancien` doit apparaître exactement une fois** dans son document. Une
    substitution qui frapperait deux endroits modifierait une clause qu'on n'a pas visée,
    et le rapport comparé n'aurait plus de sens : on refuse plutôt que de deviner.
    """
    declaration = _declaration(jeu)
    source = _declaration(declaration["derive_de"])
    dossier_source = reglages.racine_projet() / source["dossier"]
    dossier_cible = reglages.racine_projet() / ".cache" / "corpus" / jeu
    dossier_cible.mkdir(parents=True, exist_ok=True)

    substitutions = declaration.get("substitutions", [])
    par_document: dict[str, list[dict]] = {}
    for substitution in substitutions:
        par_document.setdefault(substitution["document"], []).append(substitution)

    for entree in source["documents"]:
        texte = (dossier_source / entree["fichier"]).read_text(encoding="utf-8")
        for substitution in par_document.get(entree["id"], []):
            ancien, nouveau = substitution["ancien"], substitution["nouveau"]
            occurrences = texte.count(ancien)
            if occurrences != 1:
                raise ValueError(
                    f"Jeu dérivé {jeu!r} : {ancien!r} apparaît {occurrences} fois dans "
                    f"{entree['fichier']}, il en faut exactement une. Une substitution "
                    f"ambiguë modifierait une clause non visée."
                )
            texte = texte.replace(ancien, nouveau)
        (dossier_cible / entree["fichier"]).write_text(texte, encoding="utf-8")

    return dossier_cible


def segmenter_jeu(jeu: str = "fixtures") -> dict[str, Segmentation]:
    """Segmente tous les documents d'un jeu déclaré dans `config/corpus.yaml`.

    Un jeu portant `derive_de` est **matérialisé** avant d'être segmenté : sa copie est
    reconstruite à chaque appel, ce qui la rend idempotente et interdit qu'une modification
    manuelle de la copie survive à une exécution.
    """
    declaration = _declaration(jeu)

    if "derive_de" in declaration:
        dossier = materialiser_jeu_derive(jeu)
        documents = _declaration(declaration["derive_de"])["documents"]
    else:
        dossier = reglages.racine_projet() / declaration["dossier"]
        documents = declaration["documents"]

    return {
        entree["id"]: segmenter_document(entree["id"], dossier / entree["fichier"])
        for entree in documents
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
