"""Détection de la structure : front-matter, sections, paragraphes numérotés.

Produit les `refs` (« 4.2 », « 10.3 ») qui servent de clé d'appariement avec la vérité
terrain : c'est sur `(doc_id, ref)` que le harnais d'évaluation reconnaît une constatation.

Deux pièges gouvernent ce module. Le premier est la confusion entre `10.` (titre de
section) et `10.1` (clause) : on essaie donc **toujours** le motif de clause en premier.
Le second est le déclenchement en milieu de ligne — « décrites au § 12.3 »,
« l'article R.4321-1 » — écarté par l'ancre `^` de tous les motifs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache

from cohera import reglages
from cohera.ingestion.modeles import Document, Section
from cohera.ingestion.normalisation import normaliser


@lru_cache(maxsize=1)
def _config() -> dict:
    return reglages.charger_config("segmentation")


@lru_cache(maxsize=1)
def _motifs() -> tuple[re.Pattern, re.Pattern, re.Pattern]:
    config = _config()
    return (
        re.compile(config["numerotation"]["clause"]),
        re.compile(config["numerotation"]["titre"]),
        re.compile(config["entete"]["motif_code"]),
    )


# ----------------------------------------------------------------- reconnaissance de ligne


def reference_de_clause(ligne: str) -> tuple[str, int] | None:
    """« 4.2 Le Responsable QSE… » → `("4.2", 4)`, le second membre étant le décalage du
    corps dans la ligne. Renvoie `None` si la ligne n'ouvre pas un paragraphe numéroté.

    Le numéro n'entre pas dans `texte_source` : c'est une adresse, pas un énoncé.
    """
    motif_clause, _, _ = _motifs()
    trouve = motif_clause.match(ligne)
    if not trouve:
        return None
    return f"{trouve.group(1)}.{trouve.group(2)}", trouve.end()


def titre_de_section(ligne: str) -> tuple[str, str] | None:
    """« 10. DÉROGATIONS » → `("10", "DÉROGATIONS")`, `None` sinon.

    Essayé **après** :func:`reference_de_clause`, sans quoi « 10.1 » passerait pour un
    titre et la section des dérogations disparaîtrait entière.
    """
    if reference_de_clause(ligne) is not None:
        return None

    _, motif_titre, _ = _motifs()
    trouve = motif_titre.match(ligne)
    if not trouve:
        return None

    titre = ligne[trouve.end() :].strip()
    config = _config()["titre"]
    if len(titre) > config["longueur_max"]:
        return None
    if config["sans_point_final"] and titre.endswith("."):
        return None
    return trouve.group(1), titre


def debut_du_corps(texte: str) -> int:
    """Offset du premier titre de section. Tout ce qui précède est du front-matter.

    C'est ce qui empêche « Le présent document annule et remplace la version 2 » de
    devenir une clause : elle est dans l'en-tête, pas dans le corps.
    """
    position = 0
    for ligne in texte.split("\n"):
        if titre_de_section(ligne) is not None:
            return position
        position += len(ligne) + 1
    return 0  # repli : document plat, tout est corps


# --------------------------------------------------------------------------- front-matter


def _analyser_date(brut: str) -> date | None:
    for format_ in _config()["entete"]["formats_date"]:
        try:
            return datetime.strptime(brut.strip(), format_).date()
        except ValueError:
            continue
    return None


def _type_et_niveau(code: str) -> tuple[str, int | None]:
    """Appariement par **préfixe le plus long** : « POL-SEC-01 » tombe dans « POL- », pas
    dans « PO- ». L'inverse donnerait le bon niveau par accident sur ce corpus et le
    mauvais sur le suivant."""
    hierarchie = reglages.charger_config("hierarchie_documents")
    correspondants = [p for p in hierarchie.get("types", {}) if code.startswith(p)]
    if not correspondants:
        defaut = hierarchie.get("defaut", {})
        return defaut.get("type", "INCONNU"), defaut.get("niveau")
    prefixe = max(correspondants, key=len)
    entree = hierarchie["types"][prefixe]
    return entree["type"], entree["niveau"]


def lire_entete(doc_id: str, fichier: str, texte_origine: str) -> Document:
    """Construit le `Document` à partir du front-matter. Ne produit aucune clause."""
    config = _config()["entete"]
    front = normaliser(texte_origine[: debut_du_corps(texte_origine)])
    _, _, motif_code = _motifs()

    document = Document(doc_id=doc_id, fichier=fichier, texte_origine=texte_origine)
    titre: list[str] = []
    code_vu = False

    for ligne in front.split("\n"):
        ligne = ligne.strip()
        if not ligne:
            continue

        if not code_vu and motif_code.match(ligne):
            document.code = motif_code.match(ligne).group(1)
            code_vu = True
            continue

        cle, separateur, valeur = ligne.partition(" : ")
        champ = config["cles"].get(cle.strip().lower()) if separateur else None
        if champ:
            valeur = valeur.strip()
            if champ.startswith("date_"):
                setattr(document, champ, _analyser_date(valeur))
            else:
                setattr(document, champ, valeur)
            continue

        # Ni code, ni paire clé/valeur : soit le titre (avant la première paire), soit
        # une phrase libre. « annule et remplace la version 2 » atterrit ici, et y reste.
        if not document.version and not document.date_application:
            titre.append(ligne)
        else:
            document.notes.append(ligne)

    document.titre = " ".join(titre)
    document.type, document.niveau_hierarchique = _type_et_niveau(document.code)
    return document


# ------------------------------------------------------------- découpage du corps en unités


@lru_cache(maxsize=1)
def _terminaisons_de_chapeau() -> tuple[str, ...]:
    return tuple(_config()["chapeau"]["terminaisons"])


@dataclass(frozen=True)
class Ligne:
    """Une ligne du corps, avec ses offsets dans le texte d'origine."""

    debut: int
    fin: int
    texte: str

    @property
    def vide(self) -> bool:
        return not self.texte.strip()


@dataclass
class Unite:
    """Un paragraphe du corps, avant explosion en clauses.

    `ref` vaut `None` pour un paragraphe non numéroté : celui-là devra passer la
    qualification pour devenir une clause (CAP08).
    """

    ref: str | None
    section: Section | None
    lignes: list[Ligne] = field(default_factory=list)
    # Décalage du corps sur la première ligne, le numéro « 4.2 » étant retiré.
    decalage: int = 0

    @property
    def debut(self) -> int:
        return self.lignes[0].debut + self.decalage

    @property
    def fin(self) -> int:
        return self.lignes[-1].fin

    @property
    def premiere_ligne(self) -> str:
        return self.lignes[0].texte[self.decalage :]

    def annonce_un_bloc(self) -> bool:
        """La **dernière** ligne se termine-t-elle par un marqueur de chapeau (« : ») ?

        C'est ce qui rattache le tableau de D1 §4.1 à son chapeau, alors qu'une ligne
        vide les sépare.
        """
        return self.lignes[-1].texte.rstrip().endswith(_terminaisons_de_chapeau())

    def commence_par_un_chapeau(self) -> bool:
        """La **première** ligne annonce-t-elle ce qui suit ?

        Distinct de :meth:`annonce_un_bloc` : dans « L'Animateur QSE doit : a) … b) … »,
        le chapeau ouvre l'unité et le dernier item la referme sur un point.
        """
        return self.premiere_ligne.rstrip().endswith(_terminaisons_de_chapeau())


def _lignes_avec_offsets(texte: str, depuis: int) -> list[Ligne]:
    lignes, position = [], 0
    for brute in texte.split("\n"):
        if position >= depuis:
            lignes.append(Ligne(debut=position, fin=position + len(brute), texte=brute))
        position += len(brute) + 1
    return lignes


def decouper_unites(texte_normalise: str, doc_id: str) -> tuple[list[Unite], list[Section]]:
    """Découpe le corps en paragraphes, en rattachant listes et tableaux à leur chapeau.

    Un paragraphe est un bloc de lignes non vides. Un bloc qui suit un chapeau — sans
    numéro à lui — n'ouvre pas une unité : il **prolonge** la précédente. C'est ce qui
    fait tenir ensemble « 4.1 La répartition… : » et les quatre lignes de son tableau,
    que sépare pourtant une ligne vide.
    """
    unites: list[Unite] = []
    sections: list[Section] = []
    section: Section | None = None

    lignes = _lignes_avec_offsets(texte_normalise, debut_du_corps(texte_normalise))
    blocs: list[list[Ligne]] = []
    courant: list[Ligne] = []
    for ligne in lignes:
        if ligne.vide:
            if courant:
                blocs.append(courant)
                courant = []
        else:
            courant.append(ligne)
    if courant:
        blocs.append(courant)

    for bloc in blocs:
        entete = bloc[0].texte

        titre = titre_de_section(entete)
        if titre is not None:
            numero, libelle = titre
            section = Section(
                section_id=f"{doc_id}::S{numero}",
                doc_id=doc_id,
                numero=numero,
                titre=f"{numero}. {libelle}",
            )
            sections.append(section)
            continue

        reference = reference_de_clause(entete)
        if reference is not None:
            ref, decalage = reference
            unites.append(Unite(ref=ref, section=section, lignes=list(bloc), decalage=decalage))
            continue

        # Bloc sans numéro : prolongement d'un chapeau, ou paragraphe orphelin.
        if unites and unites[-1].annonce_un_bloc():
            unites[-1].lignes.extend(bloc)
        else:
            unites.append(Unite(ref=None, section=section, lignes=list(bloc)))

    return unites, sections
