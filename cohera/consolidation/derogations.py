"""Dérogations en vigueur — la rubrique qui empêche un conflit *légitime* d'être signalé.

architecture.md §8 place les dérogations valides dans une rubrique distincte des
incohérences, et `label.json` en fait un contre-exemple explicite : N05 attend
``AUCUNE_CONSTATATION_MAIS_LISTEE`` — « sans la dérogation, ce serait un conflit réel
(exemption contre obligation inconditionnelle). La dérogation est déclarée, motivée,
approuvée et non expirée : elle doit apparaître dans la rubrique *dérogations en vigueur*
du rapport, pas dans les incohérences. »

**Quatre conditions cumulatives**, et c'est leur conjonction qui fait la validité :

1. la **cible est résolue** — on sait à quoi la dérogation déroge ;
2. elle est **motivée** — une justification est écrite ;
3. elle est **approuvée** — un approbateur est nommé ;
4. elle **n'est pas expirée** à la date de référence du jeu.

⚠️ **Lister n'est pas détecter.** Ce module ne trouve pas les dérogations fautives : une
dérogation orpheline (I17) ou expirée (I18) sort simplement de la rubrique « en vigueur »,
elle n'y produit aucun signalement. C'est le détecteur A8 qui les constaterait, et A8 n'est
pas implémenté — hors périmètre du plan 7 jours. Le distinguo compte : le rapport dit ici
ce qui est *couvert*, pas ce qui est *cassé*.

**Mesuré sur le corpus fixtures** — les trois dérogations se séparent proprement :

    D1 §10.1  cible D2 §6.4 résolue · motivée · Directeur de site · 2026-12-31  -> EN VIGUEUR
    D1 §10.2  cible non résolue · sans justification · sans approbateur         -> écartée (I17)
    D1 §10.3  cible résolue · sans justification · échéance 2024-12-31 dépassée -> écartée (I18)
"""

from __future__ import annotations

from datetime import date

from cohera.extraction.frames import ClauseFrame
from cohera.restitution.rapport_json import CoteClause, Derogation


def est_en_vigueur(frame: ClauseFrame, a_la_date: date | None) -> bool:
    """La dérogation de cette clause est-elle déclarée, motivée, approuvée et non expirée ?

    Une échéance **absente** ne vaut pas « indéfiniment valable » : une dérogation sans
    terme n'est pas encadrée, et l'encadrement est précisément ce que cette rubrique
    atteste. Sans date de référence, en revanche, on ne peut pas juger de l'expiration — on
    ne l'invente pas, et les trois autres conditions décident seules.
    """
    derogation = frame.derogation
    if derogation is None:
        return False
    if not derogation.cible_resolue:
        return False
    if not (derogation.justification or "").strip():
        return False
    if not (derogation.approbateur or "").strip():
        return False
    if derogation.echeance is None:
        return False
    if a_la_date is not None and derogation.echeance < a_la_date:
        return False
    return True


def _clause_visee(derogation, clauses: dict):
    """La clause à laquelle on déroge, résolue en `(doc, ref)`.

    ⚠️ **Ce côté n'est pas décoratif.** `label.json` désigne N05 par la **paire**
    ``D1 §10.1 ↔ D2 §6.4``, et le harnais apparie sur le `frozenset` des deux couples : une
    dérogation qui ne porterait que sa clause source ne s'apparierait à rien, et la rubrique
    resterait « absente du rapport » alors qu'elle est remplie. Mesuré au J7.
    """
    if not derogation.cible_document:
        return None
    ref = derogation.cible.replace("§", "").strip()
    return next(
        (
            clause
            for clause in clauses.values()
            if clause.doc_id == derogation.cible_document and clause.ref == ref
        ),
        None,
    )


def derogations_en_vigueur(
    frames: dict[str, ClauseFrame],
    clauses: dict,
    a_la_date: date | None = None,
) -> list[Derogation]:
    """La rubrique « dérogations en vigueur » du rapport.

    ``clauses`` associe un `clause_id` à sa clause segmentée : c'est de là que viennent le
    document, le numéro de paragraphe et le `texte_source` contre lequel la preuve citée
    est vérifiée — pour la clause qui déroge comme pour celle à laquelle on déroge.
    """
    retenues: list[Derogation] = []

    for clause_id in sorted(frames):
        frame = frames[clause_id]
        if not est_en_vigueur(frame, a_la_date):
            continue

        derogation = frame.derogation
        clause = clauses.get(clause_id)
        visee = _clause_visee(derogation, clauses)

        cible_libelle = derogation.cible.strip()
        if derogation.cible_document:
            cible_libelle = f"{derogation.cible_document} {cible_libelle}"

        retenues.append(
            Derogation(
                id=f"DER-{clause.doc_id}-{clause.ref}" if clause else f"DER-{clause_id}",
                clause_a=CoteClause(
                    doc=clause.doc_id if clause else "",
                    ref=clause.ref if clause else "",
                    clause_id=clause_id,
                    # La preuve est la surface littérale de la cible, telle qu'elle figure
                    # dans le texte : c'est ce que la vérification de `restitution/preuves.py`
                    # contrôlera comme n'importe quelle autre citation du rapport.
                    preuve=derogation.cible.strip(),
                    texte_source=clause.texte_source if clause else None,
                ),
                # Pas de preuve citée du côté visé : la dérogation ne lui reproche rien,
                # elle s'en exempte. Le côté sert à localiser, pas à accuser.
                clause_b=(
                    CoteClause(doc=visee.doc_id, ref=visee.ref, clause_id=visee.clause_id)
                    if visee is not None
                    else None
                ),
                cible=cible_libelle,
                justification=(derogation.justification or "").strip(),
                approbateur=(derogation.approbateur or "").strip(),
                echeance=derogation.echeance,
            )
        )

    return retenues
