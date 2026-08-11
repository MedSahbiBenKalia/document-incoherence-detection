"""Grandeurs : valeur, unité, opérateur, normalisation SI.

CAP04 (délais imprécis : « dans la semaine » avec drapeau IMPRECIS),
CAP05 (12 mois = annuelle), CAP06 (jours ouvrés vs calendaires),
CAP07 (« au-delà de », « dépasse », « à plus de », « supérieure à » -> '>').

Un seuil numérique dont le rôle n'existe pas dans le registre des 10 (vitesse du vent en
km/h, durée d'une intervention qui ne correspond à aucun rôle enregistré) ne devient PAS
une Grandeur : il reste une Condition(type=SEUIL), voir regles/conditions.py. Chaque
Grandeur.role émis ici est vérifié contre le registre — une erreur explicite plutôt
qu'un rôle silencieusement inventé.

Toute date en toutes lettres (« 31 décembre 2024 ») est masquée avant la recherche de
nombre : sans ça, D1 §8.4 (« Jusqu'au 31 décembre 2024, ... fixé à un. ») confondrait le
31 du calendrier avec l'effectif recherché.
"""

from __future__ import annotations

import re
from functools import lru_cache

from cohera.extraction.config import charger_lexique_extraction, charger_registre_grandeurs
from cohera.extraction.frames import Dimension, Grandeur, Operateur, StatutGrandeur
from cohera.ingestion.modeles import Clause

_SECONDE_MINUTE = 60
_SECONDE_HEURE = 3600

# Marqueurs qui distinguent un délai de réponse (I01, I12, N01) d'un simple seuil de
# durée sur un autre objet (D1 §7.4 « moins de 30 minutes », D1 §10.1 « moins de deux
# heures ») : ces derniers n'ont pas de rôle et restent des Condition(SEUIL).
_MARQUEURS_DELAI = ("sous", "dans un délai de", "délai", "retard")


@lru_cache(maxsize=1)
def _lexique():
    return charger_lexique_extraction()


@lru_cache(maxsize=1)
def _registre():
    return charger_registre_grandeurs()


def _monotonie(role: str):
    return _registre().grandeurs[role].monotonie


# --------------------------------------------------------------------------- nombres


@lru_cache(maxsize=1)
def _motif_nombre() -> str:
    """L'alternation nombre, SANS groupe englobant : chaque site d'appel pose ses propres
    parenthèses (capturantes ou non) selon la position du groupe dont il a besoin."""
    mots = sorted(_lexique().grandeurs.nombres_lettres, key=len, reverse=True)
    return r"\d+(?:[.,]\d+)?|" + "|".join(re.escape(m) for m in mots)


def _valeur_nombre(brut: str) -> float:
    brut = brut.strip().lower()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", brut):
        return float(brut.replace(",", "."))
    return float(_lexique().grandeurs.nombres_lettres[brut])


@lru_cache(maxsize=1)
def _motif_date() -> re.Pattern:
    mois = "|".join(re.escape(m) for m in _lexique().dates.mois)
    return re.compile(rf"\d{{1,2}}(?:er)?\s+(?:{mois})\s+\d{{4}}", re.IGNORECASE)


def _sans_dates(texte: str) -> str:
    """Masque les dates en toutes lettres pour qu'un jour du calendrier ne soit jamais
    pris pour la valeur cherchée (D1 §8.4)."""
    return _motif_date().sub(" ", texte)


def _contexte_correspond(texte: str, role: str) -> bool:
    bas = texte.lower()
    return any(mot in bas for mot in _lexique().grandeurs.contextes_role.get(role, []))


# -------------------------------------------------------------------------- opérateur


def _detecter_operateur(texte: str) -> Operateur:
    """CAP07 — indépendante du rôle : testable seule."""
    motifs = sorted(_lexique().grandeurs.operateurs_seuil, key=lambda o: len(o.motif), reverse=True)
    for op in motifs:
        if re.search(re.escape(op.motif), texte, re.IGNORECASE):
            return op.operateur
    return Operateur.EGAL


# ------------------------------------------------------------------------ périodicité


def _secondes_periodicite(mois: int | None, jours: int | None) -> int:
    constantes = _lexique().grandeurs.constantes_temps
    secondes_jour = constantes["secondes_par_jour"]
    if jours is not None:
        return jours * secondes_jour
    secondes_an = constantes["jours_par_an"] * secondes_jour
    return round(mois * secondes_an / 12)


def _secondes_pour_unite(unite_brute: str) -> int | None:
    """« heure », « jour », « mois », « trimestre »… -> secondes pour 1 unité.

    heure/minute/seconde/jour passent par les constantes de base ; les unités de
    périodicité (semaine, mois, trimestre, semestre, an, année) passent par
    `noms_periode` + `periodicites`, pour que « 3 ans » et « tous les 3 ans » calculent
    exactement la même chose qu'« annuel »."""
    unite = unite_brute.strip().lower()
    constantes = _lexique().grandeurs.constantes_temps
    if unite.startswith("seconde"):
        return 1
    if unite.startswith("minute"):
        return _SECONDE_MINUTE
    if unite.startswith("heure"):
        return _SECONDE_HEURE
    if unite.startswith("jour"):
        return constantes["secondes_par_jour"]

    cle = _lexique().grandeurs.noms_periode.get(unite.split()[0])
    if cle is None:
        return None
    periodicite = _lexique().grandeurs.periodicites.get(cle)
    if periodicite is None or periodicite.ambigu:
        return None
    return _secondes_periodicite(periodicite.mois, periodicite.jours)


def _grandeur_periodicite_ambigue(texte: str, motif: str) -> Grandeur:
    role = "periodicite"
    return Grandeur(
        role=role,
        dimension=Dimension.TEMPS_PERIODE,
        valeur=0,
        unite=motif,
        valeur_si=None,
        surface=_surface(texte, motif),
        monotonie=_monotonie(role),
        statut=StatutGrandeur.AMBIGU,
    )


@lru_cache(maxsize=1)
def _motif_adjectif_periodicite() -> re.Pattern:
    cles = sorted(_lexique().grandeurs.periodicites, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(c) for c in cles) + r")\w*", re.IGNORECASE)


@lru_cache(maxsize=1)
def _motif_fois_par() -> re.Pattern:
    return re.compile(r"(" + _motif_nombre() + r")\s+fois\s+par\s+(\w+)", re.IGNORECASE)


@lru_cache(maxsize=1)
def _motif_cadence() -> re.Pattern:
    """« tous les 3 mois », « chaque trimestre », « toutes les semaines » — le nombre est
    optionnel (sous-entendu 1)."""
    return re.compile(
        r"\b(?:tous\s+les|toutes\s+les|chaque)\s+(?:(" + _motif_nombre() + r")\s+)?(\w+)",
        re.IGNORECASE,
    )


def _tenter_periodicite(texte: str) -> Grandeur | None:
    fois_par = _motif_fois_par().search(texte)
    if fois_par:
        nombre, unite = fois_par.group(1), fois_par.group(2)
        secondes_unite = _secondes_pour_unite(unite)
        if secondes_unite is not None:
            valeur = _valeur_nombre(nombre)
            role = "periodicite"
            return Grandeur(
                role=role,
                dimension=Dimension.TEMPS_PERIODE,
                valeur=valeur,
                unite=f"fois par {unite}",
                valeur_si=round(secondes_unite / valeur),
                operateur=_detecter_operateur(texte),
                surface=fois_par.group(0),
                monotonie=_monotonie(role),
            )

    cadence = _motif_cadence().search(texte)
    if cadence:
        unite = cadence.group(2)
        cle_periodicite = _lexique().grandeurs.noms_periode.get(unite.lower())
        if cle_periodicite is not None:
            if _lexique().grandeurs.periodicites[cle_periodicite].ambigu:
                return _grandeur_periodicite_ambigue(texte, cadence.group(0))
            nombre = cadence.group(1)
            valeur = _valeur_nombre(nombre) if nombre else 1
            secondes_unite = _secondes_pour_unite(unite)
            role = "periodicite"
            return Grandeur(
                role=role,
                dimension=Dimension.TEMPS_PERIODE,
                valeur=valeur,
                unite=unite,
                valeur_si=round(valeur * secondes_unite),
                operateur=_detecter_operateur(texte),
                surface=cadence.group(0),
                monotonie=_monotonie(role),
            )

    adjectif = _motif_adjectif_periodicite().search(texte)
    if adjectif:
        cle = next(
            c for c in _lexique().grandeurs.periodicites if adjectif.group(0).lower().startswith(c)
        )
        if _lexique().grandeurs.periodicites[cle].ambigu:
            return _grandeur_periodicite_ambigue(texte, adjectif.group(0))
        periodicite = _lexique().grandeurs.periodicites[cle]
        role = "periodicite"
        return Grandeur(
            role=role,
            dimension=Dimension.TEMPS_PERIODE,
            valeur=1,
            unite=cle,
            valeur_si=_secondes_periodicite(periodicite.mois, periodicite.jours),
            operateur=_detecter_operateur(texte),
            surface=adjectif.group(0),
            monotonie=_monotonie(role),
        )

    return None


# --------------------------------------------------------------------------- surface


def _surface(texte: str, motif: str) -> str:
    trouve = re.search(re.escape(motif), texte, re.IGNORECASE)
    return trouve.group(0) if trouve else motif


# ------------------------------------------------------------------ durée simple (TEMPS)


@lru_cache(maxsize=1)
def _motif_duree() -> re.Pattern:
    return re.compile(
        r"("
        + _motif_nombre()
        + r")\s*(secondes?|minutes?|heures?|jours?(?:\s+ouvr[ée]s?|\s+ouvrables?)?"
        + r"|semaines?|mois|trimestres?|semestres?|ann[ée]es?|ans?)",
        re.IGNORECASE,
    )


def _tenter_duree_temps(texte: str, role: str) -> Grandeur | None:
    """Une durée TEMPS (pas TEMPS_PERIODE) : delai, duree_conservation, duree_formation,
    validite_habilitation quand elle est exprimée « pendant/sous N ans/heures » plutôt
    qu'en cadence."""
    trouve = _motif_duree().search(texte)
    if trouve:
        valeur = _valeur_nombre(trouve.group(1))
        unite = trouve.group(2)
        secondes_unite = _secondes_pour_unite(unite)
        if secondes_unite is None:
            return None
        valeur_si = round(valeur * secondes_unite)
        grandeur = Grandeur(
            role=role,
            dimension=Dimension.TEMPS,
            valeur=valeur,
            unite=unite,
            valeur_si=valeur_si,
            operateur=_detecter_operateur(texte),
            surface=trouve.group(0),
            monotonie=_monotonie(role),
        )
        if "ouvr" in unite.lower():
            constantes = _lexique().grandeurs.constantes_temps
            ratio = constantes["jours_calendaires_par_semaine"] / constantes["jours_ouvres_par_semaine"]
            grandeur.valeur_si_calendaire = round(round(valeur * ratio) * constantes["secondes_par_jour"])
            grandeur.qualificateurs["calendrier"] = "ouvre"
        else:
            grandeur.qualificateurs["calendrier"] = "calendaire"
        return grandeur

    # Cadence utilisée comme durée de validité (« tous les 3 ans » = habilitation valable
    # 3 ans) : même calcul que la périodicité, rôle différent.
    cadence = _tenter_periodicite(texte)
    if cadence is not None and cadence.valeur_si is not None:
        return Grandeur(
            role=role,
            dimension=Dimension.TEMPS,
            valeur=cadence.valeur,
            unite=cadence.unite,
            valeur_si=cadence.valeur_si,
            operateur=cadence.operateur,
            surface=cadence.surface,
            monotonie=_monotonie(role),
        )
    return None


# ---------------------------------------------------------------- autres dimensions


@lru_cache(maxsize=1)
def _motif_db() -> re.Pattern:
    return re.compile(r"(" + _motif_nombre() + r")\s*dB\(A\)", re.IGNORECASE)


@lru_cache(maxsize=1)
def _motif_metres() -> re.Pattern:
    return re.compile(r"(" + _motif_nombre() + r")\s*mètres?\b", re.IGNORECASE)


def _grandeur_exposition(texte: str) -> Grandeur | None:
    trouve = _motif_db().search(texte)
    if not trouve:
        return None
    valeur = _valeur_nombre(trouve.group(1))
    role = "seuil_exposition"
    return Grandeur(
        role=role,
        dimension=Dimension.PRESSION_ACOUSTIQUE,
        valeur=valeur,
        unite="dB(A)",
        valeur_si=round(valeur),
        operateur=_detecter_operateur(texte),
        surface=trouve.group(0),
        monotonie=_monotonie(role),
        qualificateurs={"pondération": "A"},
    )


def _grandeur_declenchement(texte: str) -> Grandeur | None:
    trouve = _motif_metres().search(texte)
    if not trouve:
        return None
    valeur = _valeur_nombre(trouve.group(1))
    role = "seuil_declenchement"
    return Grandeur(
        role=role,
        dimension=Dimension.LONGUEUR,
        valeur=valeur,
        unite="mètres",
        valeur_si=round(valeur),
        operateur=_detecter_operateur(texte),
        surface=trouve.group(0),
        monotonie=_monotonie(role),
    )


def _grandeur_effectif(texte: str) -> Grandeur | None:
    if not _contexte_correspond(texte, "effectif_minimum"):
        return None
    trouve = re.search(_motif_nombre(), texte, re.IGNORECASE)
    if not trouve:
        return None
    valeur = _valeur_nombre(trouve.group(0))
    role = "effectif_minimum"
    return Grandeur(
        role=role,
        dimension=Dimension.EFFECTIF,
        valeur=valeur,
        unite="personne(s)",
        valeur_si=round(valeur),
        operateur=_detecter_operateur(texte),
        surface=trouve.group(0),
        monotonie=_monotonie(role),
    )


# -------------------------------------------------------------------------- délais


def _grandeur_imprecise(texte: str) -> Grandeur | None:
    """CAP04 — jamais `valeur_si=None`, toujours `statut=IMPRECIS`."""
    bas = texte.lower()
    for entree in _lexique().grandeurs.delais_imprecis:
        if entree.motif in bas:
            role = "delai"
            return Grandeur(
                role=role,
                dimension=Dimension.TEMPS,
                valeur=entree.valeur_si,
                unite="secondes",
                valeur_si=entree.valeur_si,
                operateur=_detecter_operateur(texte),
                surface=_surface(texte, entree.motif),
                monotonie=_monotonie(role),
                statut=StatutGrandeur.IMPRECIS,
            )
    return None


def _grandeur_delai(texte: str) -> Grandeur | None:
    if not any(marqueur in texte.lower() for marqueur in _MARQUEURS_DELAI):
        return None
    return _tenter_duree_temps(texte, "delai")


# ------------------------------------------------------------------------- l'entrée


def extraire_grandeurs(clause: Clause) -> list[Grandeur]:
    """Une clause porte au plus une grandeur enregistrée dans ce corpus — la fonction
    renvoie une liste pour rester extensible, mais s'arrête au premier rôle trouvé."""
    texte = _sans_dates(clause.texte_source)

    imprecise = _grandeur_imprecise(texte)
    if imprecise is not None:
        return [imprecise]

    for role in ("duree_conservation", "duree_formation", "validite_habilitation"):
        if _contexte_correspond(texte, role):
            grandeur = _tenter_duree_temps(texte, role)
            if grandeur is not None:
                return [grandeur]

    grandeur = _grandeur_effectif(texte)
    if grandeur is not None:
        return [grandeur]

    grandeur = _tenter_periodicite(texte)
    if grandeur is not None:
        return [grandeur]

    grandeur = _grandeur_delai(texte)
    if grandeur is not None:
        return [grandeur]

    grandeur = _grandeur_exposition(texte)
    if grandeur is not None:
        return [grandeur]

    grandeur = _grandeur_declenchement(texte)
    if grandeur is not None:
        return [grandeur]

    return []
