# COHERA — Architecture de détection d'incohérences inter-documents par graphe de dépendances

**Version 2.0 — révision du modèle de graphe pour le domaine QHSE**
*Dossier d'architecture candidate — Stage « Étude d'architecture pour l'analyse de cohérence documentaire par graphe de dépendances »*

| | |
|---|---|
| **Entrée** | N fichiers `.txt`, français, domaine QHSE |
| **Sortie** | Constatations d'incohérence **inter-documents** typées, localisées, justifiées, scorées + graphe navigable |
| **Base de graphe** | Neo4j (2025.x / 2026.x, Community) |
| **LLM** | Mistral 7B Instruct Q4_K_M via LM Studio (local) **ou** API gratuite (Gemini 2.5 Flash / Groq / OpenRouter) |
| **Contrainte cardinale** | Ne jamais comparer toutes les paires de clauses ; ne jamais appeler un LLM sur une paire non ciblée |

> **Ce qui change en v2.** Le modèle de graphe v1 traitait un document QHSE comme un texte structuré. Il ignorait que ces documents forment un **système documentaire** : une pyramide hiérarchique, des versions qui s'abrogent, des dérogations déclarées, des périmètres d'application, des conditions d'applicabilité et des exigences réglementaires opposables. Six ajouts corrigent cela (§5, §17). Trois correctifs issus de la démonstration de bout en bout sont également intégrés (§6.5, §7.1, §7.2).

---

## 0. La thèse d'architecture

### 0.1 Le problème formel

Deux documents `D₁` et `D₂` contiennent `n₁` et `n₂` clauses. L'espace des incohérences possibles est `n₁ × n₂` : pour deux procédures de 10 pages, **~90 000 paires**. Le problème n'est pas seulement un problème de coût, c'est un problème de **rapport signal/bruit** : sur 90 000 paires dont ~10 sont réellement conflictuelles, un détecteur à 95 % de précision produit ~4 500 faux positifs — un rapport que personne ne lira.

### 0.2 La réponse

> **Le graphe n'est pas un moyen de stocker les documents. C'est le mécanisme qui décide quelles paires méritent d'être vérifiées, par quel détecteur, et lesquelles sont déjà résolues par le corpus lui-même.**

Quatre invariants tenus de bout en bout :

| # | Invariant | Conséquence concrète |
|---|---|---|
| **I1** | **Rien de cher n'est exécuté avant d'avoir été ciblé.** | Aucun appel NLI ou LLM sur une paire non issue du graphe. Le ciblage est une requête Cypher, pas un calcul. |
| **I2** | **Le détecteur le moins cher qui couvre un type d'incohérence est celui qui le traite.** | Une divergence de valeur est une comparaison d'entiers, pas un appel LLM. |
| **I3** | **Aucun verdict sans preuve matérialisée.** | Deux extraits exacts, le détecteur, et le chemin de graphe qui a fait émerger la paire. Un LLM qui affirme sans citer est rejeté automatiquement. |
| **I4** ⭐ | **Le corpus se déclare lui-même : il faut le lire avant de conclure.** | Une dérogation explicite, une abrogation, une version périmée ou une hiérarchie documentaire **résolvent** un conflit apparent. Le système lit ces déclarations avant de signaler quoi que ce soit. |

L'invariant I4 est la leçon centrale de la v2. Un système qui l'ignore signale comme incohérences : les versions obsolètes contre les versions courantes, les dérogations dûment approuvées, les instructions plus strictes que la procédure qu'elles déclinent. Ces trois familles représentent, sur un système documentaire réel, **la majorité des conflits apparents**.

### 0.3 Vue générale

```
   D1.txt  D2.txt  D3.txt … Dn.txt
      │       │       │       │
      ▼       ▼       ▼       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ L0  SEGMENTATION             → unités normatives auto-portantes          │
│ L1  EXTRACTION HYBRIDE       → Clause Frames (règles d'abord, LLM après) │
│ L2  CONSTRUCTION DU GRAPHE   → Neo4j : structure + système documentaire  │
│     ├ pont inter-documents (alias de concepts)                           │
│     ├ algèbre des conditions (recouvrement / inclusion / disjonction)    │
│     └ cycle de vie : abrogation · dérogation · déclinaison · validité    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼   ~90 000 paires théoriques
┌──────────────────────────────────────────────────────────────────────────┐
│ L3  CIBLAGE — 3 filtres d'éligibilité, 5 canaux, fusion RRF, budget      │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼   ~800–1 200 paires candidates
┌──────────────────────────────────────────────────────────────────────────┐
│ L4  CASCADE DE VÉRIFICATION                                              │
│     ├ A. 9 détecteurs symboliques  coût ≈ 0     → ~40 % des paires       │
│     ├ B. NLI (CamemBERT-NLI)       ~25 ms/paire → ~50 % des paires       │
│     └ C. LLM juge (contexte de graphe) → ~5–10 % des paires seulement    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ L5  CONSOLIDATION · arbitrage hiérarchique · propagation d'impact        │
│ L6  RESTITUTION (rapport + graphe explorable)                            │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Positionnement vis-à-vis de l'état de l'art

L'architecture prend à chacune des 8 approches benchmarkées la partie au meilleur rapport valeur/coût, et laisse le reste.

| # | Approche benchmarkée | Ce que COHERA en retient | Ce qu'elle écarte, et pourquoi |
|---|---|---|---|
| 1 | **SMT (Z3 / SBVR)** | La **table de conflits déontiques**, implémentée comme une table de vérité, pas un solveur. | La chaîne CNL→SMT-LIB : **65 % des traductions CNL restent manuelles**. Coût prohibitif en 8 semaines. |
| 2 | **Classification supervisée** | Rien directement. | Exige un corpus annoté QHSE de milliers de paires, inexistant. Surapprentissage garanti sur du synthétique. |
| 3 | **NLI pré-entraîné** | **Étage B de la cascade**, tel quel : maturité élevée, coût faible, aucun entraînement. | Son usage en balayage exhaustif : le NLI n'est bon *que* sur des paires déjà ciblées. |
| 4 | **Similarité par embeddings** | **Canaux 4 et 5 du ciblage** + le pont terminologique inter-documents. | Son usage comme détecteur : une similarité élevée n'est pas une incohérence. Générateur de candidats, jamais juge. |
| 5 | **Ontologies RDF/OWL** | Le **modèle déontique** (Bearer / Action / Object / Condition) et la comparaison de portées, réimplémentés en nœuds et propriétés Neo4j. | OWL, Pellet/HermiT : coût de mise en œuvre « très élevé », et aveugle hors du périmètre modélisé. |
| 6 | **GraphCheck (GNN + LLM gelé)** | L'idée maîtresse : **le graphe comme représentation compressée injectée au LLM** — ici par prompting conditionné par le sous-graphe. | L'entraînement du GNN (14 k exemples, 4×A100). Ni données, ni matériel, ni temps. |
| 7 | **RnR+CF (Redact-and-Retry)** | Le **filtre contraint** : le LLM doit toujours produire une preuve textuelle vérifiable, jamais un verdict nu. Appliqué à la paire, pas au document. | Les 4–5 appels sur le document entier : aucun ciblage, incompatible avec un modèle local. |
| 8 | **Icertis (commercial)** | Le **registre canonique des grandeurs** : comparer les valeurs extraites entre elles détecte les divergences avec ~0 faux positif. | Le playbook rédigé à la main et le périmètre juridique. Notre registre est construit automatiquement. |

**Synthèse.** Les approches 1/2/5 concentrent leur coût en amont (formalisation, annotation, ontologie) ; les approches 6/7 à l'exécution (appels LLM). COHERA occupe la zone vide : **coût faible des deux côtés**, en remplaçant la formalisation lourde par de l'extraction hybride, et le balayage LLM par du ciblage de graphe.

---

## 2. Taxonomie opérationnalisée — du type d'incohérence au détecteur

| Type (taxonomie) | Traduction QHSE | Exemple inter-documents FR | Détecteur | Étage | Priorité |
|---|---|---|---|---|---|
| **Negation** | Obligation vs interdiction sur la même action | « Le port du casque est obligatoire en zone A. » / « …n'est pas requis en zone A. » | **A1** table déontique | A | ★★★ |
| **Numeric** | Divergence de valeurs, seuils, délais, périodicités | « contrôle **trimestriel** » / « contrôle **semestriel** » ; « **5 jours ouvrés** » / « **48 heures** » | **A2** comparaison de `Quantite` | A | ★★★ |
| **Content** | Un attribut de l'exigence diverge (acteur, lieu, objet) | « validation par le **Responsable QSE** » / « par le **chef d'atelier** » | **A3** puis NLI | A→B | ★★★ |
| **Relation** | Responsabilités mutuellement exclusives (RACI) | Deux documents attribuent le « R » de la même tâche à deux rôles différents | **A4** contrainte RACI | A | ★★ |
| **Factual** | Référence cassée, référentiel obsolète ou divergent | « ISO 45001:2018 » / « OHSAS 18001 » (retirée) ; renvoi vers un « §5.4 » inexistant | **A5** résolution + registre | A | ★★ |
| **Causal** | La condition de déclenchement ne correspond pas à l'effet | « arrêt immédiat en cas d'incident » / « arrêt après validation » | NLI puis LLM | B→C | ★★ |
| **Perspective** | Divergence de **force** prescriptive | « il est **recommandé** de porter des gants » / « le port de gants est **imposé** » | **A1** écart de force | A→B | ★★ |
| **Emotion / Mood** | Quasi absent des documents normatifs | — | non implémenté | — | ✗ |
| ⭐ **Temporel** | Deux clauses en vigueur simultanément et contradictoires, ou clause périmée encore citée | « applicable à compter du 01/01/2025 » vs clause abrogée le 31/12/2024 | **A7** validité | A | ★★ |
| ⭐ **Dérogation** | Dérogation non déclarée, ou déclarée vers une cible inexistante/abrogée | « par dérogation à PR-QSE-03 » alors que PR-QSE-03 est abrogée | **A8** | A | ★★ |
| ⭐ **Hiérarchique** | Un document de niveau inférieur est **plus permissif** que celui dont il dérive, ou qu'une exigence réglementaire | Instruction : « contrôle annuel » / Procédure mère : « contrôle trimestriel » | **A9** | A | ★★★ |

### 2.1 Trois lectures

1. **Huit des onze types se règlent sans aucun LLM.** C'est le rendement de l'investissement fait en extraction (L1) et en modélisation (L2).
2. **Le LLM n'intervient que sur Causal, les portées indécidables et les cas ambigus** — ~5–10 % des paires candidates. C'est ce qui rend un budget gratuit tenable.
3. **Les trois types ajoutés en v2 (Temporel, Dérogation, Hiérarchique) sont spécifiquement QHSE.** Ils n'apparaissent dans aucune taxonomie générique de contradictions textuelles, parce qu'ils ne relèvent pas du texte mais du **système documentaire**. Ce sont pourtant les constats les plus fréquents en audit réel.

### 2.2 La taxonomie comme générateur de corpus

Chaque type est défini par une transformation d'une phrase source : on en dérive un injecteur automatique produisant le mini-corpus annoté (livrable 1).

| Transformation | Implémentation |
|---|---|
| Negation | inversion du marqueur déontique (`doit` ↔ `ne doit pas`) |
| Numeric | perturbation de la valeur ou changement d'unité sans conversion |
| Content | substitution de l'acteur ou de l'objet par une autre entité du graphe |
| Relation | permutation de deux responsabilités RACI exclusives |
| Factual | remplacement d'une référence par une version obsolète ou un renvoi inexistant |
| Causal | inversion de l'ordre condition/effet |
| ⭐ Temporel | décalage des dates de validité pour créer un chevauchement contradictoire |
| ⭐ Hiérarchique | assouplissement d'une exigence dans un document de niveau inférieur |

> ⚠️ **Garde-fou méthodologique.** Le benchmark note que **87 % des cas de conflits de la littérature sont (semi-)synthétiques**. Un système évalué uniquement sur des injections surestime ses performances. Le protocole (§12) impose un **jeu de test disjoint d'incohérences réelles**, jamais utilisé pour le réglage des seuils.

---

## 3. L0 — Ingestion et segmentation en unités normatives

**Objectif.** Transformer un `.txt` sans structure garantie en unités normatives auto-portantes.

### 3.1 Granularité

> **Un nœud `Clause` = un énoncé normatif atomique** : une prescription, un seuil, une responsabilité ou une définition, exprimée par une phrase ou un item de liste.

| Granularité | Problème |
|---|---|
| Le **paragraphe** | Contient souvent 2–4 exigences : comparaison de valeurs ambiguë, localisation trop grossière pour un audit. |
| Le **triplet** (S,P,O) | Perd la modalité déontique et les conditions — précisément ce qui crée les conflits QHSE. |
| **L'énoncé normatif** ✅ | Aligné sur l'unité de raisonnement du NLI, l'unité de comparaison des valeurs, et l'unité de citation en audit. |

### 3.2 Chaîne de segmentation

```
texte brut
   │
   ├─ 1. NORMALISATION      Unicode NFC, espaces insécables, guillemets, tirets,
   │                        séparateur décimal (« 0,5 » → 0.5)
   │
   ├─ 2. DÉTECTION DE STRUCTURE (heuristiques en cascade)
   │      a) numérotation      ^\s*(\d+(\.\d+)*)[\).\-\s]+(\S.*)$
   │      b) titre non ponctué ligne courte (<80 c.), sans point final
   │      c) capitales         ligne entièrement en majuscules
   │      d) puces             ^\s*([-•*–]|[a-z]\)|\d+\))\s+
   │      → arbre de sections (repli : document plat)
   │
   ├─ 3. RECOMPOSITION DES LISTES  ← étape critique
   │      Le chapeau (« Le responsable QSE doit : ») est redistribué sur chaque
   │      item, sinon les items n'ont ni sujet ni modalité.
   │
   ├─ 4. DÉTECTION DES BLOCS TABULAIRES ⭐
   │      Un bloc de lignes alignées par tabulations, points de suite ou séries
   │      de « | » est traité en mode tableau : la ligne d'en-tête donne les
   │      rôles, chaque ligne devient une Clause avec origine = TABLEAU.
   │      Les matrices de responsabilité (RACI) et les tableaux de périodicité
   │      QHSE y passent presque tous.
   │
   ├─ 5. SEGMENTATION EN PHRASES   spaCy fr_core_news_lg, avec exceptions :
   │      abréviations (art., §, cf., ex., n°), décimales, « ISO 45001:2018 »
   │
   ├─ 6. QUALIFICATION      une phrase devient Clause si elle contient un
   │      marqueur déontique, une grandeur, une référence ou un verbe
   │      définitionnel. Sinon → rattachée en `contexte` à la clause précédente.
   │
   └─ 7. AUTONOMISATION     décontextualisation des anaphores
          « Il doit être renouvelé tous les ans. »
          → « Le contrôle des EPI doit être renouvelé tous les ans. »
```

### 3.3 L'autonomisation et son contrôle de coût

Le NLI et le LLM voient une paire **hors de son document**. Une clause commençant par « Il », « Ce dernier », « Cette vérification » est inexploitable. **On ne réécrit que ce qui en a besoin** : détecteur d'anaphore par regex + absence de sujet dans l'arbre de dépendances. En pratique **15–25 % des clauses**, traitées par lots de 8.

```python
ANAPHORE = re.compile(
    r"^\s*(il|elle|ils|elles|celui-ci|celle-ci|ce dernier|cette dernière|"
    r"ceux-ci|celles-ci|ce|cet|cette|ces)\b", re.I)

def besoin_autonomisation(clause, doc_nlp):
    if ANAPHORE.match(clause.texte):
        return True
    return not any(t.dep_ in ("nsubj", "nsubj:pass") for t in doc_nlp)
```

Le `texte_source` est **toujours conservé** avec ses offsets : c'est lui qui sera cité en preuve. Le texte autonome ne sert qu'au traitement.

### 3.4 Sortie de L0

```json
{
  "clause_id": "D1::S5.2::C03",
  "doc_id": "D1",
  "section_path": ["5. Contrôles", "5.2 Périodicité"],
  "texte_source": "Il doit être renouvelé tous les trimestres.",
  "texte_autonome": "Le contrôle des EPI doit être renouvelé tous les trimestres.",
  "offset": [4821, 4864],
  "origine": "TEXTE",
  "hash": "a3f1c9…"
}
```

Le `hash` (SHA-256 du texte source) est la clé du **mode incrémental** : seules les clauses dont le hash a changé sont réextraites (§9.4).

---

## 4. L1 — Extraction hybride : du texte à la *Clause Frame*

C'est l'étage qui conditionne tout le reste. **Une frame bien extraite rend la détection quasi gratuite ; une frame bruitée rend le LLM indispensable partout.**

### 4.1 Schéma de la Clause Frame (v2)

```json
{
  "clause_id": "D1::S5.2::C03",
  "type_enonce": "PRESCRIPTION",     // PRESCRIPTION | DEFINITION | CONSTAT | RENVOI | DEROGATION
  "modalite": "OBLIGATION",          // OBLIGATION | INTERDICTION | PERMISSION | RECOMMANDATION | CONSTAT | DEFINITION
  "force": 3,                        // 4 interdiction · 3 obligation · 2 recommandation · 1 permission
  "negation": false,

  "acteur":  {"surface": "le responsable QSE", "concept_id": null, "raci": "R"},
  "action":  {"surface": "renouveler", "lemme": "renouveler"},
  "objet":   {"surface": "le contrôle des EPI", "concept_id": null},

  "quantites": [
    {"role": "periodicite", "valeur": 3, "unite": "mois", "dimension": "TEMPS_PERIODE",
     "valeur_si": 7884000, "surface": "tous les trimestres", "operateur": "="}
  ],

  "conditions": [                                        // ⭐ v2 : structurées
    {"surface": "en zone A", "type": "SPATIAL",
     "concept_cible": "zone A", "operateur": "APPARTIENT"}
  ],
  "perimetre": {"surface": "site de Radès", "type": "SITE"},   // ⭐ v2
  "portee":    {"quantificateur": "UNIVERSEL", "surface": "tout intervenant"},

  "validite": {"debut": "2024-01-01", "fin": null},            // ⭐ v2

  "references": [
    {"type": "INTERNE", "cible": "§5.4"},
    {"type": "NORME",   "cible": "ISO 45001", "version": "2018"},
    {"type": "EXIGENCE","cible": "art. R.4321-1", "source": "Code du travail"}
  ],
  "derogation": null,                                          // ⭐ v2
  "risques_maitrises": ["chute de hauteur"],                   // ⭐ v2

  "confiance_extraction": 0.86,
  "source_extraction": {"modalite":"REGLE","quantites":"REGLE","acteur":"REGLE",
                        "action":"LLM","objet":"LLM","conditions":"REGLE"}
}
```

`source_extraction` trace, **champ par champ**, si la valeur vient d'une règle ou du LLM. Un détecteur symbolique ne rend un **verdict ferme** que si tous les champs qu'il compare viennent de règles. Sinon il produit un candidat à confirmer. C'est la parade contre les hallucinations d'un 7B quantifié.

### 4.2 Étage déterministe (règles) — toujours en premier

| Champ | Méthode | Détail |
|---|---|---|
| `modalite` / `force` | lexique déontique FR + patrons syntaxiques | `doit`, `est tenu de`, `est obligatoire` → OBLIGATION · `ne doit pas`, `est interdit`, `en aucun cas` → INTERDICTION · `peut`, `est autorisé à` → PERMISSION · `il est recommandé`, `il convient de`, `devrait` → RECOMMANDATION · présent de l'indicatif + sujet = rôle du gazetteer → OBLIGATION (confiance 0,78) |
| `negation` | portée de négation via l'arbre de dépendances | distingue « ne doit pas valider » (interdiction) de « doit ne pas valider » |
| `quantites` | grammaire de règles + normalisation dimensionnelle | durées, périodicités, seuils physiques, effectifs, distances, températures, durées de validité d'habilitation |
| `conditions` ⭐ | marqueurs + typage | `en cas de`, `lorsque`, `si`, `sauf`, `hors`, `à l'exception de`, `en zone …`, `lors de`, `au-delà de`, `pour les …` |
| `perimetre` ⭐ | marqueurs d'applicabilité | `s'applique à`, `concerne`, `sur le site de`, `pour l'atelier`, `pour toute activité de` |
| `validite` ⭐ | dates + marqueurs | `à compter du`, `applicable au`, `jusqu'au`, `abrogé le`, `en vigueur depuis` |
| `derogation` ⭐ | marqueurs explicites | `par dérogation à`, `nonobstant`, `sauf disposition contraire de`, `en dérogation de` |
| `references` | regex | internes `§5.2`, `article 4.3`, `annexe B` · externes `PR-QSE-04`, `ISO 45001:2018`, `NF EN 397`, `décret n° 2001-1016`, `art. R.4321-1` |
| `acteur` + `raci` ⭐ | gazetteer QHSE (~120 rôles) + NER `camembert-ner` + marqueurs RACI | `est chargé de`, `réalise`, `exécute` → **R** · `valide`, `approuve`, `signe` → **A** · `est consulté`, `donne son avis` → **C** · `est informé`, `reçoit copie` → **I** |
| `risques_maitrises` ⭐ | lexique des dangers QHSE | chute de hauteur, ATEX, bruit, produit chimique, risque électrique, TMS, incendie… |
| `portee` | quantificateurs | `tout`, `chaque`, `tous les` → UNIVERSEL · `un`, `certains`, `le cas échéant` → EXISTENTIEL |

**Normalisation dimensionnelle** — elle rend la comparaison numérique fiable :

```
"5 jours ouvrés"   → (TEMPS, 432 000 s, {calendrier: "ouvre"})   [+ 604 800 s calendaire]
"10 jours"         → (TEMPS, 864 000 s, {calendrier: "calendaire"})
"trimestriel"      → (TEMPS_PERIODE, 7 884 000 s)     ┐ égalité
"tous les 3 mois"  → (TEMPS_PERIODE, 7 884 000 s)     ┘ détectée
"deux fois par an" → (TEMPS_PERIODE, 15 768 000 s)
"85 dB(A)"         → (PRESSION_ACOUSTIQUE, 85, {pondération: "A"})
"au-delà de 2 m"   → (LONGUEUR, 2, {}, opérateur: ">")
```

Deux quantités ne sont comparables que si leur **dimension** et leur **rôle** sont identiques.

### 4.3 Registre des grandeurs — dimension, rôle et **monotonie** ⭐

Le registre est une table de configuration, pas du code. La colonne *monotonie* est nouvelle en v2 : elle indique dans quel sens une valeur est **plus stricte**, ce qui permet de distinguer une spécialisation légitime d'une contradiction (§7.2).

| rôle | dimension | plus strict = | exemple QHSE |
|---|---|---|---|
| `delai` | TEMPS | valeur **plus petite** | validation sous 48 h |
| `periodicite` | TEMPS_PERIODE | valeur **plus petite** | contrôle trimestriel |
| `duree_conservation` | TEMPS | valeur **plus grande** | archivage 5 ans |
| `duree_formation` | TEMPS | valeur **plus grande** | formation 14 h |
| `validite_habilitation` | TEMPS | valeur **plus petite** | recyclage tous les 3 ans |
| `seuil_exposition` (max) | selon grandeur | valeur **plus petite** | 85 dB(A) |
| `seuil_declenchement` (min requis) | selon grandeur | valeur **plus grande** | port du harnais au-delà de 2 m |
| `distance_securite` | LONGUEUR | valeur **plus grande** | 10 m d'une zone ATEX |
| `effectif_minimum` | EFFECTIF | valeur **plus grande** | 2 SST par équipe |
| `tolerance` | SANS_UNITE | valeur **plus petite** | ±5 % |

### 4.4 Étage LLM (Mistral 7B local) — en complément, jamais en remplacement

Le LLM ne comble que les champs laissés `null` : `objet`, `action`, conditions complexes, acteurs hors gazetteer. Cinq garde-fous rendent un 7B Q4 exploitable :

1. **Sortie structurée imposée** — LM Studio accepte `response_format: {"type":"json_schema"}` : le décodage contraint rend le JSON invalide impossible.
2. **Traitement par lot** — 6 à 8 clauses par appel : ÷ 7 sur le nombre d'appels.
3. **Champs pré-remplis fournis et non modifiables** — le modèle voit ce que les règles ont trouvé et ne peut pas l'écraser.
4. **Vocabulaire fermé** — `modalite`, `dimension`, `type de condition`, `raci` sont des énumérations ; toute valeur hors énumération invalide la frame.
5. **Boucle de réparation bornée à 1 essai** — sinon `confiance_extraction = 0.3`, clause marquée `EXTRACTION_INCERTAINE`, exclue des verdicts fermes mais toujours traitée par NLI/LLM.

**Prompt système (extrait)**

```
Tu es un extracteur d'exigences normatives en français. Tu ne raisonnes pas,
tu extrais. Tu ne complètes JAMAIS un champ déjà rempli. Tu ne devines pas :
si l'information n'est pas explicitement dans la phrase, tu renvoies null.
Tu réponds uniquement par un tableau JSON conforme au schéma.

Énumérations autorisées :
  modalite  : OBLIGATION | INTERDICTION | PERMISSION | RECOMMANDATION | CONSTAT | DEFINITION
  dimension : TEMPS | TEMPS_PERIODE | LONGUEUR | MASSE | TEMPERATURE
            | PRESSION_ACOUSTIQUE | POURCENTAGE | EFFECTIF | MONETAIRE | SANS_UNITE
  condition : SPATIAL | TEMPOREL | ORGANISATIONNEL | CIRCONSTANCIEL
            | POPULATIONNEL | SEUIL | ACTIVITE
  raci      : R | A | C | I
```

### 4.5 Où passe réellement le coût

L'extraction est **le poste dominant de toute la chaîne**, pas la détection. 300 clauses × ~120 tokens de frame = ~36 000 tokens générés par document ; en extraction 100 % LLM sur Mistral 7B Q4 en CPU (~10 tok/s), c'est **1 h par document**. D'où l'hybridation :

| Levier | Effet |
|---|---|
| Règles d'abord | ~60 % des champs remplis sans LLM ; ~40 % des clauses sans aucun appel |
| Lots de 8 clauses | ÷ 7 sur le nombre d'appels |
| Cache par `hash` | ré-analyse d'un document modifié : seules les clauses changées |
| Profil hybride (API gratuite) | 300 clauses / 8 ≈ 38 appels, très en dessous du quota Gemini (1 500 req/jour) |

**≈ 5–8 min par document en profil local GPU, ≈ 30–45 s en profil hybride.**

### 4.6 Deux profils d'exécution

Les documents QHSE sont souvent confidentiels : l'architecture prévoit un commutateur, pas un fournisseur unique.

| | **Profil A — Local strict** | **Profil B — Hybride** |
|---|---|---|
| Extraction (L1) | Mistral 7B Q4 (LM Studio) | Gemini 2.5 Flash / Groq |
| Autonomisation (L0.7) | Mistral 7B Q4 | Mistral 7B Q4 |
| Jugement final (L4-C) | Mistral 7B Q4 | Gemini 2.5 Flash / Llama 3.3 70B |
| Données sortant du réseau | **aucune** | extraits de clauses |
| Qualité de jugement | moyenne (plus d'abstentions) | bonne |
| Durée / paire de documents | ~15 min | ~5 min |

Les deux passent par une interface `LLMClient` unique (endpoint OpenAI-compatible) : changer de profil est une variable d'environnement. Les quotas gratuits étant volatils, le client implémente un **basculement automatique** sur 429/404, avec repli terminal sur le modèle local.

---

## 5. L2 — Le modèle de graphe Neo4j *(révisé en v2)*

### 5.0 Ce qui manquait à la v1, et pourquoi

Le modèle v1 décrivait correctement **un document**. Il ne décrivait pas **un système documentaire QHSE**. Six manques, dont trois provoquent des faux positifs en série dès le premier corpus réel :

| # | Manque | Conséquence concrète si on ne le corrige pas |
|---|---|---|
| **M1** | Les **conditions** ne sont pas des nœuds | Le test de recouvrement des portées est recalculé texte contre texte à chaque paire, et n'est ni caché ni auditables. Or c'est lui qui distingue une contradiction d'une spécialisation. **Source n°1 de faux positifs.** |
| **M2** | Aucun **cycle de vie documentaire** | Une version abrogée est comparée à la version courante → chaque révision de document produit des dizaines de faux conflits. Une dérogation explicitement déclarée est signalée comme contradiction. **Rédhibitoire.** |
| **M3** | Aucune **hiérarchie documentaire** | Impossible de dire *qui a tort* entre une politique et une instruction, ni de détecter le cas le plus grave en QHSE : un document de niveau inférieur plus permissif que celui dont il dérive. |
| **M4** | Pas de **validité temporelle** | Deux clauses contradictoires mais applicables à des périodes disjointes sont signalées à tort. |
| **M5** | `NormeExterne` trop grossier, `statut` en texte libre | « remplacée par ISO 45001 » est une chaîne de caractères : le lien n'est pas parcourable. Et la réglementation QHSE se cite à l'**article** (`art. R.4321-1`), pas au référentiel. |
| **M6** | Aucune **couche de résultat** | La démo de bout en bout a produit des nœuds `Anomalie`, `Constatation` et une arête `SPECIALISE_PAR` qui **n'existent pas dans le schéma**. Les constatations mono-clause (renvoi cassé) n'ont nulle part où aller, `INCOHERENT_AVEC` étant `Clause → Clause`. |

Trois manques mineurs par ailleurs : `IMPOSE_A` confondait exécutant et valideur (RACI) ; les détecteurs `A4` évoquaient des arêtes `RESPONSABLE_DE` / `VALIDE` absentes du schéma ; les périmètres d'application (site, atelier, population) n'étaient représentés nulle part.

### 5.1 Principe de modélisation retenu

> **Un label primaire par nature de chose, des sous-labels pour les spécialisations métier.**

`Concept` reste **le** point d'entrée du vocabulaire, avec des sous-labels Neo4j (`:Concept:Acteur`, `:Concept:Risque`, …). Bénéfice décisif : **le pont inter-documents (`ALIAS_DE`), l'index vectoriel et le calcul d'IDF continuent de fonctionner uniformément sur tout le vocabulaire**, quel que soit le sous-type. Ajouter un type métier ne demande aucun code supplémentaire.

### 5.2 Nœuds

#### Couche documentaire

| Label | Rôle | Propriétés |
|---|---|---|
| `Document` | fichier `.txt` | `doc_id`, `titre`, `code` (`PR-QSE-04`), `type` (POLITIQUE / MANUEL / PROCEDURE / INSTRUCTION / CONSIGNE / ENREGISTREMENT / NORME_INTERNE), **`niveau_hierarchique`** (0–5) ⭐, `version`, `date_application` ⭐, `date_revision` ⭐, **`statut`** (EN_VIGUEUR / ABROGE / PROJET) ⭐, `langue`, `hash` |
| `Section` | nœud de structure | `section_id`, `titre`, `chemin`, `niveau`, `numero` |
| `Clause` | **unité normative** | `clause_id`, `texte_source`, `texte_autonome`, `offset`, `hash`, `origine` (TEXTE / LISTE / TABLEAU) ⭐, `type_enonce` ⭐, `modalite`, `force`, `negation`, `portee_quantificateur`, `date_debut_validite` ⭐, `date_fin_validite` ⭐, `cle_comparaison`, `embedding` (1024 f.), `confiance_extraction`, `source_extraction` |

#### Couche sémantique

| Label | Rôle | Propriétés |
|---|---|---|
| `Concept` | terme normalisé du domaine | `concept_id`, `libelle`, `libelle_canonique`, `type`, `idf`, `embedding`, `frequence` |
| ↳ `:Acteur` ⭐ | rôle, fonction, service | `+ famille` (INTERNE / EXTERNE / INSTANCE) |
| ↳ `:Risque` ⭐ | danger ou risque QHSE | `+ famille` (CHUTE / CHIMIQUE / ATEX / BRUIT / ELECTRIQUE / TMS / INCENDIE / ENVIRONNEMENTAL…) |
| ↳ `:Perimetre` ⭐ | site, atelier, activité, population | `+ type` (SITE / ATELIER / ACTIVITE / POPULATION / ENTITE) |
| ↳ `:Equipement` ⭐ | EPI, machine, installation | |
| ↳ `:Substance` ⭐ | produit chimique, agent | `+ cas_number` |
| ↳ `:Competence` ⭐ | habilitation, formation, autorisation | |
| ↳ `:Enregistrement` ⭐ | type de preuve documentaire | |
| ↳ `:Processus` ⭐ | processus du système QHSE | |
| `Quantite` | grandeur réifiée | `dimension`, `role`, `valeur`, `unite`, `valeur_si`, `operateur` (= / ≤ / ≥ / < / >) ⭐, `qualificateurs`, `surface`, `monotonie` ⭐ |
| **`Condition`** ⭐ | condition d'applicabilité réifiée | `condition_id`, `surface`, `type` (SPATIAL / TEMPOREL / ORGANISATIONNEL / CIRCONSTANCIEL / POPULATIONNEL / SEUIL / ACTIVITE), `operateur`, `valeur`, `embedding` |

#### Couche référentiel externe

| Label | Rôle | Propriétés |
|---|---|---|
| `NormeExterne` | référentiel cité | `code` (`ISO 45001`), `version`, `titre`, `statut` (EN_VIGUEUR / RETIREE / PROJET), `date_retrait` |
| **`ExigenceExterne`** ⭐ | article opposable | `reference` (`art. R.4321-1`), `source` (Code du travail / décret / arrêté), `texte`, `statut`, `date_abrogation` |

#### Couche résultat ⭐ *(entièrement nouvelle)*

| Label | Rôle | Propriétés |
|---|---|---|
| **`Constatation`** | résultat consolidé présenté à l'utilisateur | `constatation_id`, `type`, `gravite`, `criticite`, `score`, `explication`, `statut` (A_VALIDER / CONFIRMEE / REJETEE_UTILISATEUR / RESOLUE), `nb_occurrences`, `detecteurs`, `hypotheses` (alias utilisés), `run_id`, `horodatage` |
| **`Anomalie`** | défaut mono-clause (renvoi cassé, référentiel retiré, dérogation orpheline) | `type`, `cible_non_resolue`, `score` |

**Pourquoi `Constatation` est un nœud et non une propriété d'arête.** Trois raisons : (a) une même incohérence de fond se manifeste sur 8 à 12 paires de clauses — un nœud porte les N occurrences, une arête ne le peut pas ; (b) les défauts mono-clause n'ont pas de seconde clause à relier ; (c) le cycle de validation utilisateur (confirmée / rejetée / résolue) et l'historique s'attachent naturellement à un nœud. C'est aussi ce qui permet de mesurer, run après run, si une incohérence a été corrigée.

**Pourquoi réifier `Quantite`.** « Toutes les clauses de tous les documents qui fixent une périodicité pour le même objet » devient un parcours de graphe ; et une clause peut porter plusieurs grandeurs de rôles différents (un délai *et* un seuil).

**Pourquoi réifier `Condition`.** C'est l'ajout le plus rentable de la v2. Un corpus de 10 documents contient typiquement 2 000 clauses mais seulement **60 à 120 conditions distinctes** (« en zone A », « en cas d'incident grave », « pour les intervenants extérieurs »…). Le recouvrement se calcule donc **une fois par paire de conditions** — quelques milliers de comparaisons, dont une poignée escaladées au LLM — puis se **réutilise sur des dizaines de milliers de paires de clauses**. En v1, la même question était reposée à chaque paire. Et le résultat, matérialisé dans le graphe, devient auditable : *« ces deux clauses ne se contredisent pas parce que "en zone A" et "en zone de stockage" sont disjoints »*.

### 5.3 Arêtes

#### Structure et extraction

| Type | De → Vers | Sémantique | Propriétés |
|---|---|---|---|
| `CONTIENT` | Document\|Section → Section\|Clause | structure | `ordre` |
| `SUIT` | Clause → Clause | ordre de lecture | |
| `MENTIONNE` | Clause → Concept | la clause parle de ce concept | `role`, `poids` |
| `IMPOSE_A` | Clause → Concept:Acteur | l'exigence pèse sur cet acteur | **`raci`** (R/A/C/I) ⭐, `confiance` |
| `PORTE` | Clause → Quantite | la clause fixe cette grandeur | |
| **`SOUS_CONDITION`** ⭐ | Clause → Condition | la clause ne s'applique que sous cette condition | `negatif` (bool : « sauf … ») |
| **`S_APPLIQUE_A`** ⭐ | Document\|Clause → Concept:Perimetre | périmètre d'application | `exclusif` |
| **`MAITRISE`** ⭐ | Clause → Concept:Risque | la clause est une mesure de maîtrise d'un risque | `type_mesure` (SUPPRESSION / PROTECTION_COLLECTIVE / EPI / ORGANISATIONNELLE / FORMATION) |
| **`EXIGE_COMPETENCE`** ⭐ | Clause → Concept:Competence | habilitation requise | |
| `DEFINIT` | Clause → Concept | clause de définition | |

#### Renvois et référentiel externe

| Type | De → Vers | Sémantique | Propriétés |
|---|---|---|---|
| `RENVOIE_A` | Clause → Clause\|Section\|Document | renvoi explicite (`cf. §5.4`) | `surface`, `resolu` (bool) |
| `CITE_NORME` | Clause → NormeExterne | référence normative | `version_citee` |
| **`CITE_EXIGENCE`** ⭐ | Clause → ExigenceExterne | référence réglementaire à l'article | |
| **`CONTIENT_EXIGENCE`** ⭐ | NormeExterne → ExigenceExterne | structure du référentiel | |
| **`REMPLACE`** ⭐ | NormeExterne → NormeExterne | succession normative *(remplace la propriété texte `statut` de la v1)* | `date` |

#### Cycle de vie du système documentaire ⭐ *(bloc entièrement nouveau)*

| Type | De → Vers | Sémantique | Propriétés |
|---|---|---|---|
| **`ANNULE_ET_REMPLACE`** | Document → Document | « le présent document annule et remplace PR-QSE-03 v2 » | `date` |
| **`DECLINE`** | Document → Document | une procédure décline une politique ; une instruction décline une procédure | `explicite` (bool) |
| **`DEROGE_A`** | Clause → Clause\|Document | « par dérogation à PR-QSE-04 §3.1… » | `justification`, `approuvee_par`, `echeance` |
| **`REMPLACE_CLAUSE`** | Clause → Clause | même clause à travers deux versions d'un document | `version_source`, `version_cible` |

#### Alignement inter-documents

| Type | De → Vers | Sémantique | Propriétés |
|---|---|---|---|
| `ALIAS_DE` | Concept → Concept | **pont inter-documents** | `score`, `methode` (EXACT / LEXIQUE / VECTEUR / LLM) |
| **`RECOUVRE`** ⭐ | Condition → Condition | les deux conditions peuvent être vraies ensemble | `score`, `methode` |
| **`INCLUS_DANS`** ⭐ | Condition → Condition | A ⊂ B : A est un cas particulier de B | `score`, `methode` |
| **`DISJOINT_DE`** ⭐ | Condition → Condition | jamais vraies ensemble | `score`, `methode` |

#### Couche pipeline et résultat

| Type | De → Vers | Sémantique | Propriétés |
|---|---|---|---|
| `PAIRE_CANDIDATE` | Clause → Clause | paire retenue pour vérification | `score`, `canaux[]`, `rang`, `run_id` |
| `INCOHERENT_AVEC` | Clause → Clause | verdict de conflit | `type`, `score`, `detecteur`, `preuve_a`, `preuve_b`, `explication`, `run_id` |
| **`SPECIALISE`** ⭐ | Clause → Clause | A restreint B et est plus stricte : **compatible, pas un conflit** | `score`, `detecteur` |
| **`IMPLIQUE`** ⭐ | Constatation → Clause | les clauses concernées par une constatation | `role` (SOURCE / CIBLE) |
| **`SIGNALE`** ⭐ | Anomalie → Clause | défaut mono-clause | |
| **`CONCERNE`** ⭐ | Constatation → Concept\|NormeExterne\|Concept:Risque | objet métier de la constatation, pour le filtrage du rapport | |

### 5.4 Récapitulatif v1 → v2

| | v1 | v2 |
|---|---|---|
| Labels primaires | 6 | **10** (+ 8 sous-labels de `Concept`) |
| Types d'arêtes | 11 | **28** |
| Blocs nouveaux | — | conditions · cycle de vie documentaire · référentiel à l'article · couche résultat |

### 5.5 Schéma Cypher

```cypher
// ─── Contraintes d'unicité (créent les index) ───────────────────────────────
CREATE CONSTRAINT doc_id      IF NOT EXISTS FOR (d:Document)    REQUIRE d.doc_id       IS UNIQUE;
CREATE CONSTRAINT section_id  IF NOT EXISTS FOR (s:Section)     REQUIRE s.section_id   IS UNIQUE;
CREATE CONSTRAINT clause_id   IF NOT EXISTS FOR (c:Clause)      REQUIRE c.clause_id    IS UNIQUE;
CREATE CONSTRAINT concept_id  IF NOT EXISTS FOR (k:Concept)     REQUIRE k.concept_id   IS UNIQUE;
CREATE CONSTRAINT cond_id     IF NOT EXISTS FOR (x:Condition)   REQUIRE x.condition_id IS UNIQUE;
CREATE CONSTRAINT norme_code  IF NOT EXISTS FOR (n:NormeExterne)
       REQUIRE (n.code, n.version) IS UNIQUE;
CREATE CONSTRAINT exig_ref    IF NOT EXISTS FOR (e:ExigenceExterne)
       REQUIRE (e.reference, e.source) IS UNIQUE;
CREATE CONSTRAINT const_id    IF NOT EXISTS FOR (f:Constatation) REQUIRE f.constatation_id IS UNIQUE;

// ─── Index de filtrage ──────────────────────────────────────────────────────
CREATE INDEX clause_doc      IF NOT EXISTS FOR (c:Clause)   ON (c.doc_id);
CREATE INDEX clause_modalite IF NOT EXISTS FOR (c:Clause)   ON (c.modalite);
CREATE INDEX clause_cle      IF NOT EXISTS FOR (c:Clause)   ON (c.cle_comparaison);
CREATE INDEX clause_validite IF NOT EXISTS FOR (c:Clause)   ON (c.date_debut_validite, c.date_fin_validite);
CREATE INDEX doc_statut      IF NOT EXISTS FOR (d:Document) ON (d.statut, d.niveau_hierarchique);
CREATE INDEX qte_dim         IF NOT EXISTS FOR (q:Quantite) ON (q.dimension, q.role);
CREATE INDEX cond_type       IF NOT EXISTS FOR (x:Condition) ON (x.type);
CREATE INDEX const_statut    IF NOT EXISTS FOR (f:Constatation) ON (f.statut, f.criticite);

// ─── Index plein texte (canal lexical) ──────────────────────────────────────
CREATE FULLTEXT INDEX clause_ft IF NOT EXISTS
FOR (c:Clause) ON EACH [c.texte_autonome]
OPTIONS { indexConfig: { `fulltext.analyzer`: 'french' } };

// ─── Index vectoriels ───────────────────────────────────────────────────────
CREATE VECTOR INDEX clause_vec IF NOT EXISTS
FOR (c:Clause) ON (c.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 1024, `vector.similarity_function`: 'cosine' }};

CREATE VECTOR INDEX concept_vec IF NOT EXISTS
FOR (k:Concept) ON (k.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 1024, `vector.similarity_function`: 'cosine' }};

CREATE VECTOR INDEX condition_vec IF NOT EXISTS
FOR (x:Condition) ON (x.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 1024, `vector.similarity_function`: 'cosine' }};
```

> **Note de version.** Depuis Neo4j 2026.01, les index vectoriels acceptent des propriétés de filtrage dans l'index et se requêtent via la clause `SEARCH` ; `db.index.vector.queryNodes` reste disponible, déprécié depuis 2026.04. Une petite couche d'abstraction garde la compatibilité 5.x → 2026.x. Index vectoriel, plein texte et sous-labels sont disponibles en **Community Edition** : aucune licence requise.

### 5.6 Le pont inter-documents

**Le problème.** Deux documents rédigés par deux services n'emploient pas le même vocabulaire :

```
D1 (procédure) : « Le Responsable HSE valide les fiches d'arrêt sous 48 h. »
D2 (politique) : « Le Référent sécurité est chargé de valider les fiches
                   de mise à l'arrêt dans un délai de 5 jours. »
```

Sans alignement, ces concepts sont deux nœuds distincts : **le graphe est en deux composantes connexes disjointes**, aucun candidat n'est produit, l'incohérence reste invisible. **Le pont est la pièce maîtresse, pas un raffinement.**

**Résolution en cascade de coût croissant :**

```
 pour chaque paire de Concepts issus de documents différents
   │
   ├─ 1. Identité normalisée   minuscules, sans accents ni déterminants, lemmatisée
   │      → ALIAS_DE {EXACT, 1.00}
   │
   ├─ 2. Lexique métier QHSE + acronymes
   │      HSE = QSE = QHSE · EPI = équipement de protection individuelle
   │      DUERP · CSE · SST · ATEX · FDS = fiche de données de sécurité
   │      → ALIAS_DE {LEXIQUE, 0.95}
   │
   ├─ 3. Similarité vectorielle
   │      cos ≥ 0.86             → ALIAS_DE {VECTEUR, cos}
   │      0.72 ≤ cos < 0.86      → zone grise, étape 4
   │      cos < 0.72             → rejeté
   │
   └─ 4. Arbitrage LLM (~5 % des paires)
          « Dans un document QHSE, X et Y désignent-ils la même fonction /
            le même objet ? OUI / NON / INCERTAIN + justification »
          → ALIAS_DE {LLM, 0.8} ou aucune arête
```

Les alias forment des classes d'équivalence (union-find) dont on élit un **représentant canonique** (le libellé le plus fréquent). Toutes les requêtes de ciblage passent par le canonique.

> ⚠️ **Le risque à documenter.** Un alias erroné crée des faux positifs en cascade. Les alias sont donc (a) tracés avec méthode et score, (b) exposés dans le rapport comme hypothèses révisables, (c) le **premier levier de réglage** en cas de dérive de précision. Un alias produit par LLM ne suffit jamais seul à un verdict ferme.

### 5.7 ⭐ L'algèbre des conditions

Chaque `Condition` distincte est comparée aux autres **une seule fois**, et le résultat est matérialisé.

```
 pour chaque paire de Conditions (types compatibles)
   │
   ├─ 1. Identité de surface normalisée        → RECOUVRE {EXACT, 1.00}
   │
   ├─ 2. Règles typées (sans modèle)
   │      SPATIAL      hiérarchie des lieux : « zone A » ⊂ « site de Radès »
   │                   → INCLUS_DANS
   │                   « zone A » vs « zone B » (mêmes parent, valeurs distinctes)
   │                   → DISJOINT_DE
   │      SEUIL        « au-delà de 2 m » vs « en deçà de 2 m » → DISJOINT_DE
   │                   « au-delà de 2 m » vs « au-delà de 5 m » → INCLUS_DANS
   │      TEMPOREL     intervalles de dates → recouvrement calculé
   │      POPULATIONNEL « intervenants extérieurs » ⊂ « tout intervenant »
   │                   → INCLUS_DANS  (via ALIAS_DE et hyperonymie du lexique)
   │      condition vide d'un côté → l'autre est INCLUS_DANS
   │
   ├─ 3. Vecteur         cos ≥ 0.90 → RECOUVRE  ·  cos < 0.55 → DISJOINT_DE
   │
   └─ 4. LLM (zone grise seulement) — question fermée, jamais ouverte :
          « Existe-t-il une situation concrète satisfaisant simultanément
            la condition A et la condition B ? Et si oui, l'une est-elle un
            cas particulier de l'autre ? »
```

**Le rendement.** Un corpus de 10 documents / 2 000 clauses contient ~90 conditions distinctes → ~4 000 paires de conditions, dont ~150 en zone grise. Ces 150 appels LLM sont payés **une fois** et servent l'ensemble des paires de clauses du corpus, y compris lors des ré-exécutions.

### 5.8 La clé de comparaison

Chaque clause reçoit une signature de ce dont elle parle, indépendamment de sa formulation :

```
cle_comparaison = (acteur_canonique, action_canonique, objet_canonique,
                   dimension_grandeur, role_grandeur)

D1::C12 : (RESP_QSE, VALIDER, FICHE_ARRET, TEMPS, delai)  valeur = 172 800 s  (48 h)
D2::C07 : (RESP_QSE, VALIDER, FICHE_ARRET, TEMPS, delai)  valeur = 432 000 s  (5 j)
          ▲ même clé, valeurs différentes, documents différents
```

`*` en position acteur = joker (tournure passive). Un simple `GROUP BY cle_comparaison HAVING count(DISTINCT valeur) > 1` suffit : coût quasi nul, précision très élevée. C'est la transposition du principe de vérification interne d'Icertis, **construite automatiquement** et généralisée à N documents.

### 5.9 ⭐ La hiérarchie documentaire

```
   niveau 0   EXIGENCES EXTERNES     Code du travail, décrets, normes  ← opposable
      ▲                                                                  à tous
      │ DECLINE
   niveau 1   POLITIQUE / ENGAGEMENT DE DIRECTION
      ▲
      │ DECLINE
   niveau 2   MANUEL QHSE / DOCUMENTS SYSTÈME
      ▲
      │ DECLINE
   niveau 3   PROCÉDURES
      ▲
      │ DECLINE
   niveau 4   INSTRUCTIONS · MODES OPÉRATOIRES · CONSIGNES
      ▲
      │
   niveau 5   ENREGISTREMENTS · FORMULAIRES
```

`niveau_hierarchique` est déduit du `type` de document, lui-même détecté par le code documentaire (`PO-`, `MA-`, `PR-`, `IN-`, `MO-`, `FO-`), le titre, ou renseigné manuellement dans un fichier de configuration du corpus (2 minutes de saisie, gain considérable).

**La règle d'or QHSE, qui donne le détecteur A9 :**

> Un document de niveau inférieur peut être **plus strict** que celui dont il dérive : c'est une déclinaison légitime. Il ne peut pas être **plus permissif** : c'est une non-conformité. Et aucun document, à aucun niveau, ne peut être plus permissif qu'une exigence externe.

C'est aussi ce qui permet au rapport de dire **qui a tort**, et non seulement que deux clauses divergent — ce que demandera systématiquement l'auditeur qualité.

---

## 6. L3 — Le ciblage : 3 filtres d'éligibilité, 5 canaux, une fusion

**C'est ici que se joue la promesse du sujet.** On passe de `n₁ × n₂` paires théoriques à `O(n · k)`.

### 6.0 ⭐ Filtres d'éligibilité — appliqués **avant** tout canal

Nouveauté v2 : trois filtres qui écartent des paires que le corpus a lui-même déjà résolues (invariant I4). Ils s'appliquent au niveau du document ou de la clause, coûtent une requête, et suppriment la majorité des faux positifs d'un système documentaire réel.

```cypher
// F1 · Exclure les documents abrogés ou remplacés
MATCH (d:Document)
WHERE d.statut = 'ABROGE' OR EXISTS { (:Document)-[:ANNULE_ET_REMPLACE]->(d) }
SET d.eligible = false;

// F2 · Exclure les paires de clauses dont les périodes de validité sont disjointes
//      (appliqué à la volée dans chaque canal)
WHERE NOT (a.date_fin_validite < b.date_debut_validite
        OR b.date_fin_validite < a.date_debut_validite)

// F3 · Marquer — et non supprimer — les paires couvertes par une dérogation déclarée
MATCH (a:Clause)-[d:DEROGE_A]->(b)
SET a.derogation_vers = b.clause_id;
```

📌 **F3 ne supprime pas la paire, il la requalifie.** Une dérogation déclarée n'est pas une incohérence, mais elle n'est pas non plus un non-événement : le rapport la liste dans une rubrique « dérogations en vigueur », avec son échéance et son approbateur. Une dérogation **sans justification, sans approbateur ou expirée** est elle-même une constatation (détecteur A8).

### 6.1 Canal 1 — Structurel (renvois explicites) · précision très élevée

```cypher
MATCH (a:Clause)-[:RENVOIE_A]->(t)
MATCH (t)<-[:CONTIENT*0..3]-()<-[:CONTIENT*0..3]-(b:Clause)
WHERE a.doc_id <> b.doc_id AND a.eligible AND b.eligible
RETURN a, b, 1.0 AS score, 'STRUCTUREL' AS canal
```

Un `RENVOIE_A` **non résolu** est déjà, à lui seul, une anomalie de type *Factual* — remontée sans aucune comparaison.

### 6.2 Canal 2 — Clé de comparaison · coût nul, précision très élevée

```cypher
MATCH (a:Clause)-[:PORTE]->(qa:Quantite), (b:Clause)-[:PORTE]->(qb:Quantite)
WHERE a.doc_id < b.doc_id
  AND a.cle_comparaison = b.cle_comparaison
  AND qa.dimension = qb.dimension AND qa.role = qb.role
RETURN a, b, 1.0 AS score, 'CLE' AS canal
```

### 6.3 Canal 3 — Conceptuel (2 sauts) · le canal principal en rappel

```cypher
MATCH (a:Clause)-[ma:MENTIONNE]->(k:Concept)<-[mb:MENTIONNE]-(b:Clause)
WHERE a.doc_id < b.doc_id AND k.idf > 1.5
WITH a, b, sum(ma.poids * mb.poids * k.idf) AS score, count(k) AS partages
WHERE partages >= 2
RETURN a, b, score, 'CONCEPTUEL' AS canal
```

Les `Concept` sont ici les **canoniques** (après résolution des alias) : c'est ce qui permet à une clause parlant du « Responsable HSE » de rencontrer une clause parlant du « Référent sécurité ». Le canal exploite aussi les sous-labels : deux clauses qui `MAITRISE` le même `:Risque`, ou qui `EXIGE_COMPETENCE` la même habilitation, sont candidates même sans vocabulaire commun.

### 6.4 Canal 4 — Vectoriel (k-NN) · le filet de sécurité

```cypher
MATCH (a:Clause) WHERE a.doc_id = $doc_a
CALL db.index.vector.queryNodes('clause_vec', 12, a.embedding)
YIELD node AS b, score
WHERE b.doc_id <> a.doc_id AND score >= 0.70
RETURN a, b, score, 'VECTORIEL' AS canal
```

Modèle : **BAAI/bge-m3** (1024 d, MIT, français solide, 8 192 tokens) ou **OrdalieTech/Solon-embeddings-large** (natif FR, MIT). Choix final par mesure du rappel sur le mini-corpus, pas sur le classement MTEB générique.

### 6.5 ⭐ Canal 5 — Dimension seule · le rattrapage du vocabulaire disjoint

**Motivation.** La démonstration de bout en bout a perdu une incohérence réelle — « signalée sous **24 heures** » vs « remontées **dans la semaine** » — parce que les quatre premiers canaux reposent tous sur un partage lexical ou conceptuel : aucun terme commun, similarité vectorielle 0,67 sous le seuil. Le canal 5 est indépendant du vocabulaire.

```cypher
MATCH (a:Clause)-[:PORTE]->(qa:Quantite), (b:Clause)-[:PORTE]->(qb:Quantite)
WHERE a.doc_id < b.doc_id
  AND qa.dimension = qb.dimension AND qa.role = qb.role
  AND qa.valeur_si <> qb.valeur_si
WITH a, b, vector.similarity.cosine(a.embedding, b.embedding) AS sim
ORDER BY sim DESC
RETURN a, b, sim, 'DIMENSION' AS canal
LIMIT 3   // top-3 par clause, SANS seuil de similarité
```

> **Le principe :** deux clauses qui fixent un délai pour deux choses apparemment différentes méritent un coup d'œil, même si elles n'ont aucun mot en commun — parce qu'un délai est rare et qu'un corpus n'en contient qu'une poignée par rôle. Le canal produit peu de paires et rattrape exactement les cas que le vocabulaire cache.

**Sous-correctif indispensable.** Le canal 5 ne voit une clause que si une grandeur y a été extraite. Le patron `DELAI` doit donc couvrir les expressions vagues (`dans la semaine`, `sous quinzaine`, `dans les meilleurs délais`, `sans délai`), converties en intervalle avec un drapeau `IMPRECIS` — signalé comme tel dans le rapport.

### 6.6 Fusion et budget

Les scores de canaux différents ne sont pas comparables (un cosinus n'est pas un poids IDF) : on fusionne **par rang** — *Reciprocal Rank Fusion*.

```
RRF(a,b) = Σ_canaux  w_c / (60 + rang_c(a,b))

w_STRUCTUREL = 3.0   w_CLE = 3.0   w_CONCEPTUEL = 1.5
w_VECTORIEL  = 1.0   w_DIMENSION = 1.2
```

Puis trois filtres :

1. **Comparabilité** — une paire n'est retenue que si : modalité prescriptive des deux côtés, **ou** grandeurs de même dimension **et** même rôle, **ou** renvoi explicite. Une définition et un seuil ne se contredisent pas.
2. **Budget par clause** — `top-k = 8` ; les canaux 1 et 2 sont exemptés du plafond (trop précis pour être coupés).
3. **Budget global** — `B = 4 × max(n₁, n₂)`. Au-delà, troncature par score, **journalisée** : c'est une information de qualité, pas un détail d'implémentation.

```cypher
MERGE (a)-[p:PAIRE_CANDIDATE]->(b)
SET p.score = $score, p.canaux = $canaux, p.rang = $rang,
    p.run_id = $run_id, p.horodatage = datetime()
```

Cette matérialisation rend le système **auditable et incrémental** : on peut expliquer *pourquoi* une paire a été examinée, et rejouer la vérification sans refaire le ciblage.

### 6.7 Réduction obtenue (2 documents de ~300 clauses)

| Étape | Paires |
|---|---|
| Espace théorique `n₁ × n₂` | 90 000 |
| Après filtres d'éligibilité (F1–F3) | ~86 000 |
| Union des 5 canaux | ~5 400 |
| Après filtre de comparabilité | ~2 300 |
| Après top-k et budget | **~1 200** |
| **Facteur de réduction** | **≈ 75 ×** |

> **La métrique qui compte n'est pas le facteur de réduction, c'est le rappel du ciblage.** Une paire écartée en L3 ne sera jamais rattrapée en L4 : le rappel du ciblage **plafonne** le rappel du système entier. Objectif : **≥ 0,95**, la réduction n'étant optimisée qu'à rappel constant.

---

## 7. L4 — La cascade de vérification

```
   PAIRE CANDIDATE
        │
        ▼
   ┌────────────────────────────────────────────┐
   │ A. DÉTECTEURS SYMBOLIQUES        ~0,1 ms   │
   │    A1 … A9, comparaison de frames          │
   └────┬───────────────────┬───────────────────┘
        │ verdict ferme     │ pas de verdict / champs LLM impliqués
        ▼                   ▼
   INCOHÉRENCE      ┌────────────────────────────────────────┐
   (score ≥ 0,90)   │ B. NLI bidirectionnel      ~25 ms      │
                    └───┬──────────────┬──────────────┬──────┘
                        │ NEUTRE       │ CONTRADICTION│ zone grise
                        │ p<0,15       │ p>0,85       │ 0,15–0,85
                        ▼              ▼              ▼
                   REJETÉE      INCOHÉRENCE    ┌──────────────────────┐
                                (score 0,80)   │ C. LLM JUGE   ~2–5 s │
                                               │  + sous-graphe 2 sauts│
                                               └───┬───────┬───────┬──┘
                                                   ▼       ▼       ▼
                                            INCOHÉRENCE  REJET  ABSTENTION
```

### 7.1 Étage A — Neuf détecteurs symboliques

#### A1 · Conflit déontique *(corrigé en v2 : écart de force)*

La v1 marquait « — » les cases OBLIGATION × RECOMMANDATION. Or c'est une incohérence réelle et sérieuse : *la procédure impose ce que la politique se contente de recommander* — un intervenant peut alors invoquer la politique pour ne pas porter son casque, et l'obligation devient inopposable. Les cases vides sont remplacées par un **écart de force** :

```
échelle :  interdiction 4  ·  obligation 3  ·  recommandation 2  ·  permission 1
ecart = |force(A) − force(B)|   (après application de negation)

ecart = 0  → aucun conflit
ecart = 1  → DIVERGENCE_PERSPECTIVE, non ferme, escalade obligatoire vers B
ecart ≥ 2  → CONFLIT FORT (obligation vs permission, interdiction vs recommandation)
polarité opposée (obligation vs interdiction) → CONFLIT FORT quel que soit l'écart
```

Déclenchement : même `acteur_canonique`, `action_canonique`, `objet_canonique`, **et** conditions non disjointes (§7.2).

#### A2 · Divergence de valeurs *(type Numeric)*

```python
def a2(fa, fb):
    for qa in fa.quantites:
        for qb in fb.quantites:
            if (qa.dimension, qa.role) != (qb.dimension, qb.role):
                continue
            rel = relation_portees(fa, fb)            # §7.2
            if rel == "DISJOINTE":
                continue                              # pas un conflit
            if qa.valeur_si != qb.valeur_si:
                if rel == "INCLUSION":
                    return escalade_C(motif="inclusion de portée")
                ecart = abs(qa.valeur_si - qb.valeur_si) / max(qa.valeur_si, qb.valeur_si)
                return Verdict("NUMERIQUE", 0.95, gravite_par_ecart(ecart),
                               preuve=(qa.surface, qb.surface))
            if qa.qualificateurs != qb.qualificateurs:   # 5 j ouvrés vs 5 j calendaires
                return Verdict("NUMERIQUE_QUALIFICATEUR", 0.85)
```

#### A3 · Divergence d'attribut *(type Content)*

Clés identiques sur 3 des 4 champs (acteur / action / objet / condition), différence sur le quatrième, les deux valeurs venant de concepts canoniques non alias l'un de l'autre. Si l'un des champs a été rempli par le LLM → pas de verdict ferme, escalade en B.

#### A4 · Conflit de responsabilité *(type Relation — RACI)* ⭐ *révisé*

La v1 invoquait des arêtes `RESPONSABLE_DE` / `VALIDE` qui n'existaient pas dans le schéma. La v2 les remplace par la propriété `raci` de `IMPOSE_A`. **La règle est plus fine qu'une simple exclusivité** : plusieurs acteurs peuvent être `C` ou `I` sur une même tâche ; il ne peut y avoir **qu'un seul `A`** (approbateur) et, en pratique QHSE, un seul `R` principal.

```cypher
MATCH (c:Clause)-[i:IMPOSE_A]->(a:Concept:Acteur)
WHERE i.raci IN ['R','A'] AND c.eligible
WITH c.action_canonique AS action, c.objet_canonique AS objet, i.raci AS raci,
     collect(DISTINCT a.concept_id) AS acteurs, collect(DISTINCT c.doc_id) AS docs
WHERE size(acteurs) > 1 AND size(docs) > 1
RETURN action, objet, raci, acteurs, docs
```

#### A5 · Référence cassée, référentiel obsolète ou divergent *(type Factual)*

- `RENVOIE_A` non résolu → **référence cassée** *(anomalie mono-clause)*.
- `CITE_NORME` vers une norme dont `statut = 'RETIREE'`, ou pour laquelle il existe `(n)-[:REMPLACE]->(:NormeExterne)` → **référentiel obsolète**.
- Deux documents citant des versions différentes du même référentiel → **divergence de référentiel**.
- ⭐ `CITE_EXIGENCE` vers un article abrogé → **non-conformité réglementaire**, criticité maximale.

Registre amorcé à la main (~40 normes + ~60 articles QHSE : ISO 45001, ISO 14001, ISO 9001, OHSAS 18001 retirée, NF EN 397, art. R.4321-1…), enrichi au fil du corpus.

#### A6 · Divergence terminologique et définitionnelle

Deux libellés alignés par `ALIAS_DE` mais jamais définis de manière convergente ; ou deux clauses `DEFINIT` pointant vers le même concept canonique avec des définitions sémantiquement éloignées (NLI en support). Faible gravité, forte fréquence — le constat le plus courant en audit documentaire.

#### A7 · ⭐ Conflit de validité temporelle

```
deux clauses contradictoires ET périodes de validité qui se chevauchent → conflit réel
deux clauses contradictoires ET périodes disjointes                     → aucun conflit
une clause citée par une autre alors qu'elle est hors validité          → anomalie
un document EN_VIGUEUR déclinant un document ABROGE                     → anomalie
```

#### A8 · ⭐ Dérogation défectueuse

```
DEROGE_A vers une clause ou un document inexistant   → dérogation orpheline
DEROGE_A vers une cible abrogée                      → dérogation obsolète
DEROGE_A sans justification ni approbateur           → dérogation non tracée
DEROGE_A dont l'echeance est dépassée                → dérogation expirée
```

Ces quatre cas sont des constats d'audit classiques. Aucun n'exige de comparaison de contenu.

#### A9 · ⭐ Inversion hiérarchique — le détecteur le plus précieux en QHSE

```python
def a9(fa, fb, doc_a, doc_b):
    if doc_a.niveau == doc_b.niveau:
        return None                                     # pas de hiérarchie applicable
    inferieur, superieur = ordonner(doc_a, doc_b)        # niveau plus grand = inférieur
    rel = relation_portees(fa, fb)
    if rel == "DISJOINTE":
        return None
    sens = registre_grandeurs[role].monotonie            # §4.3
    if plus_permissif(valeur_inferieur, valeur_superieur, sens):
        gravite = "CRITIQUE" if superieur.niveau == 0 else "ELEVEE"
        return Verdict("HIERARCHIQUE", 0.93, gravite,
            explication=f"{inferieur.code} (niveau {inferieur.niveau}) est plus "
                        f"permissif que {superieur.code} (niveau {superieur.niveau}) "
                        f"dont il dérive.")
    return Verdict("SPECIALISATION", relation="SPECIALISE")   # plus strict = légitime
```

**Ce que ce détecteur apporte, et qu'aucun autre ne donne :** il ne dit pas seulement que deux clauses divergent, il dit **laquelle est fautive et pourquoi**. C'est exactement la question que pose l'auditeur, et c'est ce qui transforme un rapport de divergences en un plan d'action.

### 7.2 ⭐ Le test de recouvrement des portées *(corrigé en v2)*

**Deux valeurs différentes ne sont une incohérence que si elles s'appliquent au même périmètre.** C'est la source n°1 de faux positifs.

La v1 traitait « conditions vides d'un côté » comme un recouvrement, donc comme un conflit. C'est faux, et la démonstration l'a montré :

```
D1 §2.1  « Le Responsable QSE valide chaque fiche sous 48 heures. »     (sans condition)
D2 §5.1  « En cas d'incident grave, la fiche est validée sous 24 h. »   (condition)
   → même clé, valeurs différentes, un détecteur naïf crie au conflit
   → en réalité : un sous-cas plus strict. AUCUNE incohérence.
```

**La règle correcte, à quatre cas :**

| Relation des portées | Contrainte de la clause restreinte | Verdict |
|---|---|---|
| **Identiques** | valeur différente | **CONTRADICTION** |
| **Disjointes** | quelconque | **aucun conflit** |
| **Inclusion** (B ⊂ A) | plus **stricte** que A *(selon la monotonie du rôle, §4.3)* | **SPÉCIALISATION** ✅ arête `SPECIALISE` |
| **Inclusion** (B ⊂ A) | plus **permissive** que A | **CONTRADICTION** ⛔ |
| **Indéterminée** | quelconque | escalade obligatoire vers l'étage C |

La relation des portées est **lue dans le graphe** (`RECOUVRE` / `INCLUS_DANS` / `DISJOINT_DE`, §5.7), calculée une fois pour toutes, et non recalculée à chaque paire. Le sens de « plus strict » est lu dans le **registre des grandeurs** (§4.3) : pour un `delai`, plus petit ; pour une `duree_conservation`, plus grand.

### 7.3 Étage B — NLI bidirectionnel

- **Modèle** : `cmarkea/distilcamembert-base-nli` (≈ 2× plus rapide que CamemBERT-base à qualité proche) ; alternatives `BaptisteDoyen/camembert-base-xnli` et `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`. Comparés sur le mini-corpus, pas sur XNLI.
- **Bidirectionnel** : le NLI n'est pas symétrique. On calcule `P(contradiction | A→B)` et `P(contradiction | B→A)`, on retient le maximum.
- **Entrée** : `texte_autonome` préfixé du chemin de section — « [Procédure §5.2 Périodicité] Le contrôle des EPI doit… » — ce qui restitue le contexte perdu par la décontextualisation.
- **Seuils** : calibrés sur le mini-corpus, jamais fixés a priori. Départ : ≥ 0,85 contradiction ferme · ≤ 0,15 rejet · entre les deux → étage C.
- **Coût** : ~25 ms/paire sur CPU en lots de 32 ; 1 200 paires × 2 sens ≈ 60 s.

**Limite assumée.** Ces modèles sont entraînés sur XNLI (langue générique, phrases courtes), pas sur du français normatif. Bons pour repérer une opposition sémantique, mauvais pour juger d'une divergence de portée — d'où leur position d'arbitre intermédiaire et non de juge final.

### 7.4 Étage C — Le LLM juge, conditionné par le graphe

Appelé **uniquement** sur : zone grise du NLI, recouvrement de portées indéterminé, type *Causal*, et incohérences de gravité maximale (double vérification systématique).

**Le contexte de graphe injecté dans le prompt** — l'emprunt à GraphCheck, sans GNN :

```
CLAUSE A  [PR-QSE-04 · niveau 3 · §5.2 Périodicité · en vigueur depuis 2024-01-01]
"Le contrôle des EPI doit être renouvelé tous les trimestres."
  ↳ acteur : Responsable QSE (R)    ↳ objet : contrôle des EPI
  ↳ grandeur : périodicité = 3 mois (plus strict = plus petit)
  ↳ conditions : aucune             ↳ périmètre : site de Radès
  ↳ maîtrise le risque : détérioration d'EPI
  ↳ renvoie à : §5.4                ↳ concepts : EPI, contrôle périodique

CLAUSE B  [POL-SEC-01 · niveau 1 · §3.1 Vérifications · en vigueur depuis 2025-01-01]
"La vérification des équipements de protection est réalisée deux fois par an."
  ↳ acteur : Référent sécurité (R)  (≡ Responsable QSE, alias vecteur 0,88)
  ↳ objet : vérification des équipements de protection (≡ contrôle des EPI, 0,91)
  ↳ grandeur : périodicité = 6 mois
  ↳ conditions : aucune             ↳ périmètre : site de Radès (≡ EXACT)

RELATION DES PORTÉES : IDENTIQUES (aucune condition de part et d'autre)
HIÉRARCHIE           : A est de niveau inférieur à B et PLUS STRICT → déclinaison
SIGNAL AMONT         : divergence numérique 3 mois / 6 mois, écart 50 %
```

**Contrat de sortie (JSON contraint) :**

```json
{
  "verdict": "INCOHERENCE | COHERENT | SPECIALISATION | INDECIDABLE",
  "type": "NEGATION|NUMERIQUE|CONTENU|RELATION|FACTUEL|CAUSAL|PERSPECTIVE|HIERARCHIQUE|TEMPOREL",
  "preuve_a": "<extrait EXACT de la clause A>",
  "preuve_b": "<extrait EXACT de la clause B>",
  "relation_portees": "IDENTIQUE|INCLUSION|DISJOINTE|INDETERMINEE",
  "clause_fautive": "A | B | AUCUNE",
  "explication": "<2 phrases maximum>",
  "confiance": 0.0
}
```

**Cinq garde-fous — c'est ici que se joue la crédibilité du système :**

1. **Filtre contraint** *(repris de RnR+CF)* — `preuve_a` et `preuve_b` doivent être des sous-chaînes littérales des clauses. Vérification programmatique après l'appel : si l'extrait n'existe pas, **le verdict est annulé** et la paire part en abstention. Un LLM qui invente sa preuve ne peut pas polluer le rapport.
2. **Anti-biais de position** — ordre (A,B) puis (B,A) sur les cas de gravité maximale ; verdicts divergents → abstention.
3. **Auto-cohérence bornée** — 3 échantillons à `T = 0,2` sur la zone grise, vote majoritaire 2/3 minimum.
4. **Abstention légitime** — `INDECIDABLE` alimente une file de revue humaine. Un système d'audit qui abstient 8 % est infiniment plus utile qu'un système qui tranche à tort 8 %.
5. **Plafond de budget** — `max_appels = 0,1 × nb_candidats`. Atteint → paires marquées `NON_VERIFIEE_BUDGET`, jamais silencieusement rejetées.

> **Une honnêteté nécessaire sur Mistral 7B Q4.** C'est un bon *extracteur contraint* et un *filtre de rappel* correct ; c'est un juge médiocre sur des contradictions subtiles en français normatif. L'architecture en tient compte structurellement : jamais seul décisionnaire d'un verdict grave, toujours sur des paires pré-qualifiées et enrichies du sous-graphe, abstention encouragée. Si le profil hybride est autorisé, le jugement final est délégué à un modèle plus fort via API gratuite — **c'est la recommandation par défaut**, le local restant le mode de repli pour les documents confidentiels.

---

## 8. L5 — Consolidation, arbitrage, propagation d'impact

### 8.1 Écriture des verdicts et création des constatations

```cypher
// 1. Verdict au niveau de la paire
MATCH (a:Clause {clause_id:$a}), (b:Clause {clause_id:$b})
MERGE (a)-[i:INCOHERENT_AVEC]->(b)
SET i += {type:$type, score:$score, detecteur:$detecteur,
          preuve_a:$preuve_a, preuve_b:$preuve_b, run_id:$run_id};

// 2. Consolidation en Constatation (une par problème de fond)
MERGE (f:Constatation {constatation_id: $cid})
SET f += {type:$type, gravite:$gravite, criticite:$criticite,
          explication:$expl, statut:'A_VALIDER', nb_occurrences:$n,
          detecteurs:$detecteurs, hypotheses:$alias, run_id:$run_id}
WITH f
MATCH (c:Clause) WHERE c.clause_id IN $clauses
MERGE (f)-[:IMPLIQUE {role: CASE WHEN c.doc_id = $doc_source
                                 THEN 'SOURCE' ELSE 'CIBLE' END}]->(c);
```

`statut` ∈ `A_VALIDER | CONFIRMEE | REJETEE_UTILISATEUR | RESOLUE`. **Les rejets utilisateurs constituent le jeu de calibration du tour suivant : le système apprend sans réentraîner un modèle.**

### 8.2 Déduplication et regroupement

Une même divergence de fond se manifeste sur plusieurs paires : la valeur « 3 mois » apparaît dans 4 clauses de D1 et « 6 mois » dans 3 clauses de D2 → 12 paires signalées pour **un seul problème**. On regroupe par `(type, clé de comparaison, valeurs en conflit)` en une **constatation unique** portant N occurrences. Sans cette étape, le rapport devient illisible et perd la confiance de l'auditeur.

### 8.3 Criticité et arbitrage hiérarchique

```
criticite = w_type × w_gravite × w_confiance × w_portee × w_hierarchie ⭐

w_type       hiérarchisation issue de la taxonomie (livrable 1)
w_gravite    écart relatif pour les valeurs ; force du conflit déontique sinon
w_confiance  score du détecteur × confiance_extraction des deux clauses
w_portee     UNIVERSEL > EXISTENTIEL ; périmètre site > atelier
w_hierarchie ⭐  ×2,0 si l'une des clauses contredit une EXIGENCE EXTERNE
                ×1,5 si inversion hiérarchique (A9)
                ×1,0 sinon
```

**L'arbitrage.** Grâce à `niveau_hierarchique` et `DECLINE`, chaque constatation porte une **clause fautive désignée** : celle du document de niveau inférieur si elle est plus permissive, celle qui contredit l'exigence externe sinon. Si les deux documents sont de même niveau, la constatation est marquée `ARBITRAGE_REQUIS` — ce qui est en soi une information utile pour le pilote du système documentaire.

### 8.4 Propagation d'impact — la réponse directe à la problématique du sujet

```cypher
MATCH (c:Clause {clause_id:$c})
CALL {
  WITH c
  MATCH (c)-[:PAIRE_CANDIDATE|INCOHERENT_AVEC|SPECIALISE]-(v:Clause)
  RETURN v, 0 AS priorite                       // liens déjà connus : à revoir d'abord
UNION
  WITH c
  MATCH (v:Clause) WHERE v.cle_comparaison = c.cle_comparaison AND v <> c
  RETURN v, 0 AS priorite                       // même clé de comparaison
UNION
  WITH c
  MATCH (c)-[:RENVOIE_A|MENTIONNE|IMPOSE_A|SOUS_CONDITION|MAITRISE|ALIAS_DE*1..3]-(v:Clause)
  RETURN v, 1 AS priorite                       // voisinage structurel et conceptuel
UNION
  WITH c
  MATCH (c)<-[:CONTIENT*1..3]-(:Document)<-[:DECLINE|ANNULE_ET_REMPLACE*1..2]-(:Document)
        -[:CONTIENT*1..3]->(v:Clause)
  RETURN v, 2 AS priorite                       // ⭐ documents dérivés dans la pyramide
}
RETURN DISTINCT v.clause_id, v.doc_id, min(priorite) AS priorite
ORDER BY priorite
```

Le quatrième bloc est nouveau en v2 : **modifier une politique impacte toutes les procédures qui la déclinent**, même sans partage lexical direct. C'est précisément ce qu'un responsable QSE veut savoir avant de valider une révision.

**Le mode incrémental en découle mécaniquement :**

```
document modifié → recalcul des hash → clauses changées (typiquement 3 à 15)
   → réextraction de ces clauses uniquement (cache par hash)
   → rayon d'impact (typiquement 20 à 80 clauses)
   → ciblage restreint à ce sous-ensemble
   → cascade sur ~50 à 200 paires au lieu de 1 200
   → alias et relations de conditions déjà en cache : 0 appel LLM dans la plupart des cas
```

**La deuxième exécution coûte 20 à 50 fois moins cher que la première.** C'est ce qui distingue une architecture d'un script d'analyse.

---

## 9. L6 — Restitution

Trois sorties, une seule source de vérité (le graphe) :

1. **`rapport.json`** — machine-lisible : constatations, occurrences, preuves, offsets, scores, chemin de détection. Artefact d'évaluation.
2. **`rapport.html`** — audit-lisible : constatations triées par criticité, extraits surlignés en regard, clause fautive désignée, badges de détecteur, et quatre rubriques obligatoires :
   - *Hypothèses d'alignement* — les alias et relations de conditions utilisés, avec méthode et score, révisables ;
   - *Vérifié et déclaré cohérent* — notamment les spécialisations, pour montrer ce que le système a écarté et pourquoi ;
   - *Dérogations en vigueur* — avec justification, approbateur, échéance ;
   - *Zones non couvertes* — troncatures de budget, abstentions, extractions incertaines.
3. **Exploration du graphe** — Neo4j Browser / Bloom : requête d'une clause, visualisation de son voisinage, de ses conflits et de sa position dans la pyramide documentaire.

Chaque constatation porte obligatoirement **les deux extraits exacts, le détecteur, et le chemin de graphe qui a fait émerger la paire** (invariant I3).

---

## 10. Modèle de coût

### 10.1 Formule

```
Appels_LLM  =  ⌈α·n/8⌉        autonomisation           (α ≈ 0,20 des clauses)
            +  ⌈β·n/8⌉        extraction               (β ≈ 0,40 des clauses)
            +  γ·|Concepts|   arbitrage d'alias        (γ ≈ 0,05)
            +  ε·|Conditions²| arbitrage de conditions ⭐ (ε ≈ 0,04, payé une fois)
            +  δ·|Candidats|  jugement final           (δ ≈ 0,08, ×3 sur zone grise)

Inférences_NLI = 2 × |Candidats| × 0,60
Encodages      = n + |Concepts| + |Conditions|
|Candidats|    ≈ 4 × max(n₁, n₂)
```

### 10.2 Cas de référence : 2 documents × 300 clauses

| Poste | Volume | Profil A (GPU 8 Go) | Profil B (hybride) |
|---|---|---|---|
| Segmentation + règles | 600 clauses | 8 s | 8 s |
| Autonomisation | 15 appels | 65 s | 20 s |
| Extraction LLM | 30 appels | 130 s | 35 s |
| Embeddings (bge-m3) | ~1 500 vecteurs | 27 s | 27 s |
| Arbitrage d'alias | ~20 appels | 85 s | 25 s |
| ⭐ Arbitrage de conditions | ~12 appels *(payés une fois)* | 50 s | 15 s |
| Graphe Neo4j | ~5 400 nœuds / 21 000 arêtes | 15 s | 15 s |
| Ciblage L3 (5 Cypher + filtres) | 90 000 → 1 200 | 6 s | 6 s |
| Cascade A (9 détecteurs) | 1 200 paires | < 1 s | < 1 s |
| Cascade B (NLI) | ~1 440 inférences | 36 s | 36 s |
| Cascade C (LLM) | ~120 appels | 520 s | 130 s |
| **Total** | **~197 appels LLM** | **≈ 16 min** | **≈ 5 min** |
| **Coût monétaire** | | **0 €** | **0 €** (≈ 13 % du quota Gemini/jour) |

Ré-exécution après modification d'un document : **20 à 60 s**, 0 à 5 appels LLM.

### 10.3 Comparaison avec les alternatives

| Stratégie | Appels LLM | Tokens | Faisable en local (7B) ? | Localise ? |
|---|---|---|---|---|
| Pairwise LLM naïf | 90 000 | ~45 M | non | oui |
| Pairwise NLI naïf | 0 | 0 | oui, ~75 min **et milliers de faux positifs** | oui |
| RnR+CF sur documents concaténés | ~5 | ~150 k | **non** (30 k de contexte requis) | grossièrement |
| GraphCheck | 1 | ~15 k | non (GNN à entraîner) | non |
| **COHERA** | ~197 | ~270 k | **oui** | **oui, avec preuve** |

> **À noter en toute rigueur :** sur *deux petits documents*, RnR+CF consomme moins de tokens. Son avantage disparaît à l'échelle, pour trois raisons : (1) il exige un modèle à long contexte, inutilisable avec un 7B local, quand COHERA n'émet que des appels courts ; (2) sur `N` documents il faut `N(N−1)/2` passes de contexte complet, quand COHERA construit **un seul graphe** ; (3) il ne produit ni localisation fine, ni traçabilité, ni mode incrémental. **Le choix n'est pas « moins de tokens », c'est « des tokens dépensés là où ils décident ».**

---

## 11. Protocole d'évaluation et preuve de concept (semaine 7)

### 11.1 Ce que le PoC doit démontrer

Le mécanisme central de cette architecture est le **ciblage par graphe**. La PoC démontre, dans un notebook :

1. la construction du graphe à partir de 2–3 documents `.txt` réels ;
2. le **pont inter-documents** (alias) et son effet mesuré sur le rappel ;
3. l'**algèbre des conditions** et son effet sur la précision ;
4. la génération des paires candidates et le facteur de réduction ;
5. la cascade A + B complète, C sur un échantillon ;
6. la **propagation d'impact** après modification d'une clause.

### 11.2 Corpus

| Jeu | Composition | Usage |
|---|---|---|
| **Dev** | 4 documents, ~40 incohérences **injectées** (8 transformations de la taxonomie) | calibration des seuils, poids RRF, top-k |
| **Test** | 3 documents, ~15 incohérences **réelles** repérées manuellement, jamais vues pendant le réglage | mesure finale honnête |
| **Négatif** | 2 documents cohérents entre eux + 1 paire version courante / version abrogée + 1 dérogation déclarée | mesure du taux de faux positifs, validation des filtres d'éligibilité |

Le jeu négatif est aussi important que les autres : c'est lui qui révèle les alias erronés, les seuils laxistes et les filtres d'éligibilité mal câblés.

### 11.3 Métriques

| Métrique | Définition | Cible |
|---|---|---|
| **Rappel du ciblage** ★ | part des paires vraies présentes dans les candidats | **≥ 0,95** |
| Facteur de réduction | `1 − |candidats| / (n₁·n₂)` | ≥ 0,97 |
| Précision / Rappel / F1 | **par type de la taxonomie**, pas seulement en global | rapportés par type |
| Taux d'abstention | part des paires `INDECIDABLE` | ≤ 0,15 |
| Faux positifs (jeu négatif) | constatations sur documents cohérents | ≤ 2 par paire de documents |
| Appels LLM / paire de documents | budget effectif | ≤ 220 |
| Durée totale | de bout en bout | ≤ 20 min (profil A) |

★ **La métrique décisive.** Toute paire perdue en L3 est définitivement perdue.

### 11.4 Ablations à produire

| Ablation | Question à laquelle elle répond |
|---|---|
| Sans canal conceptuel (vectoriel seul) | Le graphe apporte-t-il ce qu'un index vectoriel ne donne pas ? |
| Sans pont inter-documents | Quelle part des incohérences inter-documents est perdue faute d'alignement ? *(hypothèse : la majorité)* |
| ⭐ Sans canal 5 (dimension seule) | Combien de cas à vocabulaire disjoint sont récupérés ? |
| ⭐ Sans algèbre des conditions | Combien de faux positifs par spécialisation ? |
| ⭐ Sans filtres d'éligibilité | Combien de faux positifs par version abrogée / dérogation ? |
| Sans étage A | Combien coûte le fait de ne pas exploiter les frames ? |
| Sans étage C | Le système est-il utilisable en 100 % symbolique + NLI ? |
| Mistral 7B local vs API gratuite en étage C | Le profil local suffit-il, et à quel prix en précision ? |
| top-k ∈ {4, 8, 16} | Où est le rendement décroissant du ciblage ? |

### 11.5 Ce que le PoC ne prétend pas démontrer

À écrire explicitement dans le rapport : corpus de très petite taille ; incohérences majoritairement injectées sur le jeu de développement ; seuils calibrés sur un domaine unique ; segmentation adaptée à des `.txt` de structure raisonnable. Les chiffres sont des **indications de faisabilité**, pas des performances généralisables.

---

## 12. Stack technique

| Couche | Choix | Justification |
|---|---|---|
| Langage | Python 3.11 | écosystème NLP, compétence visée par le sujet |
| Segmentation / NLP | **spaCy** `fr_core_news_lg` | phrases, POS, dépendances, lemmes — local, gratuit |
| NER | `Jean-Baptiste/camembert-ner` + gazetteer QHSE | rôles, organisations |
| Embeddings | **BAAI/bge-m3** (1024 d, MIT) · alternative `OrdalieTech/Solon-embeddings-large` | multilingue solide en FR, 8 192 tokens, 100 % local ; choix final par mesure |
| NLI | **`cmarkea/distilcamembert-base-nli`** · replis `camembert-base-xnli`, `mDeBERTa-v3-base-mnli-xnli` | ~2× plus rapide à qualité proche ; aucun entraînement |
| Graphe | **Neo4j Community 2025.x/2026.x** + driver Python `neo4j` | Cypher expressif, index vectoriel et plein texte natifs, sous-labels, gratuit |
| Algorithmes de graphe | Neo4j **GDS** ou **NetworkX** | composantes connexes, union-find pour les alias, centralité |
| LLM local | **LM Studio + Mistral 7B Instruct Q4_K_M** | endpoint OpenAI-compatible, sorties JSON contraintes |
| LLM distant (profil B) | Gemini 2.5 Flash · Groq (Llama 3.3 70B) · OpenRouter `:free` | quotas gratuits, basculement automatique sur 429/404 |
| Validation de schéma | `pydantic` v2 | contrat des Clause Frames, boucle de réparation |
| Orchestration | scripts + `typer` ; notebook pour la PoC | le sujet ne demande pas un produit |
| Restitution | `jinja2` (HTML) + Neo4j Browser/Bloom | démonstration en soutenance |

**LM Studio (profil A).** Serveur local `http://localhost:1234/v1`, contexte 8 192, `temperature` 0,1 (extraction) / 0,2 (jugement), `response_format` en JSON Schema, `n_gpu_layers` au maximum — principal levier de vitesse (×3 à ×4 vs CPU).

**Arborescence du dépôt :**

```
cohera/
├─ config/        registre_grandeurs.yaml · lexique_qhse.yaml · gazetteer_acteurs.yaml
│                 registre_normes.yaml · hierarchie_documents.yaml ⭐
├─ ingestion/     normalisation · structure · listes · tableaux ⭐ · phrases · autonomisation
├─ extraction/    regles/{deontique,grandeurs,conditions,references,raci,validite}.py
│                 llm_client.py · frames.py
├─ graphe/        schema.cypher · chargeur.py · alias.py · conditions.py ⭐
│                 cycle_de_vie.py ⭐ · requetes.py
├─ ciblage/       eligibilite.py ⭐ · canaux/{structurel,cle,conceptuel,vectoriel,dimension}.py
│                 fusion_rrf.py
├─ detection/     symbolique/{a1…a9}.py · portees.py ⭐ · nli.py · juge_llm.py · cascade.py
├─ consolidation/ constatations.py ⭐ · criticite.py · impact.py
├─ evaluation/    injecteur_taxonomie.py · metriques.py · ablations.py
├─ restitution/   rapport_json.py · rapport_html.py
├─ corpus/        dev/ · test/ · negatif/ · annotations.jsonl
└─ notebooks/     poc_semaine7.ipynb
```

---

## 13. Risques et parades

| # | Risque | Impact | Parade intégrée |
|---|---|---|---|
| R1 | **Alias erronés** entre concepts | faux positifs en cascade — risque n°1 | seuils élevés, méthode et score tracés, arbitrage LLM en zone grise, alias exposés et révisables, jamais suffisants seuls pour un verdict ferme |
| R2 | **Mistral 7B Q4 trop faible** en extraction FR | frames bruitées | règles d'abord, champs pré-remplis non modifiables, JSON Schema contraint, `confiance_extraction` propagée, exclusion des verdicts fermes, profil B en repli |
| R3 | **`.txt` sans structure** | segmentation erronée | heuristiques en cascade + repli plat, recomposition des listes, détection de blocs tabulaires, contrôle qualité manuel en S1–S2 |
| R4 | **Rappel du ciblage insuffisant** | incohérences invisibles définitivement | 5 canaux redondants dont deux indépendants du vocabulaire (4 et 5) ; le rappel est la métrique pilote |
| R5 | **Portées mal comparées** | faux positifs très visibles | algèbre des conditions matérialisée dans le graphe, règle à 4 cas avec monotonie par rôle, escalade LLM sur question fermée |
| R6 | **NLI hors domaine** | seuils instables | seuils calibrés sur le corpus, NLI en arbitre intermédiaire jamais juge final |
| R7 | **Quotas gratuits volatils** | pipeline bloqué | `LLMClient` unique, liste ordonnée de fournisseurs, basculement automatique, repli local |
| R8 | **Explosion du graphe** | requêtes lentes | IDF sur les concepts, plafonds top-k, index sur toutes les clés de filtrage, budget journalisé |
| R9 | **Confidentialité** des documents QHSE | blocage juridique | profil A 100 % local sans dégradation fonctionnelle ; les quotas gratuits impliquent en général l'usage des prompts par le fournisseur — à écrire noir sur blanc |
| R10 ⭐ | **Hiérarchie documentaire mal renseignée** | arbitrage faux, criticité fausse | déduction par code documentaire + fichier de configuration relu par le tuteur ; en cas de doute, `ARBITRAGE_REQUIS` plutôt qu'une désignation erronée |
| R11 ⭐ | **Dérogations non détectées** | faux positifs sur des écarts approuvés | marqueurs `par dérogation à`, `nonobstant`, `sauf disposition contraire` ; toute dérogation détectée est listée dans le rapport, jamais silencieusement absorbée |

---

## 14. Alternatives écartées

| Alternative | Pourquoi elle séduit | Pourquoi elle est écartée |
|---|---|---|
| **RAG vectoriel pur** | simple, rapide, une dépendance | la similarité mesure la *proximité*, pas la *contradiction*. Deux clauses contradictoires bien rédigées sont très similaires, deux clauses cohérentes aussi. Aucun routage vers le bon détecteur, aucune traçabilité, aucun incrémental. |
| **Ontologie OWL + raisonneur** | rigueur formelle, verdicts explicables | coût de mise en œuvre « très élevé » : modélisation + expertise OWL hors d'atteinte en 8 semaines, et aveugle hors du périmètre modélisé. La v2 en garde l'essentiel (modèle déontique, algèbre de portées) sous forme de nœuds Neo4j. |
| **Chaîne CNL → SMT (Z3)** | verdicts certains, exécution gratuite | **65 % des traductions CNL restent manuelles**. Le goulot est la formalisation, pas le raisonnement. COHERA en garde la table de conflits déontiques. |
| **GraphCheck (GNN)** | bat les méthodes pairwise pour une fraction du coût | GNN à entraîner sur 14 k exemples avec 4×A100. Son idée forte est reprise en prompting conditionné par le sous-graphe. |
| **Classifieur supervisé dédié** | performances potentiellement élevées | aucun corpus annoté QHSE français n'existe ; l'annoter dépasse le stage ; surapprentissage garanti. |
| **RnR+CF sur documents concaténés** | très simple à implémenter | modèle à long contexte requis (incompatible 7B local), pas de localisation fine, `O(N²)` passes, aucun incrémental. |
| **Graphe unique « tout LLM »** | code minimal | coût d'extraction ×2,5 et frames non fiables avec un 7B Q4 ; perte de l'invariant I2. |

---

## 15. Mise en correspondance avec les livrables du sujet

| Semaines | Attendu | Ce que produit cette architecture |
|---|---|---|
| **S1–S2** | taxonomie + mini-corpus annoté | §2 : taxonomie opérationnalisée (type → détecteur → priorité), enrichie de 3 types QHSE ; injecteur automatique ; jeux dev / test / négatif |
| **S3–S4** | état de l'art + benchmark | §1 : matrice « retenu / écarté et pourquoi » — la valeur du benchmark est la décision qu'il documente |
| **S5–S6** | architecture, grille de critères, coût | §3–§9 : pipeline `extraction → graphe → détection`, granularité des nœuds, types d'arêtes, §10 coût par document, §14 alternatives écartées |
| **S7** | preuve de concept ciblée | §11 : notebook — graphe, pont inter-documents, algèbre des conditions, ciblage, cascade, propagation d'impact, ablations |
| **S8** | rapport + cahier de spécifications | §13 risques, §16 suite |

---

## 16. Ce que le stage n°2 doit reprendre

1. **Cohérence intra-document** — hors périmètre ici, mais l'architecture la supporte sans modification : retirer la contrainte `a.doc_id <> b.doc_id` des cinq canaux. Décision de périmètre, pas limite technique.
2. **Autres formats** (Word, PDF) — seule la couche L0 change, et elle y gagne l'information structurelle (styles de titres, **vrais tableaux**) que le `.txt` a perdue.
3. **Évaluation quantitative sur corpus étendu** — précision/rappel par type sur plusieurs dizaines de documents annotés par des experts QHSE.
4. **Apprentissage des seuils** à partir des `REJETEE_UTILISATEUR` — calibrage supervisé léger, sans réentraînement.
5. **Extraction par LLM fine-tuné (LoRA)** sur les frames validées du stage n°1 — meilleure piste d'amélioration du rappel, l'extraction étant le plafond de performance de tout l'édifice.
6. **Interface de revue** : validation/rejet des constatations, édition des alias et des relations de conditions, ré-exécution incrémentale.
7. **Passage à l'échelle N documents** : le graphe est déjà multi-documents ; à valider sur 50–100 documents (partitionnement du ciblage, cache d'embeddings, GDS pour le clustering de concepts).
8. ⭐ **Ontologie QHSE légère** : les sous-labels de `Concept` (`:Risque`, `:Competence`, `:Substance`…) sont le socle d'une taxonomie métier qui pourrait s'aligner sur une nomenclature existante (INRS, ISO 45001 §6.1).

---

## Annexe A — Journal des changements v1 → v2

| Bloc | Changement | Motif |
|---|---|---|
| Invariants | ajout de **I4** « le corpus se déclare lui-même » | fondement des filtres d'éligibilité |
| Taxonomie | +3 types QHSE : Temporel, Dérogation, Hiérarchique | absents des taxonomies génériques, majoritaires en audit réel |
| L0 | détection des **blocs tabulaires** | matrices RACI et tableaux de périodicité |
| L1 | frame enrichie : `conditions` structurées, `perimetre`, `validite`, `derogation`, `raci`, `risques_maitrises`, `type_enonce` | alimente les nouveaux nœuds et détecteurs |
| L1 | **registre des grandeurs avec monotonie** | distingue spécialisation et contradiction |
| **L2** | `Condition` réifiée + algèbre `RECOUVRE`/`INCLUS_DANS`/`DISJOINT_DE` | M1 — calcul mis en cache, auditable |
| **L2** | cycle de vie : `ANNULE_ET_REMPLACE`, `DECLINE`, `DEROGE_A`, `REMPLACE_CLAUSE` | M2 — supprime les faux positifs de version et de dérogation |
| **L2** | `niveau_hierarchique` + pyramide documentaire | M3 — permet de désigner la clause fautive |
| **L2** | validité temporelle sur `Clause` et `Document` | M4 |
| **L2** | `ExigenceExterne` + `REMPLACE` en arête | M5 — la réglementation se cite à l'article |
| **L2** | `Constatation`, `Anomalie`, `IMPLIQUE`, `SIGNALE`, `SPECIALISE`, `CONCERNE` | M6 — la démo utilisait des nœuds absents du schéma |
| **L2** | sous-labels de `Concept` (`:Acteur`, `:Risque`, `:Perimetre`, …) | vocabulaire QHSE typé sans dupliquer la machinerie d'alias |
| **L2** | `IMPOSE_A {raci}`, `MAITRISE`, `EXIGE_COMPETENCE`, `S_APPLIQUE_A` | A4 invoquait des arêtes inexistantes en v1 |
| L3 | **filtres d'éligibilité** F1–F3 | invariant I4 |
| L3 | **canal 5 « dimension seule »** | correctif issu de la démo : rappel de ciblage 0,83 → 1,00 |
| L4 | A1 : **écart de force déontique** | correctif issu de la démo : obligation vs recommandation |
| L4 | test de portées : **règle à 4 cas avec monotonie** | correctif issu de la démo : faux positif de spécialisation |
| L4 | nouveaux détecteurs **A7, A8, A9** | types QHSE ajoutés |
| L5 | `Constatation` + **arbitrage hiérarchique** + propagation via `DECLINE` | désigner la clause fautive, propager dans la pyramide |
| Risques | +R10 (hiérarchie mal renseignée), +R11 (dérogations non détectées) | corollaires des ajouts |

---

## Annexe B — Les six décisions structurantes

1. **Le graphe sert au ciblage, pas au stockage.** C'est ce qui transforme un problème quadratique en un problème de requête.
2. **L'extraction structurée (Clause Frame) est l'investissement central.** Huit des onze types de la taxonomie deviennent détectables sans modèle. Le coût déplacé vers l'extraction est récupéré au centuple en vérification.
3. **Le pont inter-documents est la pièce sans laquelle rien ne fonctionne** — et simultanément le premier facteur de faux positifs. Il est donc tracé, scoré, exposé et révisable.
4. ⭐ **Un document QHSE n'existe pas seul : il vit dans un système documentaire.** Abrogations, dérogations, déclinaisons, périmètres et validités doivent être dans le graphe, sans quoi le système signale comme incohérences des situations que le corpus a lui-même déjà résolues.
5. **La cascade impose au LLM une place étroite** : jamais de balayage, jamais de verdict sans preuve littérale vérifiée, abstention légitime, budget plafonné. C'est ce qui rend un Mistral 7B Q4 exploitable.
6. **Le rappel du ciblage est la métrique pilote.** Ce qui est perdu en L3 est perdu définitivement ; la réduction de coût ne s'optimise qu'à rappel constant.

---

## Annexe C — Ordre d'implémentation recommandé

| Sprint | Contenu | Pourquoi cet ordre |
|---|---|---|
| **S1** | L0 complet + L1 règles seules + `Document`/`Section`/`Clause`/`Quantite` + canal 2 + détecteurs A2, A5 | Produit des constatations **réelles dès la première semaine**, sans aucun LLM. Valide la segmentation et le registre des grandeurs sur documents réels. |
| **S2** | `Concept` + sous-labels + `ALIAS_DE` + canaux 3 et 4 + embeddings | Débloque l'inter-documents. À mesurer immédiatement : combien d'incohérences apparaissent que S1 ne voyait pas. |
| **S3** | `Condition` + algèbre des portées + test à 4 cas + A1, A3, A9 | Là où se gagne la **précision**. À mesurer : combien de faux positifs S2 produisait. |
| **S4** | Cycle de vie (`ANNULE_ET_REMPLACE`, `DECLINE`, `DEROGE_A`) + filtres d'éligibilité + A7, A8 | Indispensable dès qu'on ingère un corpus réel avec plusieurs versions. |
| **S5** | LLM : extraction complémentaire, arbitrage d'alias et de conditions, étage C | Le LLM arrive **en dernier**, sur une chaîne déjà mesurée : on sait exactement ce qu'il apporte. |
| **S6** | `Constatation`, criticité, arbitrage, rapport HTML, propagation d'impact | Restitution et démonstration. |

> **La logique de cet ordre :** chaque sprint est mesurable seul et améliore une métrique précise (rappel, puis précision, puis robustesse). Si le temps manque, on s'arrête après S4 avec un système **entièrement symbolique, sans aucun LLM**, qui détecte déjà huit des onze types — et le rapport peut le dire, chiffres à l'appui.
