"""Renvois internes et croisés, citations de normes.

« décrites au § 12.3 » (I09, cible inexistante), « au § 11.2 de la procédure
PR-QSE-04 » (I10, renvoi inter-documents), « ISO 45001:2018 » (I08).

`resolu` est formellement une propriété d'arête de graphe (architecture.md §5.3,
`RENVOIE_A`), posée au chargement L2. Ce module en calcule une version locale et légère,
dès le J2, en interrogeant directement les `Segmentation` déjà en mémoire — sans attendre
Neo4j. `resolu` reste `None` (jamais `False`) pour NORME/EXIGENCE : aucune tentative de
résolution contre `registre_normes.yaml` n'est faite ici (rempli au J4) ; `False`
impliquerait à tort qu'une vérification a eu lieu et a échoué.
"""

from __future__ import annotations

import re
from functools import lru_cache

from cohera.extraction.frames import Reference, TypeReference
from cohera.ingestion.modeles import Clause, Segmentation

_MOTIF_ISO = re.compile(r"\bISO\s+(\d+)(?::(\d{4}))?", re.IGNORECASE)
_MOTIF_OHSAS = re.compile(r"\bOHSAS\s+(\d+)", re.IGNORECASE)
_MOTIF_EXIGENCE = re.compile(
    r"\barticle\s+([A-Z]?\.?\s?\d[\d.\-]*)(?:\s+du\s+([^,.]+?)(?=\s+relatif|\s*[,.]|$))?",
    re.IGNORECASE,
)

# « § 6.4 de la politique POL-SEC-01 », « § 5.1 de la présente procédure » (code absent
# -> soi-même), « § 11.2 de la procédure PR-QSE-04 ».
_MOTIF_INTERNE_APRES = re.compile(
    r"§\s*(\d+(?:\.\d+)?)\s+de\s+la\s+"
    r"(présente\s+procédure|présente\s+politique|présent\s+document|politique|procédure|instruction)"
    r"(?:\s+([A-Z]{2,4}-[A-Z]{2,4}-\d{2,3}))?",
    re.IGNORECASE,
)
# « la procédure PR-QSE-02 § 3.1 » — le code précède le §, seul cas dans ce sens (D1 §10.2).
_MOTIF_INTERNE_AVANT = re.compile(
    r"(?:politique|procédure)\s+([A-Z]{2,4}-[A-Z]{2,4}-\d{2,3})\s+§\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
# Repli : un § nu, sans connecteur de document (D1 §7.5) -> soi-même par défaut.
_MOTIF_INTERNE_NU = re.compile(r"§\s*(\d+(?:\.\d+)?)")


def document_par_code(code: str, segmentations: dict[str, Segmentation]) -> str | None:
    for doc_id, segmentation in segmentations.items():
        if segmentation.document.code == code:
            return doc_id
    return None


def resoudre_section(numero_section: str, doc_id_cible: str | None, segmentations: dict[str, Segmentation]) -> bool:
    """La section de tête du numéro existe-t-elle dans le document ciblé ?

    Vérification au niveau section (« 10 » couvre 10.1, 10.2, 10.3), pas au paragraphe
    précis : suffisant pour les 12 cas du plan à 7 jours."""
    if doc_id_cible is None:
        return False
    segmentation = segmentations.get(doc_id_cible)
    if segmentation is None:
        return False
    return bool(segmentation.par_section(numero_section.split(".")[0]))


def resoudre_reference_interne(
    texte: str, doc_id: str, segmentations: dict[str, Segmentation]
) -> tuple[str, str | None, bool] | None:
    """Cherche le premier renvoi interne (`§...`) dans `texte` et le résout en
    `(numero, document_cible, resolu)`, ou `None` si aucun renvoi n'y est trouvé.

    Réutilisée par `regles/validite.py` pour résoudre la cible d'une dérogation (« par
    dérogation au § 6.4 de la politique POL-SEC-01 ») sans réimplémenter les motifs
    § croisés/inversés/nus ci-dessus."""
    trouve = _MOTIF_INTERNE_APRES.search(texte)
    if trouve:
        numero, connecteur, code = trouve.group(1), trouve.group(2).lower(), trouve.group(3)
        document_cible = document_par_code(code, segmentations) if code else doc_id
        return numero, document_cible, resoudre_section(numero, document_cible, segmentations)

    trouve = _MOTIF_INTERNE_AVANT.search(texte)
    if trouve:
        code, numero = trouve.group(1), trouve.group(2)
        document_cible = document_par_code(code, segmentations)
        return numero, document_cible, resoudre_section(numero, document_cible, segmentations)

    trouve = _MOTIF_INTERNE_NU.search(texte)
    if trouve:
        numero = trouve.group(1)
        return numero, doc_id, resoudre_section(numero, doc_id, segmentations)

    return None


def _chevauche(empan: tuple[int, int], empans: list[tuple[int, int]]) -> bool:
    debut, fin = empan
    return any(not (fin <= e_debut or debut >= e_fin) for e_debut, e_fin in empans)


@lru_cache(maxsize=1)
def _connecteurs_soi_meme() -> tuple[str, ...]:
    return ("présente procédure", "présente politique", "présent document")


def extraire_references(
    clause: Clause, doc_id: str, segmentations: dict[str, Segmentation]
) -> list[Reference]:
    texte = clause.texte_source
    references: list[Reference] = []
    empans: list[tuple[int, int]] = []

    for trouve in _MOTIF_ISO.finditer(texte):
        references.append(
            Reference(
                type=TypeReference.NORME,
                cible=f"ISO {trouve.group(1)}",
                surface=trouve.group(0),
                version=trouve.group(2),
            )
        )
        empans.append(trouve.span())

    for trouve in _MOTIF_OHSAS.finditer(texte):
        references.append(
            Reference(type=TypeReference.NORME, cible=f"OHSAS {trouve.group(1)}", surface=trouve.group(0))
        )
        empans.append(trouve.span())

    for trouve in _MOTIF_EXIGENCE.finditer(texte):
        source = trouve.group(2).strip() if trouve.group(2) else None
        references.append(
            Reference(
                type=TypeReference.EXIGENCE,
                cible=trouve.group(1).strip(),
                surface=trouve.group(0),
                source=source,
            )
        )
        empans.append(trouve.span())

    for trouve in _MOTIF_INTERNE_APRES.finditer(texte):
        numero, connecteur, code = trouve.group(1), trouve.group(2).lower(), trouve.group(3)
        if code:
            document_cible = document_par_code(code, segmentations)
        else:
            document_cible = doc_id  # soi-même, connecteur explicite ou implicite
        references.append(
            Reference(
                type=TypeReference.INTERNE,
                cible=f"§ {numero}",
                surface=trouve.group(0),
                document_cible=document_cible,
                resolu=resoudre_section(numero, document_cible, segmentations),
            )
        )
        empans.append(trouve.span())

    for trouve in _MOTIF_INTERNE_AVANT.finditer(texte):
        if _chevauche(trouve.span(), empans):
            continue
        code, numero = trouve.group(1), trouve.group(2)
        document_cible = document_par_code(code, segmentations)
        references.append(
            Reference(
                type=TypeReference.INTERNE,
                cible=f"§ {numero}",
                surface=trouve.group(0),
                document_cible=document_cible,
                resolu=resoudre_section(numero, document_cible, segmentations),
            )
        )
        empans.append(trouve.span())

    for trouve in _MOTIF_INTERNE_NU.finditer(texte):
        if _chevauche(trouve.span(), empans):
            continue
        numero = trouve.group(1)
        references.append(
            Reference(
                type=TypeReference.INTERNE,
                cible=f"§ {numero}",
                surface=trouve.group(0),
                document_cible=doc_id,
                resolu=resoudre_section(numero, doc_id, segmentations),
            )
        )
        empans.append(trouve.span())

    return references
