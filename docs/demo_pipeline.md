# COHERA — Démonstration du pipeline de bout en bout

**Simulation commentée sur deux documents QHSE volontairement incohérents.**
Aucun code : à chaque étage, on montre *ce qui entre*, *ce qui sort*, et *pourquoi*.

---

## 0. Les deux documents d'entrée

### `D1 — PR-QSE-04.txt` · Procédure de contrôle des EPI (v3, 2024)

```
1. OBJET

1.1 La présente procédure définit les modalités de contrôle des équipements
    de protection individuelle (EPI) sur le site de Radès.
    Ce document est diffusé à l'ensemble des services.

2. RESPONSABILITÉS

2.1 Le Responsable QSE valide chaque fiche de contrôle sous 48 heures.
2.2 Le port du casque est obligatoire en zone A.
2.3 L'opérateur peut refuser un EPI visiblement défectueux.
2.4 Toute anomalie détectée est signalée au chef d'atelier sous 24 heures.

3. PÉRIODICITÉ

3.1 Le contrôle des EPI doit être renouvelé tous les trimestres.
3.2 Il est archivé pendant 3 ans.

4. RÉFÉRENCES

4.1 La présente procédure est conforme à la norme ISO 45001:2018.
4.2 Les modalités de retrait des EPI sont décrites au § 6.3.
```

### `D2 — POL-SEC-01.txt` · Politique sécurité du site (v2, 2025)

```
1. PRINCIPES

1.1 La politique sécurité s'applique à tout intervenant présent sur le site
    de Radès.

2. RÔLES

2.1 Le Référent sécurité est chargé de valider les fiches de contrôle dans un
    délai de 5 jours ouvrés.
2.2 En zone A, il est recommandé de porter un casque.
2.3 Le port de gants est obligatoire lors des opérations de manutention.
2.4 Les écarts constatés sont remontés à la hiérarchie dans la semaine.

3. VÉRIFICATIONS

3.1 La vérification des équipements de protection est réalisée deux fois par an.
3.2 Les enregistrements de vérification sont conservés pendant 5 ans.

4. RÉFÉRENTIEL

4.1 Le site applique le référentiel OHSAS 18001.

5. CAS PARTICULIER

5.1 En cas d'incident grave, la fiche de contrôle est validée sous 24 heures.
```

### 0.1 Vérité terrain — ce que le système *devrait* trouver

| # | Clauses | Type (taxonomie) | Difficulté attendue |
|---|---|---|---|
| **V1** | D1 §2.1 ↔ D2 §2.1 | **Numeric** — délai de validation 48 h vs 5 jours ouvrés | facile *(si l'alias acteur est trouvé)* |
| **V2** | D1 §2.2 ↔ D2 §2.2 | **Perspective** — casque *obligatoire* vs *recommandé* en zone A | moyenne |
| **V3** | D1 §3.1 ↔ D2 §3.1 | **Numeric** — périodicité trimestrielle vs semestrielle | moyenne *(2 alias nécessaires)* |
| **V4** | D1 §3.2 ↔ D2 §3.2 | **Numeric** — conservation 3 ans vs 5 ans | difficile *(anaphore + 2 alias faibles)* |
| **V5** | D1 §4.1 ↔ D2 §4.1 | **Factual** — ISO 45001:2018 vs OHSAS 18001 (retirée) | facile |
| **V6** | D1 §4.2 (seule) | **Factual** — renvoi vers un § 6.3 inexistant | facile |
| **V7** | D1 §2.4 ↔ D2 §2.4 | **Numeric** — délai de signalement 24 h vs « dans la semaine » | **très difficile** *(aucun mot commun)* |

### 0.2 Le piège — ce que le système ne doit **pas** signaler

| # | Clauses | Pourquoi c'est un piège |
|---|---|---|
| **N1** | D1 §2.1 (48 h) ↔ D2 §5.1 (24 h) | Même clé de comparaison, valeurs différentes → **un détecteur naïf crie au conflit**. Or D2 §5.1 est un *cas particulier plus strict* : une spécialisation compatible, pas une contradiction. |
| **N2** | D1 §2.2 (casque) ↔ D2 §2.3 (gants) | Deux obligations de port d'EPI, formulations très proches, objets différents. Le canal vectoriel va les rapprocher ; la cascade doit les séparer. |
| **N3** | D1 §1.1 ↔ D2 §1.1 | Deux phrases de cadrage citant le même site. Similarité élevée, **aucune valeur prescriptive** : ne doivent jamais atteindre le NLI. |

---

# ÉTAGE L0 — Segmentation

**Ce que fait l'étage :** transformer deux fichiers texte bruts en unités normatives auto-portantes.

### L0.2 — Détection de structure

Le détecteur de numérotation `^\s*(\d+(\.\d+)*)[\).\-\s]+` s'accroche sur `1.`, `1.1`, `2.1`… et les titres en capitales (`OBJET`, `RESPONSABILITÉS`) confirment les niveaux 1. Arbre reconstruit pour D1 :

```
D1 ── 1. OBJET ──────────── 1.1
   ├─ 2. RESPONSABILITÉS ── 2.1, 2.2, 2.3, 2.4
   ├─ 3. PÉRIODICITÉ ────── 3.1, 3.2
   └─ 4. RÉFÉRENCES ─────── 4.1, 4.2
```

📌 **Information capitale extraite sans le savoir :** D1 s'arrête à la section 4. Le renvoi « § 6.3 » de la clause 4.2 est donc déjà, à ce stade, **structurellement invalide**. C'est V6, détectée avant même la construction du graphe.

### L0.5 — Qualification : quelles phrases deviennent des clauses ?

| Phrase | Marqueur déontique | Grandeur | Référence | Verbe définitionnel | → |
|---|---|---|---|---|---|
| D1 §1.1 « …définit les modalités… » | ✗ | ✗ | ✗ | ✅ `définit` | **Clause** (`DEFINITION`) |
| D1 « Ce document est diffusé… » | ✗ | ✗ | ✗ | ✗ | ❌ **rattachée en `contexte`** |
| D1 §2.1 « …valide…sous 48 heures » | ✅ présent prescriptif | ✅ 48 h | ✗ | ✗ | **Clause** |
| D1 §3.2 « Il est archivé pendant 3 ans » | ✅ | ✅ 3 ans | ✗ | ✗ | **Clause** ⚠️ anaphore |

**Résultat : 9 clauses dans D1, 9 dans D2** (une phrase de D1 rattachée en contexte, non comptée).

### L0.6 — Autonomisation : l'étape qui sauve V4

Une seule clause déclenche le détecteur d'anaphore, mais c'est celle qui porte une incohérence.

```
AVANT   D1::C06  « Il est archivé pendant 3 ans. »
                  ↑ pronom sujet en tête, aucun référent dans la phrase

        → appel LLM (lot de 1), contexte = clause précédente + chemin de section

APRÈS   D1::C06  texte_autonome :
                  « Le contrôle des EPI est archivé pendant 3 ans. »
                  texte_source conservé tel quel pour la citation en preuve
```

> **Sans cette étape, V4 est perdue.** Le NLI, qui voit la paire hors contexte, aurait comparé « Il est archivé pendant 3 ans » à « Les enregistrements de vérification sont conservés pendant 5 ans » : aucun sujet commun, aucun concept partagé, verdict *neutre*. **Une clause sur dix-huit avait besoin de cette réécriture, et c'est précisément une clause fautive.**

### L0 — Sortie

| ID | § | texte_autonome (extrait) |
|---|---|---|
| `D1::C01` | 1.1 | La présente procédure définit les modalités de contrôle des EPI sur le site de Radès. |
| `D1::C02` | 2.1 | Le Responsable QSE valide chaque fiche de contrôle sous 48 heures. |
| `D1::C03` | 2.2 | Le port du casque est obligatoire en zone A. |
| `D1::C04` | 2.3 | L'opérateur peut refuser un EPI visiblement défectueux. |
| `D1::C05` | 2.4 | Toute anomalie détectée est signalée au chef d'atelier sous 24 heures. |
| `D1::C06` | 3.1 | Le contrôle des EPI doit être renouvelé tous les trimestres. |
| `D1::C07` | 3.2 | **Le contrôle des EPI** est archivé pendant 3 ans. ← *réécrite* |
| `D1::C08` | 4.1 | La présente procédure est conforme à la norme ISO 45001:2018. |
| `D1::C09` | 4.2 | Les modalités de retrait des EPI sont décrites au § 6.3. |
| `D2::C01` | 1.1 | La politique sécurité s'applique à tout intervenant présent sur le site de Radès. |
| `D2::C02` | 2.1 | Le Référent sécurité est chargé de valider les fiches de contrôle dans un délai de 5 jours ouvrés. |
| `D2::C03` | 2.2 | En zone A, il est recommandé de porter un casque. |
| `D2::C04` | 2.3 | Le port de gants est obligatoire lors des opérations de manutention. |
| `D2::C05` | 2.4 | Les écarts constatés sont remontés à la hiérarchie dans la semaine. |
| `D2::C06` | 3.1 | La vérification des équipements de protection est réalisée deux fois par an. |
| `D2::C07` | 3.2 | Les enregistrements de vérification sont conservés pendant 5 ans. |
| `D2::C08` | 4.1 | Le site applique le référentiel OHSAS 18001. |
| `D2::C09` | 5.1 | En cas d'incident grave, la fiche de contrôle est validée sous 24 heures. |

---

# ÉTAGE L1 — Extraction des *Clause Frames*

**Ce que fait l'étage :** convertir chaque clause en structure comparable. **Les règles passent en premier ; le LLM ne comble que les trous.**

### L1.1 — Trace détaillée sur une clause

```
ENTRÉE   D1::C02  « Le Responsable QSE valide chaque fiche de contrôle sous 48 heures. »

┌─ RÈGLES (déterministe, ~0,2 ms) ───────────────────────────────────────────┐
│                                                                             │
│  Modalité      « valide » = présent de l'indicatif, sujet = rôle du         │
│                 gazetteer QHSE → PRESCRIPTIF                                │
│                 → OBLIGATION, force 3, confiance 0,78                       │
│                                                                             │
│  Négation      aucun marqueur (ne…pas, aucun, sans) → false                 │
│                                                                             │
│  Grandeur      « sous 48 heures » → patron DELAI                            │
│                 dimension TEMPS · rôle « delai » · 48 heure                 │
│                 → valeur_si = 172 800 s                                     │
│                                                                             │
│  Acteur        « Responsable QSE » ∈ gazetteer (120 rôles) → RESP_QSE       │
│                                                                             │
│  Portée        « chaque » → quantificateur UNIVERSEL                        │
│                                                                             │
│  Conditions    aucun marqueur (en cas de, si, lorsque, sauf) → []           │
│                                                                             │
│  Références    aucune                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │  champs restants à null : action, objet
                                    ▼
┌─ LLM (Mistral 7B Q4, lot de 8 clauses, JSON Schema contraint) ─────────────┐
│  Le prompt contient les champs DÉJÀ remplis, marqués non modifiables.       │
│  Le modèle ne peut compléter que `action` et `objet`.                       │
│    action → « valider » (lemme)                                             │
│    objet  → « chaque fiche de contrôle »                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Frame produite :**

```json
{
  "clause_id": "D1::C02",
  "modalite": "OBLIGATION", "force": 3, "negation": false,
  "acteur":  {"surface": "Le Responsable QSE", "concept_id": "K_RESP_QSE"},
  "action":  {"surface": "valide",  "lemme": "valider"},
  "objet":   {"surface": "chaque fiche de contrôle", "concept_id": "K_FICHE_CTRL"},
  "quantites": [{"role": "delai", "dimension": "TEMPS", "valeur": 48, "unite": "heure",
                 "valeur_si": 172800, "surface": "sous 48 heures"}],
  "conditions": [],
  "portee": {"quantificateur": "UNIVERSEL", "surface": "chaque"},
  "references": [],
  "confiance_extraction": 0.86,
  "source_extraction": {"modalite":"REGLE","quantites":"REGLE","acteur":"REGLE",
                        "action":"LLM","objet":"LLM"}
}
```

📌 `source_extraction` sera relu à l'étage L4 : un verdict ferme n'est autorisé que si **tous les champs comparés viennent de `REGLE`**. Ici `acteur` et `quantites` sont issus des règles → un verdict de divergence de valeur sur cette clause pourra être ferme.

### L1.2 — Le point délicat : « 5 jours ouvrés »

```
D2::C02  « …dans un délai de 5 jours ouvrés. »

  patron DELAI + qualificateur « ouvrés » détecté
  → valeur_si            = 432 000 s      (5 × 86 400, durée nominale)
  → valeur_si_calendaire = 604 800 s      (≈ 7 jours calendaires réels)
  → qualificateurs       = {"calendrier": "ouvre"}
```

Les **deux** valeurs sont stockées. Comparée à 48 h, la divergence est réelle dans les deux conventions — la constatation est donc robuste, et le rapport pourra le dire.

### L1.3 — Deux échecs d'extraction, assumés

```
D2::C05  « Les écarts constatés sont remontés à la hiérarchie dans la semaine. »

  Grandeur   « dans la semaine » → ⚠️ le patron DELAI ne couvre pas les
             expressions vagues (« dans la semaine », « sous quinzaine »,
             « rapidement », « dans les meilleurs délais »)
             → quantites = []          ← V7 commence à se perdre ici
  Acteur     « la hiérarchie » ∉ gazetteer, NER → rien
             → acteur = null, complété par LLM en surface seulement
  confiance_extraction = 0,54
```

```
D1::C05  « Toute anomalie détectée est signalée au chef d'atelier sous 24 heures. »

  Grandeur   ✅ 24 h → 86 400 s
  Acteur     ✅ chef d'atelier ∈ gazetteer
  Objet      « anomalie détectée » → concept nouveau K_ANOMALIE
  confiance_extraction = 0,81
```

Les deux clauses de V7 sont correctement segmentées, mais **l'une n'a pas de grandeur extraite**. La conséquence se manifestera à l'étage L3.

### L1.4 — Bilan de l'étage sur les 18 clauses

| Indicateur | Valeur |
|---|---|
| Clauses traitées | 18 |
| Champs remplis par règles | 61 % |
| Clauses n'ayant nécessité **aucun** appel LLM | 7 / 18 |
| Appels LLM d'extraction (lots de 8) | **2** |
| Appels LLM d'autonomisation | **1** |
| Confiance moyenne d'extraction | 0,79 |
| Clauses marquées `EXTRACTION_INCERTAINE` (< 0,60) | 1 (`D2::C05`) |

---

# ÉTAGE L2 — Construction du graphe

**Ce que fait l'étage :** matérialiser les clauses, concepts, grandeurs et normes dans Neo4j, puis **construire le pont entre les deux documents**.

### L2.1 — Chargement brut

| Élément | Volume |
|---|---|
| `Document` | 2 |
| `Section` | 9 |
| `Clause` | 18 |
| `Concept` (avant alignement) | 31 |
| `Quantite` | 11 |
| `NormeExterne` | 2 |
| Arêtes structurelles + extraction | 96 |

À ce stade, **le graphe est en deux morceaux** :

```
   ┌──────────── D1 ────────────┐        ┌──────────── D2 ────────────┐
   │  K_RESP_QSE                │        │  K_REFERENT_SEC            │
   │  K_FICHE_CTRL              │        │  K_FICHES_CTRL             │
   │  K_EPI                     │        │  K_EQUIP_PROTECTION        │
   │  K_CONTROLE                │        │  K_VERIFICATION            │
   │  K_ARCHIVER                │        │  K_CONSERVER               │
   │  K_CASQUE, K_ZONE_A        │        │  K_CASQUE, K_ZONE_A        │
   └────────────────────────────┘        └────────────────────────────┘
        aucune arête entre les deux, sauf sur « casque » et « zone A »
```

> **Sur 7 incohérences attendues, 5 sont invisibles à ce stade.** Le graphe voit deux documents qui ne se parlent pas. Tout se joue dans l'étape suivante.

### L2.2 — Le pont inter-documents, en cascade de coût

```
NIVEAU 1 · Identité normalisée (gratuit)
────────────────────────────────────────────────────────────────────────
  « casque »       ≡ « casque »        → ALIAS_DE {EXACT, 1.00}
  « zone A »       ≡ « zone A »        → ALIAS_DE {EXACT, 1.00}
  « site de Radès »≡ « site de Radès » → ALIAS_DE {EXACT, 1.00}
  « fiche de contrôle » ≡ « fiches de contrôle »   (lemmatisation, pluriel)
                                        → ALIAS_DE {EXACT, 1.00}   ⭐ débloque V1

NIVEAU 2 · Lexique métier QHSE (gratuit)
────────────────────────────────────────────────────────────────────────
  « EPI » ≡ « équipements de protection individuelle »
          ≡ « équipements de protection »
                                        → ALIAS_DE {LEXIQUE, 0.95} ⭐ débloque V3

NIVEAU 3 · Similarité vectorielle (bge-m3, ~10 ms/paire)
────────────────────────────────────────────────────────────────────────
  Responsable QSE  ↔ Référent sécurité       cos = 0.88  ≥ 0.86
                                        → ALIAS_DE {VECTEUR, 0.88} ⭐ débloque V1
  contrôle         ↔ vérification            cos = 0.91  ≥ 0.86
                                        → ALIAS_DE {VECTEUR, 0.91} ⭐ débloque V3
  archiver         ↔ conserver               cos = 0.79  → ZONE GRISE ↓
  contrôle des EPI ↔ enregistrements de vérification
                                             cos = 0.74  → ZONE GRISE ↓
  anomalie         ↔ écart                   cos = 0.68  < 0.72  ✗ REJETÉ
  chef d'atelier   ↔ hiérarchie              cos = 0.61  < 0.72  ✗ REJETÉ
  signaler         ↔ remonter                cos = 0.70  < 0.72  ✗ REJETÉ
  casque           ↔ gants                   cos = 0.66  < 0.72  ✗ REJETÉ  ✅ bon rejet (N2)

NIVEAU 4 · Arbitrage LLM (zone grise uniquement — 2 appels)
────────────────────────────────────────────────────────────────────────
  Q : « Dans un document QHSE, "archiver" et "conserver" appliqués à des
        documents désignent-ils la même opération ? OUI / NON / INCERTAIN »
  R : OUI — « conservation et archivage désignent la même obligation de
      rétention documentaire »        → ALIAS_DE {LLM, 0.80}

  Q : « "Le contrôle des EPI" et "les enregistrements de vérification"
        désignent-ils le même objet ? »
  R : OUI — « les enregistrements sont la trace documentaire du contrôle »
                                       → ALIAS_DE {LLM, 0.78}   ⭐ débloque V4
```

### L2.3 — Le graphe après pontage

```
                    ┌─────────────────────────────────────┐
                    │      CONCEPTS CANONIQUES            │
                    └─────────────────────────────────────┘

   D1::C02 ──IMPOSE_A──►┌─────────────┐◄──IMPOSE_A── D2::C02
   "sous 48 heures"     │ K_RESP_QSE  │              "5 jours ouvrés"
        │               │ ≡ Référent  │                   │
        │               │   sécurité  │                   │
        │               │  (vec 0.88) │                   │
        │               └─────────────┘                   │
        │                                                 │
        └──MENTIONNE──►┌──────────────┐◄──MENTIONNE───────┘
                       │K_FICHE_CTRL  │
                       └──────────────┘
                              ▲
                              └──MENTIONNE── D2::C09  "sous 24 heures"
                                             + condition « incident grave »

   D1::C06 ──MENTIONNE──►┌────────┐◄──MENTIONNE── D2::C06
   "tous les trimestres" │ K_EPI  │              "deux fois par an"
   D1::C07 ──MENTIONNE──►│(lex.95)│◄──MENTIONNE── D2::C07
   "3 ans"               └────────┘              "5 ans"
                              ▲
                              └── K_CONTROLE ≡ K_VERIFICATION (vec 0.91)
                                  K_ARCHIVER ≡ K_CONSERVER    (LLM 0.80)

   D1::C03 ──MENTIONNE──►┌──────────┐◄──MENTIONNE── D2::C03
   OBLIGATION force 3    │ K_CASQUE │              RECOMMANDATION force 2
                         │ K_ZONE_A │
                         └──────────┘
                              ✗  aucun lien vers K_GANTS (cos 0.66)  ✅

   D1::C08 ──CITE_NORME──► [ISO 45001 : 2018 · en vigueur]
   D2::C08 ──CITE_NORME──► [OHSAS 18001 · RETIRÉE, remplacée par ISO 45001]

   D1::C09 ──RENVOIE_A──► ✗ § 6.3 : NŒUD INEXISTANT

   D1::C05 ─── K_ANOMALIE, K_CHEF_ATELIER, K_SIGNALER      ⚠️ ÎLOT ISOLÉ
   D2::C05 ─── K_ECART,   K_HIERARCHIE,   K_REMONTER       ⚠️ ÎLOT ISOLÉ
        └─── aucun pont : V7 est déjà condamnée ────┘
```

### L2.4 — Clés de comparaison calculées

| Clause | `cle_comparaison` | Valeur |
|---|---|---|
| `D1::C02` | `(RESP_QSE, VALIDER, FICHE_CTRL, TEMPS, delai)` | 172 800 s |
| `D2::C02` | `(RESP_QSE, VALIDER, FICHE_CTRL, TEMPS, delai)` | 432 000 s |
| `D2::C09` | `(RESP_QSE, VALIDER, FICHE_CTRL, TEMPS, delai)` | 86 400 s |
| `D1::C06` | `(*, CONTROLER, EPI, TEMPS_PERIODE, periodicite)` | 7 884 000 s |
| `D2::C06` | `(*, CONTROLER, EPI, TEMPS_PERIODE, periodicite)` | 15 768 000 s |
| `D1::C07` | `(*, ARCHIVER, EPI, TEMPS, duree_conservation)` | 94 608 000 s |
| `D2::C07` | `(*, ARCHIVER, EPI, TEMPS, duree_conservation)` | 157 680 000 s |
| `D1::C05` | `(CHEF_ATELIER, SIGNALER, ANOMALIE, TEMPS, delai)` | 86 400 s |
| `D2::C05` | `(HIERARCHIE, REMONTER, ECART, —, —)` | *aucune grandeur* |

`*` = acteur absent (tournure passive) : la clé accepte le joker.

📌 Trois groupes de clés identiques apparaissent, chacun avec des valeurs différentes. **Les incohérences V1, V3 et V4 sont, à ce stade, déjà visibles par un simple `GROUP BY`** — sans NLI, sans LLM, sans comparaison de texte. C'est le rendement de l'investissement fait en L1.

Et les deux dernières lignes montrent l'échec : les clés de V7 n'ont **rien** en commun.

---

# ÉTAGE L3 — Ciblage

**Espace théorique : 9 × 9 = 81 paires inter-documents.**

### Canal 1 — Structurel

```
D1::C09 ──RENVOIE_A──► « § 6.3 »
                        résolution dans D1 : sections 1, 2, 3, 4 → ÉCHEC
                        résolution inter-documents : aucune section 6.3 → ÉCHEC
   ⚡ ANOMALIE DIRECTE — aucune paire nécessaire → V6 remontée immédiatement
```

**0 paire produite, 1 constatation.** Le canal le moins productif en volume est le plus rentable en coût.

### Canal 2 — Clé de comparaison

| Paire | Clé | Valeurs |
|---|---|---|
| `D1::C02 ↔ D2::C02` | complète | 172 800 vs 432 000 |
| `D1::C02 ↔ D2::C09` | complète | 172 800 vs 86 400 |
| `D1::C06 ↔ D2::C06` | joker acteur | 7 884 000 vs 15 768 000 |
| `D1::C07 ↔ D2::C07` | joker acteur | 94 608 000 vs 157 680 000 |

**4 paires, score 1.00.** Trois d'entre elles sont des vraies incohérences ; la quatrième est le piège N1.

### Canal 3 — Conceptuel (≥ 2 concepts partagés, idf > 1,5)

| Paire | Concepts partagés | Score IDF |
|---|---|---|
| `D1::C03 ↔ D2::C03` | K_CASQUE, K_ZONE_A, K_PORTER | 9,2 |
| `D1::C02 ↔ D2::C02` | K_RESP_QSE, K_VALIDER, K_FICHE_CTRL | 8,4 |
| `D1::C06 ↔ D2::C06` | K_EPI, K_CONTROLER | 7,8 |
| `D1::C02 ↔ D2::C09` | K_VALIDER, K_FICHE_CTRL | 6,1 |
| `D1::C07 ↔ D2::C07` | K_EPI, K_ARCHIVER | 5,4 |
| `D1::C08 ↔ D2::C08` | K_REFERENTIEL, K_CONFORMITE | 4,9 |
| `D1::C03 ↔ D2::C04` | K_PORTER, K_EPI | 3,1 |
| `D1::C01 ↔ D2::C01` | K_SITE_RADES, K_SECURITE | 3,3 |

**8 paires.** Noter que `D1::C05 ↔ D2::C05` (V7) **n'apparaît pas** : 0 concept partagé après l'échec des alias.

### Canal 4 — Vectoriel (bge-m3, seuil 0,70)

| Paire | cos | | Paire | cos |
|---|---|---|---|---|
| `D1::C03 ↔ D2::C03` | 0,91 | | `D1::C08 ↔ D2::C08` | 0,81 |
| `D1::C02 ↔ D2::C02` | 0,88 | | `D1::C07 ↔ D2::C07` | 0,79 |
| `D1::C06 ↔ D2::C06` | 0,87 | | `D1::C03 ↔ D2::C04` | 0,76 |
| `D1::C02 ↔ D2::C09` | 0,84 | | `D1::C06 ↔ D2::C07` | 0,72 |
| `D1::C01 ↔ D2::C01` | 0,83 | | `D1::C04 ↔ D2::C03` | 0,70 |

**10 paires.** Et le cas critique :

```
D1::C05 ↔ D2::C05  →  cos = 0,67   < seuil 0,70   ✗ ÉCARTÉE
   « Toute anomalie détectée est signalée au chef d'atelier sous 24 heures. »
   « Les écarts constatés sont remontés à la hiérarchie dans la semaine. »
```

⚠️ **V7 est définitivement perdue ici.** Écartée par les quatre canaux, elle ne pourra plus jamais être rattrapée : c'est la démonstration concrète du risque R4 de l'architecture (« le rappel du ciblage plafonne le rappel du système »).

### Fusion RRF et filtres

```
81 paires théoriques
   │
   ├─ union des 4 canaux ─────────────────────────────► 11 paires uniques
   │
   ├─ FILTRE DE COMPARABILITÉ ────────────────────────► 9 paires
   │     ✗ D1::C01 ↔ D2::C01   DEFINITION vs DEFINITION, aucune modalité
   │                            prescriptive, aucune grandeur → REJETÉE  ✅ N3
   │     ✗ D1::C04 ↔ D2::C03   PERMISSION vs RECOMMANDATION, objets non
   │                            alias, aucune grandeur → REJETÉE
   │
   ├─ top-k = 8 par clause ───────────────────────────► non contraignant
   └─ budget global 4 × 9 = 36 ───────────────────────► non contraignant
```

### Les 9 paires candidates, triées par score RRF

| # | Paire | Canaux | RRF | Vérité |
|---|---|---|---|---|
| P1 | `D1::C02 ↔ D2::C02` | CLE · CONCEPT · VECT | 0,141 | **V1** |
| P2 | `D1::C06 ↔ D2::C06` | CLE · CONCEPT · VECT | 0,138 | **V3** |
| P3 | `D1::C07 ↔ D2::C07` | CLE · CONCEPT · VECT | 0,131 | **V4** |
| P4 | `D1::C02 ↔ D2::C09` | CLE · CONCEPT · VECT | 0,129 | *piège N1* |
| P5 | `D1::C03 ↔ D2::C03` | CONCEPT · VECT | 0,092 | **V2** |
| P6 | `D1::C08 ↔ D2::C08` | CONCEPT · VECT | 0,071 | **V5** |
| P7 | `D1::C03 ↔ D2::C04` | CONCEPT · VECT | 0,048 | *piège N2* |
| P8 | `D1::C06 ↔ D2::C07` | VECT | 0,016 | bruit |
| P9 | `D1::C04 ↔ D2::C09` | VECT | 0,014 | bruit |

### Bilan du ciblage

| Indicateur | Valeur |
|---|---|
| Paires théoriques | 81 |
| Paires candidates | **9** |
| Facteur de réduction | **9,0 ×** (−88,9 %) |
| **Rappel du ciblage** | **5 / 6 = 0,83** *(V6 détectée hors paires ; V7 perdue)* |
| Coût | 4 requêtes Cypher, ~40 ms |

> **Lecture honnête.** Un facteur 9 sur des documents de 9 clauses est modeste : la réduction croît avec la taille (l'espace théorique est quadratique, le nombre de candidats linéaire). Sur 300 clauses par document, le même réglage donne un facteur ≈ 80. En revanche le **rappel de 0,83 est en dessous de la cible de 0,95**, et la démo dit exactement pourquoi — voir le correctif n° 1 en fin de document.

---

# ÉTAGE L4 — La cascade de vérification

Les 9 paires candidates traversent les trois étages. **Chaque paire s'arrête au premier étage qui tranche.**

---

## P1 · `D1::C02 ↔ D2::C02` — tranchée à l'étage A

```
ÉTAGE A ─ détecteur A2 (divergence de valeurs)

  dimension     TEMPS = TEMPS                      ✓ comparables
  rôle          delai = delai                      ✓
  clé           (RESP_QSE, VALIDER, FICHE_CTRL)    ✓ identique
  portées       conditions A = []   conditions B = []
                quantificateurs UNIVERSEL / UNIVERSEL
                → RECOUVREMENT TOTAL               ✓
  valeurs       172 800 s  ≠  432 000 s
                écart relatif = 60,0 %
  provenance    acteur=REGLE · quantites=REGLE     ✓ verdict ferme autorisé

  ⚡ VERDICT   INCOHERENCE / NUMERIQUE   score 0,95   gravité ÉLEVÉE
```

**Coût : 0,1 ms. Aucun modèle appelé.** La cascade s'arrête ici.

---

## P2 · `D1::C06 ↔ D2::C06` — tranchée à l'étage A

```
ÉTAGE A ─ A2

  dimension TEMPS_PERIODE = TEMPS_PERIODE          ✓
  clé       (*, CONTROLER, EPI, periodicite)       ✓ (via alias LEXIQUE + VECTEUR)
  portées   [] / []  → recouvrement total          ✓
  valeurs   7 884 000 s (trimestriel) ≠ 15 768 000 s (2×/an)   écart 50,0 %
  provenance quantites=REGLE, alias score min = 0,91 ≥ 0,86    ✓ ferme autorisé

  ⚡ VERDICT   INCOHERENCE / NUMERIQUE   score 0,95   gravité ÉLEVÉE
```

---

## P3 · `D1::C07 ↔ D2::C07` — A → B → C (les trois étages)

```
ÉTAGE A ─ A2

  clé identique, portées vides, valeurs 3 ans ≠ 5 ans (écart 40,0 %)
  MAIS  provenance des alias :
        K_ARCHIVER ≡ K_CONSERVER            méthode = LLM, score 0,80
        K_CONTROLE ≡ K_ENREGISTREMENTS      méthode = LLM, score 0,78
  → règle : un alias produit par LLM n'autorise pas un verdict ferme
  → CANDIDAT à confirmer, pas de verdict            ⟶ escalade B

ÉTAGE B ─ NLI bidirectionnel (distilcamembert-base-nli)

  A→B  P(contradiction) = 0,79   P(neutre) = 0,18   P(implication) = 0,03
  B→A  P(contradiction) = 0,74
  max = 0,79  →  zone grise [0,15 ; 0,85]           ⟶ escalade C

ÉTAGE C ─ LLM juge, prompt conditionné par le sous-graphe

  ┌─────────────────────────────────────────────────────────────────────┐
  │ CLAUSE A [PR-QSE-04 · §3.2 Périodicité]                             │
  │ « Le contrôle des EPI est archivé pendant 3 ans. »                  │
  │   ↳ grandeur : durée de conservation = 3 ans                        │
  │   ↳ concepts : EPI, contrôle, archivage                             │
  │                                                                     │
  │ CLAUSE B [POL-SEC-01 · §3.2 Vérifications]                          │
  │ « Les enregistrements de vérification sont conservés 5 ans. »       │
  │   ↳ grandeur : durée de conservation = 5 ans                        │
  │                                                                     │
  │ PONTS UTILISÉS (hypothèses) :                                       │
  │   archiver ≡ conserver              (LLM, 0,80)                     │
  │   contrôle des EPI ≡ enregistrements de vérification (LLM, 0,78)    │
  │ SIGNAL AMONT : divergence numérique 3 ans / 5 ans, portées vides    │
  └─────────────────────────────────────────────────────────────────────┘

  Auto-cohérence : 3 échantillons à T=0,2 → INCOHERENCE ×3  (3/3)

  { "verdict": "INCOHERENCE", "type": "NUMERIQUE",
    "preuve_a": "archivé pendant 3 ans",
    "preuve_b": "conservés pendant 5 ans",
    "portees_recouvrantes": true,
    "explication": "Les deux documents fixent une durée de rétention
                    différente pour la même trace documentaire de contrôle
                    des EPI, sans condition distinctive.",
    "confiance": 0.88 }

  FILTRE CONTRAINT : « archivé pendant 3 ans » ⊂ texte A ?  ✓
                     « conservés pendant 5 ans » ⊂ texte B ? ✓
  → preuves validées, verdict accepté

  ⚡ VERDICT   INCOHERENCE / NUMERIQUE   score 0,88   gravité MOYENNE
              ⓘ dépend de 2 hypothèses d'alignement — signalé dans le rapport
```

**Coût : 4 appels LLM (1 refusé par auto-cohérence n'est pas survenu ici) + 2 inférences NLI.**

---

## P4 · `D1::C02 ↔ D2::C09` — LE PIÈGE

```
ÉTAGE A ─ A2

  clé identique       (RESP_QSE, VALIDER, FICHE_CTRL, TEMPS, delai)   ✓
  valeurs             172 800 s (48 h)  ≠  86 400 s (24 h)   écart 50 %
  ⚠️ un détecteur naïf conclurait ici à une incohérence

  TEST DE RECOUVREMENT DES PORTÉES
     conditions A = []                              → portée universelle
     conditions B = [« en cas d'incident grave », CIRCONSTANCIEL]
     → ni recouvrement total, ni disjonction : cas d'INCLUSION (B ⊂ A)
     → règle : inclusion ⇒ AUCUN verdict ferme      ⟶ escalade C directe
                (le NLI est inutile : la question n'est pas sémantique
                 mais logique)

ÉTAGE C ─ question fermée, pas ouverte

  « La clause B restreint-elle la portée de la clause A ?
    Si oui, la contrainte de B est-elle plus stricte ou plus permissive
    que celle de A ? »

  { "verdict": "COHERENT",
    "relation": "SPECIALISATION",
    "explication": "La clause B traite un sous-cas (incident grave) et impose
                    un délai plus court (24 h < 48 h). Une exigence plus
                    stricte sur un sous-ensemble ne contredit pas l'exigence
                    générale : elle la renforce.",
    "confiance": 0.91 }

  ✅ VERDICT   COHERENT — FAUX POSITIF ÉVITÉ
              enregistré comme (D1::C02)-[:SPECIALISE_PAR]->(D2::C09)
```

📌 **C'est la paire la plus instructive de la démo.** Un système fondé sur la seule comparaison de valeurs — y compris la vérification de cohérence interne d'un outil commercial du benchmark — aurait signalé cette paire. C'est le test de recouvrement des portées qui la sauve, et c'est ce test qui justifie à lui seul l'existence de l'étage C.

---

## P5 · `D1::C03 ↔ D2::C03` — A → B → C

```
ÉTAGE A ─ A1 (conflit déontique)

  acteur    * / *      action PORTER / PORTER      objet CASQUE / CASQUE  ✓
  condition ZONE_A / ZONE_A                                              ✓
  modalités OBLIGATION (force 3)  ×  RECOMMANDATION (force 2)
  → table §7.1 de l'architecture : case « — » (pas de conflit fort)
  → écart de force = 1  →  DIVERGENCE_PERSPECTIVE, score 0,72, non ferme
                                                     ⟶ escalade B

ÉTAGE B ─ NLI

  A→B  P(contradiction) = 0,41   ← zone grise : le NLI voit deux énoncés
  B→A  P(contradiction) = 0,37     compatibles au sens strict (recommander
                                    n'est pas nier une obligation)
                                                     ⟶ escalade C

ÉTAGE C

  { "verdict": "INCOHERENCE", "type": "PERSPECTIVE",
    "preuve_a": "Le port du casque est obligatoire en zone A",
    "preuve_b": "il est recommandé de porter un casque",
    "explication": "La procédure impose ce que la politique se contente de
                    recommander, pour la même zone. En audit, un intervenant
                    peut légitimement invoquer la politique pour ne pas
                    porter de casque : l'obligation devient inopposable.",
    "confiance": 0.85 }

  ⚡ VERDICT   INCOHERENCE / PERSPECTIVE   score 0,85   gravité ÉLEVÉE
              (relevée de MOYENNE à ÉLEVÉE : objet = EPI de sécurité)
```

---

## P6 · `D1::C08 ↔ D2::C08` — tranchée à l'étage A

```
ÉTAGE A ─ A5 (référentiels)

  D1 → ISO 45001 : 2018    registre : EN VIGUEUR
  D2 → OHSAS 18001         registre : RETIRÉE — remplacée par ISO 45001
                                      depuis mars 2021
  deux constats simultanés :
    (a) référentiel obsolète cité par D2
    (b) deux documents du même site déclarent des référentiels différents

  ⚡ VERDICT   INCOHERENCE / FACTUEL   score 0,98   gravité ÉLEVÉE
```

**Aucun modèle appelé.** Une table de 40 entrées suffit.

---

## P7 · `D1::C03 ↔ D2::C04` — rejetée à l'étage B ✅

```
ÉTAGE A   objets K_CASQUE / K_GANTS non alias (cos 0,66)  → aucun détecteur
ÉTAGE B   NLI : P(contradiction) = 0,06 · P(neutre) = 0,91
          ✅ REJETÉE — deux obligations distinctes, pas un conflit  (piège N2)
```

## P8 · `D1::C06 ↔ D2::C07` — rejetée à l'étage A

```
dimensions TEMPS_PERIODE ≠ TEMPS(durée)  → non comparables
NLI : P(contradiction) = 0,09  → ✅ REJETÉE
```

## P9 · `D1::C04 ↔ D2::C09` — rejetée à l'étage B

```
PERMISSION (refuser un EPI) vs OBLIGATION (valider une fiche) : objets sans
rapport. NLI : P(contradiction) = 0,04  → ✅ REJETÉE
```

---

## Bilan de la cascade

| Étage | Paires traitées | Paires tranchées | Coût unitaire | Coût total |
|---|---|---|---|---|
| **A** symbolique | 9 | 4 (3 incohérences + 1 rejet) | 0,1 ms | ~1 ms |
| **B** NLI | 5 | 3 rejets | 25 ms × 2 sens | ~250 ms |
| **C** LLM juge | 3 | 3 (2 incohérences + 1 « cohérent ») | 2–5 s | ~9 appels |

```
   9 candidates
      ├─ 4 tranchées sans aucun modèle          44 %
      ├─ 3 rejetées par le NLI seul             33 %
      └─ 2 escaladées au LLM + 1 piège          23 %   ← seul poste coûteux
```

---

# ÉTAGE L5 — Consolidation

### Déduplication et regroupement

Aucun regroupement nécessaire ici (une occurrence par constatation) — sur documents réels, les 3 divergences de délai apparaîtraient typiquement dans 8 à 12 paires et seraient fusionnées en une constatation unique.

### Calcul de criticité

```
criticite = w_type × w_gravite × w_confiance × w_portee

F1  Délai de validation        3,0 × 0,60 × 0,95 × 1,0 (universel)  = 1,71  ⛔ CRITIQUE
F2  Périodicité de contrôle    3,0 × 0,50 × 0,95 × 1,0              = 1,43  🔴 ÉLEVÉE
F3  Casque obligatoire/reco.   2,5 × 0,70 × 0,85 × 1,0              = 1,49  🔴 ÉLEVÉE
F4  Référentiel obsolète       2,5 × 0,80 × 0,98 × 1,0              = 1,96  ⛔ CRITIQUE
F5  Durée de conservation      3,0 × 0,40 × 0,88 × 1,0              = 1,06  🟠 MOYENNE
F6  Renvoi § 6.3 inexistant    2,0 × 1,00 × 1,00 × 0,5 (locale)     = 1,00  🟠 MOYENNE
```

### Écriture dans le graphe

```
(D1::C02)-[:INCOHERENT_AVEC {type:"NUMERIQUE", score:0.95, detecteur:"A2",
            gravite:"ELEVEE", statut:"A_VALIDER"}]->(D2::C02)
(D1::C06)-[:INCOHERENT_AVEC {…A2…}]->(D2::C06)
(D1::C07)-[:INCOHERENT_AVEC {…C-LLM, hypotheses:["archiver≡conserver",…]}]->(D2::C07)
(D1::C03)-[:INCOHERENT_AVEC {type:"PERSPECTIVE", …C-LLM…}]->(D2::C03)
(D1::C08)-[:INCOHERENT_AVEC {type:"FACTUEL", …A5…}]->(D2::C08)
(D1::C09)-[:REFERENCE_CASSEE {cible:"§ 6.3"}]->(:Anomalie)
(D1::C02)-[:SPECIALISE_PAR {source:"C-LLM", confiance:0.91}]->(D2::C09)
```

---

# ÉTAGE L6 — Le rapport final

```
═══════════════════════════════════════════════════════════════════════════
  RAPPORT DE COHÉRENCE INTER-DOCUMENTS                       10/08/2026
  PR-QSE-04 (v3, 2024)   ⇄   POL-SEC-01 (v2, 2025)
───────────────────────────────────────────────────────────────────────────
  6 constatations · 81 paires théoriques · 9 vérifiées · 9 appels LLM · 52 s
═══════════════════════════════════════════════════════════════════════════

⛔ F4 · CRITIQUE — Référentiel obsolète et divergent          [FACTUEL · A5]

   PR-QSE-04 §4.1  « …conforme à la norme ISO 45001:2018. »
   POL-SEC-01 §4.1 « Le site applique le référentiel OHSAS 18001. »

   Les deux documents déclarent des référentiels différents, et OHSAS 18001
   est retirée depuis mars 2021 (remplacée par ISO 45001).
   Détecté par : registre des normes · Certitude 0,98
   ▸ Non-conformité d'audit immédiate.

───────────────────────────────────────────────────────────────────────────
⛔ F1 · CRITIQUE — Délai de validation divergent             [NUMERIQUE · A2]

   PR-QSE-04 §2.1  « Le Responsable QSE valide chaque fiche de contrôle
                     sous 48 heures. »
   POL-SEC-01 §2.1 « Le Référent sécurité est chargé de valider les fiches
                     de contrôle dans un délai de 5 jours ouvrés. »

   48 h vs 5 jours ouvrés (≈ 7 j calendaires) — écart 60 %.
   Hypothèse d'alignement : Responsable QSE ≡ Référent sécurité (0,88) ⚙️
   Détecté par : comparaison de grandeurs · Certitude 0,95

───────────────────────────────────────────────────────────────────────────
🔴 F3 · ÉLEVÉE — Force d'exigence divergente               [PERSPECTIVE · C]

   PR-QSE-04 §2.2  « Le port du casque est obligatoire en zone A. »
   POL-SEC-01 §2.2 « En zone A, il est recommandé de porter un casque. »

   La procédure impose ce que la politique recommande. Un intervenant peut
   invoquer la politique pour ne pas porter de casque : l'obligation devient
   inopposable.
   Détecté par : écart de force déontique → LLM · Certitude 0,85

───────────────────────────────────────────────────────────────────────────
🔴 F2 · ÉLEVÉE — Périodicité de contrôle divergente          [NUMERIQUE · A2]

   PR-QSE-04 §3.1  « …renouvelé tous les trimestres. »   (3 mois)
   POL-SEC-01 §3.1 « …réalisée deux fois par an. »       (6 mois)

   Écart 50 %. Hypothèses : EPI ≡ équipements de protection (lexique) ·
   contrôle ≡ vérification (0,91) ⚙️
   Détecté par : comparaison de grandeurs · Certitude 0,95

───────────────────────────────────────────────────────────────────────────
🟠 F5 · MOYENNE — Durée de conservation divergente        [NUMERIQUE · C]

   PR-QSE-04 §3.2  « Il est archivé pendant 3 ans. »
   POL-SEC-01 §3.2 « …conservés pendant 5 ans. »

   ⚙️ Repose sur 2 hypothèses d'alignement de confiance moyenne :
      archiver ≡ conserver (LLM, 0,80)
      contrôle des EPI ≡ enregistrements de vérification (LLM, 0,78)
   ▸ À confirmer par un relecteur métier. Certitude 0,88

───────────────────────────────────────────────────────────────────────────
🟠 F6 · MOYENNE — Renvoi interne cassé                      [FACTUEL · A5]

   PR-QSE-04 §4.2  « Les modalités de retrait des EPI sont décrites
                     au § 6.3. »
   Le document ne comporte que les sections 1 à 4. Certitude 1,00

═══════════════════════════════════════════════════════════════════════════
  ✅ VÉRIFIÉ ET DÉCLARÉ COHÉRENT
     PR-QSE-04 §2.1 (48 h) ⇄ POL-SEC-01 §5.1 (24 h en cas d'incident grave)
     → spécialisation compatible, pas une contradiction (confiance 0,91)

  ⚙️ HYPOTHÈSES D'ALIGNEMENT UTILISÉES (révisables)          7 alias
     EXACT 4 · LEXIQUE 1 · VECTEUR 2 (0,88 / 0,91) · LLM 2 (0,80 / 0,78)

  ⚠️ ZONES NON COUVERTES
     PR-QSE-04 §2.4 et POL-SEC-01 §2.4 traitent toutes deux d'un délai de
     signalement mais n'ont pu être rapprochées (aucun terme commun).
     → clauses à relire manuellement
═══════════════════════════════════════════════════════════════════════════
```

---

# Bilan de la démonstration

### Performance

| | Attendu | Trouvé | |
|---|---|---|---|
| V1 délai de validation | ✓ | ✅ F1 | étage A |
| V2 casque obligatoire/recommandé | ✓ | ✅ F3 | étage C |
| V3 périodicité | ✓ | ✅ F2 | étage A |
| V4 durée de conservation | ✓ | ✅ F5 | étage C |
| V5 référentiel obsolète | ✓ | ✅ F4 | étage A |
| V6 renvoi cassé | ✓ | ✅ F6 | canal 1 |
| **V7 délai de signalement** | ✓ | ❌ **MANQUÉE** | perdue en L3 |
| N1 spécialisation 24 h | ✗ | ✅ correctement écartée | étage C |
| N2 casque/gants | ✗ | ✅ correctement écartée | étage B |
| N3 phrases de cadrage | ✗ | ✅ correctement écartée | filtre L3 |

```
Précision     6 / 6  = 1,00
Rappel        6 / 7  = 0,86
F1                   = 0,92
Faux positifs        = 0
Rappel du ciblage    = 0,83   ⚠️ sous la cible de 0,95
```

### Coût

| Poste | Volume | Temps (profil A, GPU 8 Go) |
|---|---|---|
| Segmentation + règles | 18 clauses | 1,2 s |
| Autonomisation LLM | 1 appel | 3,5 s |
| Extraction LLM | 2 appels | 8,1 s |
| Embeddings bge-m3 | 49 vecteurs | 2,0 s |
| Arbitrage d'alias LLM | 2 appels | 7,2 s |
| Graphe Neo4j | 62 nœuds, 138 arêtes | 0,9 s |
| Ciblage (4 Cypher) | 81 → 9 | 0,04 s |
| Cascade A | 9 paires | 0,001 s |
| Cascade B (NLI) | 10 inférences | 0,3 s |
| Cascade C | 9 appels | 28 s |
| Rapport | — | 0,2 s |
| **TOTAL** | **14 appels LLM** | **≈ 52 s** · **0 €** |

Pour comparaison : 81 paires × 1 appel LLM = **81 appels**, soit 5,8 × plus, pour un résultat strictement inférieur (aucune preuve structurée, aucune traçabilité, faux positif N1 quasi certain).

---

# Ce que la démonstration révèle — 3 correctifs à porter à l'architecture

C'est le vrai produit d'une simulation : elle fait apparaître ce qu'une conception sur papier ne voit pas.

### ⚠️ Correctif n° 1 — Ajouter un **canal 5 « dimension seule »** au ciblage

**Symptôme.** V7 est perdue par les quatre canaux : aucun terme commun, cos = 0,67 sous le seuil, et l'une des deux clauses n'a même pas de grandeur extraite.

**Cause.** Les quatre canaux reposent tous sur un **partage lexical ou conceptuel**. Deux clauses qui disent la même chose avec un vocabulaire entièrement disjoint sont invisibles.

**Correctif.** Un cinquième canal, indépendant du vocabulaire :

> Apparier toutes les clauses de documents différents qui portent une grandeur de **même dimension et même rôle** (ici : un délai), classées par similarité, top-3 par clause, sans seuil de similarité.

Coût : quelques dizaines de paires supplémentaires par document. Rappel de ciblage sur la démo : **0,83 → 1,00**.

**Sous-correctif.** Étendre le patron `DELAI` aux expressions vagues (`dans la semaine`, `sous quinzaine`, `dans les meilleurs délais` → intervalle avec drapeau `IMPRECIS`). Sans cela, `D2::C05` n'a toujours aucune grandeur et le canal 5 ne la voit pas.

### ⚠️ Correctif n° 2 — Formaliser l'**inclusion de portée** dans le test de recouvrement

**Symptôme.** La paire N1 (48 h vs 24 h en cas d'incident grave) n'est ni un recouvrement total ni une disjonction. La règle initiale (« l'une des conditions est vide → recouvrement décidé par règle ») aurait conclu au recouvrement, donc au conflit : **un faux positif**.

**Correctif — règle explicite à trois cas :**

| Portées | Contrainte de la clause restreinte | Verdict |
|---|---|---|
| identiques | valeur différente | **contradiction** |
| disjointes | quelconque | **aucun conflit** |
| **inclusion** (B ⊂ A) | plus **stricte** que A | **spécialisation** ✅ |
| **inclusion** (B ⊂ A) | plus **permissive** que A | **contradiction** ⛔ |

La comparaison « plus stricte / plus permissive » dépend du rôle de la grandeur : pour un `delai`, plus petit = plus strict ; pour une `duree_conservation`, plus grand = plus strict ; pour un `seuil`, cela dépend du sens de l'inégalité. **Cette table de monotonie par rôle doit être ajoutée au registre des grandeurs.**

### ⚠️ Correctif n° 3 — Compléter la table déontique avec l'**écart de force**

**Symptôme.** La case OBLIGATION × RECOMMANDATION était marquée « — » (pas de conflit). Or V2 est une incohérence réelle, et sérieuse en audit.

**Correctif.** Remplacer les cases vides de la table par un **écart de force** :

```
ecart = |force(A) − force(B)|   sur l'échelle  interdiction 4 · obligation 3
                                              recommandation 2 · permission 1

ecart = 0  →  aucun conflit
ecart = 1  →  DIVERGENCE_PERSPECTIVE, non ferme, escalade obligatoire
ecart ≥ 2  →  CONFLIT FORT (obligation vs permission, interdiction vs reco.)
```

---

# Scénario bonus — Le mode incrémental

**Action de l'utilisateur :** correction de PR-QSE-04 §3.1 pour l'aligner sur la politique.

```
AVANT  « Le contrôle des EPI doit être renouvelé tous les trimestres. »
APRÈS  « Le contrôle des EPI doit être renouvelé deux fois par an. »
```

### Ce qui se passe

```
1. RÉ-INGESTION           18 clauses, comparaison des hash
                          → 1 seule clause modifiée : D1::C06
                          → 17 frames rechargées du cache, 0 appel LLM

2. RÉEXTRACTION           D1::C06 : règles seules suffisent
                          (grandeur + modalité + acteur)   → 0 appel LLM

3. RAYON D'IMPACT (Cypher)
   MATCH (c:Clause {clause_id:"D1::C06"}) …
   ┌──────────────────────────────────────────────────────────┐
   │ priorité 0 · liens déjà connus                           │
   │   D2::C06   (INCOHERENT_AVEC)                            │
   │   D2::C07   (PAIRE_CANDIDATE)                            │
   │ priorité 1 · voisinage conceptuel (K_EPI, K_CONTROLER)   │
   │   D1::C07 · D2::C06 · D2::C07                            │
   └──────────────────────────────────────────────────────────┘
   → 3 clauses impactées, 3 paires à revérifier
     (au lieu de 81 paires théoriques / 9 candidates)

4. CASCADE
   D1::C06 ↔ D2::C06   A2 : 15 768 000 s = 15 768 000 s
                       → ⚡ INCOHÉRENCE F2 RÉSOLUE
                       → statut de l'arête : RESOLUE, horodatée
   D1::C06 ↔ D2::C07   dimensions différentes → rejetée (inchangé)
   D1::C06 ↔ D1::C07   intra-document → hors périmètre

5. RAPPORT MIS À JOUR    5 constatations (F2 disparaît, marquée « résolue
                         le 10/08/2026 »)
```

| | Première exécution | Ré-exécution |
|---|---|---|
| Paires vérifiées | 9 | **3** |
| Appels LLM | 14 | **0** |
| Inférences NLI | 10 | 0 |
| Durée | 52 s | **1,8 s** |

> **C'est ici que se voit la différence entre une architecture et un script d'analyse.** Le graphe ne se contente pas de trouver les incohérences une fois : il sait **quelles zones du corpus une modification met en danger**, et ne recalcule que celles-là. C'est la réponse directe à la problématique du sujet — « identifier les zones impactées par une modification locale » — et c'est aussi ce qui rend l'outil utilisable au quotidien plutôt qu'une fois par audit.

---

## En une phrase

Sur 81 paires possibles, le système en a examiné 9, appelé un LLM sur 3, trouvé 6 incohérences sur 7 sans aucun faux positif, écarté trois pièges, et sait exactement pourquoi il a manqué la septième.
