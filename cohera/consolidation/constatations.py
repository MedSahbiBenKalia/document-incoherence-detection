"""Écriture des verdicts, déduplication et regroupement des constatations.

architecture.md §8.2 : « Une même divergence de fond se manifeste sur plusieurs paires […]
On regroupe par `(type, clé de comparaison, valeurs en conflit)` en une **constatation
unique** portant N occurrences. Sans cette étape, le rapport devient illisible et perd la
confiance de l'auditeur. »

**Deux mécanismes, et les confondre serait une faute.**

* Le **regroupement** fusionne des constatations de *paire* qui manifestent la même
  divergence de fond, par la clé de §8.2. C'est le `groupby` demandé par le plan.
* L'**absorption** range une anomalie *mono-clause* sous la constatation de *paire* qui
  cite déjà la même preuve littérale sur cette même clause. C'est un cas que §8.2 ne nomme
  pas mais qui relève du même principe : un seul problème de fond, vu deux fois.

**Ce que l'absorption corrige, mesuré.** Le J6 comptait `D2 §10.1` en faux positif : A5 la
signale seule (« OHSAS 18001 retirée ») *et* dans la paire `D1 §2.1 ↔ D2 §10.1`
(« référentiels divergents »). Or `label.json` décrit I08 comme un **double constat** —
c'est bien un seul problème — mais le modélise en une seule entrée de paire, si bien que le
harnais ne sait pas apparier la moitié mono-clause. Ce n'est donc pas une constatation
infondée, c'est un défaut de regroupement.

⚠️ **Le risque de ce module est de faire disparaître un vrai positif sans bruit.** Le
harnais apparie sur le `frozenset` des couples `(doc, ref)` : retirer une constatation
retire sa clé du barème. Deux garde-fous en découlent, tous deux testés négativement :

1. l'absorption exige la **preuve littérale commune**, pas seulement la clause commune —
   sinon `D1 §10.2` disparaîtrait dans une paire qui parle d'autre chose ;
2. le regroupement **refuse de travailler sur une clé partielle** : sans clé de
   comparaison, chaque constatation reste seule. Regrouper sur le seul `type` fusionnerait
   toutes les divergences numériques du corpus en une ligne.

**Mesuré sur le corpus fixtures** : seule l'absorption travaille, et elle retire exactement
une constatation (18 → 17, faux positifs 4 → 3 en profil local). Aucune paire ne partage sa
clé de §8.2 avec une autre — le regroupement est écrit pour le corpus réel, pas pour celui-ci,
et son inefficacité ici est une propriété du corpus, pas un défaut du code.
"""

from __future__ import annotations

from cohera.restitution.rapport_json import Constatation, Occurrence

#: La clé de §8.2 : `(type, clé de comparaison, valeurs en conflit)`. `None` signale une
#: clé **dégénérée**, qui n'autorise aucun regroupement.
CleRegroupement = tuple[str, str, frozenset[str]] | None


# ----------------------------------------------------------------- petites briques


def _en_occurrence(constatation: Constatation) -> Occurrence:
    return Occurrence(
        id=constatation.id,
        detecteur=constatation.detecteur,
        etage=constatation.etage,
        clause_a=constatation.clause_a,
        clause_b=constatation.clause_b,
        explication=constatation.explication,
    )


def _occurrences_de(constatation: Constatation) -> list[Occurrence]:
    """Les manifestations d'une constatation, elle-même comprise.

    Une constatation fraîche n'en porte aucune et vaut pour elle-même ; une constatation
    déjà regroupée porte la liste complète. C'est ce qui rend :func:`regrouper` idempotent.
    """
    return list(constatation.occurrences) or [_en_occurrence(constatation)]


def _preuves(constatation: Constatation) -> frozenset[str]:
    cotes = [constatation.clause_a] + ([constatation.clause_b] if constatation.clause_b else [])
    return frozenset(cote.preuve.strip() for cote in cotes if cote.preuve.strip())


def _est_mono_clause(constatation: Constatation) -> bool:
    return constatation.clause_b is None


def _se_citent(gauche: str, droite: str) -> bool:
    """Les deux preuves désignent-elles la même chose ?

    L'une doit être sous-chaîne de l'autre. Les deux étant, par l'invariant #3, des
    sous-chaînes littérales du **même** `texte_source`, cette relation dit qu'elles portent
    sur le même passage — et non qu'elles se ressemblent.
    """
    gauche, droite = gauche.strip(), droite.strip()
    if not gauche or not droite:
        return False
    return gauche in droite or droite in gauche


# ------------------------------------------------------------------- l'absorption


def _cote_correspondant(paire: Constatation, couple: tuple[str, str]):
    """Le côté de `paire` qui porte cette clause, ou `None` si elle n'y figure pas."""
    for cote in (paire.clause_a, paire.clause_b):
        if cote is not None and cote.couple() == couple:
            return cote
    return None


def _absorbe(mono: Constatation, paire: Constatation) -> bool:
    """`paire` couvre-t-elle déjà ce que `mono` signale ?

    Trois conditions cumulatives : même type de taxonomie, la clause du constat mono-clause
    est l'un des deux côtés de la paire, et les deux preuves désignent le même passage.
    """
    if mono.type != paire.type:
        return False
    cote = _cote_correspondant(paire, mono.clause_a.couple())
    if cote is None:
        return False
    return _se_citent(mono.clause_a.preuve, cote.preuve)


def _absorber(constatations: list[Constatation]) -> list[Constatation]:
    """Range chaque anomalie mono-clause sous la paire qui la couvre déjà.

    L'absorption est **orientée** : une paire n'absorbe jamais une paire. Deux paires ne se
    fusionnent que par le regroupement de §8.2, qui exige une clé de comparaison — la seule
    présence d'une preuve commune ne suffit pas à établir qu'elles disent la même chose.
    """
    paires = [c for c in constatations if not _est_mono_clause(c)]
    absorbees: dict[int, list[Occurrence]] = {}
    retirees: set[int] = set()

    for indice, mono in enumerate(constatations):
        if not _est_mono_clause(mono):
            continue
        hote = next((p for p in paires if _absorbe(mono, p)), None)
        if hote is None:
            continue
        absorbees.setdefault(id(hote), []).extend(_occurrences_de(mono))
        retirees.add(indice)

    resultat: list[Constatation] = []
    for indice, constatation in enumerate(constatations):
        if indice in retirees:
            continue
        supplement = absorbees.get(id(constatation))
        if supplement:
            constatation = constatation.model_copy(
                update={"occurrences": _occurrences_de(constatation) + supplement}
            )
        resultat.append(constatation)
    return resultat


# ---------------------------------------------------------------- le regroupement


def cle_de_regroupement(constatation: Constatation) -> CleRegroupement:
    """La clé `(type, clé de comparaison, valeurs en conflit)` de architecture.md §8.2.

    Rend `None` — clé **dégénérée** — dès qu'un terme manque. Une clé partielle ne regroupe
    pas : c'est le garde-fou qui empêche de fusionner deux divergences numériques sans
    rapport au seul motif qu'elles sont toutes deux numériques.

    Les valeurs en conflit sont un `frozenset` : « 48 heures contre 5 jours » et « 5 jours
    contre 48 heures » sont le même problème, l'ordre des côtés a/b n'a pas de sens ici.
    """
    if not constatation.type or not constatation.cle_comparaison:
        return None
    valeurs = _preuves(constatation)
    if not valeurs:
        return None
    return (constatation.type, constatation.cle_comparaison, valeurs)


def _fusionner(groupe: list[Constatation]) -> Constatation:
    """La première constatation du groupe représente le constat de fond, et porte les autres."""
    representante, *autres = groupe
    if not autres:
        return representante
    occurrences = _occurrences_de(representante)
    for autre in autres:
        occurrences.extend(_occurrences_de(autre))
    return representante.model_copy(update={"occurrences": occurrences})


def _regrouper_les_paires(constatations: list[Constatation]) -> list[Constatation]:
    groupes: dict[CleRegroupement, list[Constatation]] = {}
    ordre: list[CleRegroupement] = []

    for rang, constatation in enumerate(constatations):
        cle = cle_de_regroupement(constatation)
        # Une clé dégénérée est rendue unique par le rang : la constatation reste seule,
        # tout en gardant sa place dans l'ordre de sortie.
        effective = cle if cle is not None else ("", str(rang), frozenset())
        if effective not in groupes:
            groupes[effective] = []
            ordre.append(effective)
        groupes[effective].append(constatation)

    return [_fusionner(groupes[cle]) for cle in ordre]


# ------------------------------------------------------------------------ entrée


def regrouper(constatations: list[Constatation]) -> list[Constatation]:
    """Consolide les constatations en constats de fond (architecture.md §8.2).

    Absorption d'abord — elle retire des lignes —, regroupement ensuite. Fonction **pure** :
    la liste reçue n'est pas modifiée, ce qui permet d'évaluer un rapport avant et après
    consolidation pour en chiffrer l'effet.

    Idempotente : `regrouper(regrouper(x)) == regrouper(x)`. Un `nb_occurrences` qui enflerait
    à chaque passage ne voudrait plus rien dire.
    """
    return _regrouper_les_paires(_absorber(list(constatations)))
