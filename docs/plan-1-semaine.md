# COHERA — Plan d'implémentation en 7 jours

**Contrainte : 1 semaine.** Ce plan ne construit pas l'architecture v2 complète. Il construit le **noyau démontrable** : celui qui prouve que le graphe de dépendances réduit le coût de vérification, et qui produit des chiffres exploitables en soutenance.

---

## 1. Périmètre : ce qu'on garde, ce qu'on coupe

| | Gardé (7 jours) | Coupé, et pourquoi |
|---|---|---|
| **Nœuds** | `Document`, `Section`, `Clause`, `Concept`, `Quantite`, `Condition` | `ExigenceExterne`, `Constatation`, `Anomalie`, sous-labels — remplaçables par des propriétés ou du JSON |
| **Arêtes** | `CONTIENT`, `MENTIONNE`, `PORTE`, `SOUS_CONDITION`, `RENVOIE_A`, `CITE_NORME`, `ALIAS_DE`, `RECOUVRE/INCLUS_DANS/DISJOINT_DE`, `PAIRE_CANDIDATE`, `INCOHERENT_AVEC`, `SPECIALISE` | tout le bloc **cycle de vie** (`ANNULE_ET_REMPLACE`, `DECLINE`, `DEROGE_A`), `IMPOSE_A{raci}`, `MAITRISE` |
| **Canaux** | 2 (clé), 3 (conceptuel), 4 (vectoriel), 5 (dimension) | canal 1 structurel — replié dans le détecteur A5 |
| **Détecteurs** | **A1** (déontique + écart de force), **A2** (valeurs + portées), **A5** (références/normes) | A3, A4, A6, A7, A8, A9 |
| **LLM** | arbitrage des alias en zone grise + juge sur les portées indéterminées | extraction complémentaire par LLM (règles seules) |
| **Sprint 4 entier** | — | **système documentaire** : inutile sur un corpus figé de PoC |

**Ce que couvre encore ce noyau : 5 types de la taxonomie sur 11** (Negation, Numeric, Perspective, Factual, et Causal partiellement). C'est suffisant pour une preuve de concept, et le rapport doit le dire explicitement — avec le reste en perspective.

> **À écrire dans le rapport :** *« La PoC valide le mécanisme central (ciblage par graphe et cascade de vérification) sur un corpus figé. La couche système documentaire — versions, dérogations, hiérarchie — est spécifiée mais non implémentée : elle conditionne le passage à un corpus réel multi-versions, et constitue le premier chantier du stage n°2. »*

---

## 2. Le plan, jour par jour

### J1 — Socle, corpus, segmentation

**Faire**
- venv + `neo4j`, `spacy` (`fr_core_news_lg`), `sentence-transformers`, `pydantic`, `pyyaml` ; Neo4j en Docker
- **Le corpus d'abord** : les 2 mini-documents de la démonstration dans `corpus/fixtures/` + `label.json` (19 incohérences dont 12 dans le périmètre 7 jours, 9 contre-exemples dont 7 dans le périmètre). *Une heure, et c'est ce qui rendra tout le reste mesurable.*
- Segmentation : normalisation → structure par numérotation → recomposition des listes (redistribuer le chapeau) → phrases spaCy → qualification (déontique OU grandeur OU référence OU verbe définitionnel)
- Autonomisation **par règle**, sans LLM : si la clause commence par un pronom, reprendre le sujet de la clause précédente

**✅ Terminé quand**
- `fixtures` produit **exactement 41 + 37 clauses** (cf. `nb_clauses_attendu` dans `corpus/fixtures/label.json`), et « Ce document est diffusé… » est rattachée en contexte
- Pour chaque clause : `texte_origine[debut:fin] == texte_source` (offsets alignés)
- `D1::S9::C02` « Il est archivé pendant 3 ans » est réécrite avec « registre de contrôle des EPI »

**⚠️** Perdre l'alignement des offsets pendant la normalisation. C'est irréparable en aval : toutes les preuves du rapport seront décalées.

---

### J2 — Extraction par règles

**Faire** — quatre extracteurs, dans cet ordre de priorité :
1. **Grandeurs** (le plus rentable) : délais, périodicités, durées de conservation, seuils ; normalisation en SI ; `registre_grandeurs.yaml` avec la **monotonie** par rôle
2. **Modalité / force / négation** : lexique déontique + présent prescriptif (sujet ∈ gazetteer)
3. **Références** : `§5.2`, `PR-QSE-04`, `ISO 45001:2018`, avec marquage `resolu = false`
4. **Conditions** : marqueurs typés (`en cas de`, `en zone`, `pour les`, `au-delà de`, `sauf`)

Deux fichiers YAML seulement : `registre_grandeurs.yaml` (10 rôles + monotonie) et `lexique_qhse.yaml` (~60 entrées : acronymes, synonymes, gazetteer d'acteurs fusionné dedans).

**✅ Terminé quand** — trois petits jeux de test annotés à la main :
- **≥ 35/40 grandeurs** correctes, et `trimestriel` = `tous les 3 mois` = `4 fois par an`
- **≥ 25/30 modalités**, dont « ne doit pas valider » ≠ « doit ne pas valider »
- `D1 §4.2 → § 6.3` marqué **non résolu**, et « tolérance de 4.3 % » ne produit **pas** de référence

**⚠️** Chaque grandeur doit porter une monotonie non nulle — c'est elle qui distinguera spécialisation et contradiction au J5.

---

### J3 — Graphe, concepts, alias

**Faire**
- `schema.cypher` (contraintes + index + index vectoriel 1024) ; chargement **idempotent** par `MERGE`
- Concepts : acteur (gazetteer), objet et action (syntaxe spaCy : sujet / verbe / objet direct). Pas de NER si le temps presse, le gazetteer suffit sur un corpus de PoC
- Embeddings `BAAI/bge-m3` sur clauses et concepts, **avec cache disque par hash**
- **Pont inter-documents** : identité normalisée → lexique → vectoriel (`cos ≥ 0,86` alias, `0,72–0,86` → `zone_grise.jsonl`) → union-find → canoniques
- Recalcul de `cle_comparaison` avec les canoniques

**✅ Terminé quand**
- Deux chargements successifs donnent le **même nombre de nœuds et d'arêtes**
- Les 4 alias attendus existent avec la bonne méthode : `fiche/fiches` (EXACT), `EPI/équipements de protection` (LEXIQUE), `Responsable QSE/Référent sécurité` (VECTEUR ~0,88), `contrôle/vérification` (VECTEUR ~0,91)
- **La liste noire tient** : `casque`≢`gants`, `anomalie`≢`écart`, `chef d'atelier`≢`hiérarchie`
- `zone_grise.jsonl` contient 2 paires

**⚠️** C'est la journée à risque. Un seul alias erroné rend comparables des dizaines de clauses sans rapport. **La liste noire du test compte autant que la liste blanche.**

---

### J4 — Ciblage 🎯 *(point de contrôle n°1)*

**Faire** — quatre requêtes Cypher, une par canal, plus la fusion :
- Canal 2 (clé de comparaison) · Canal 3 (2 sauts conceptuels, `idf > 1,5`, ≥ 2 concepts partagés) · Canal 4 (k-NN, seuil 0,70) · Canal 5 (même dimension + même rôle, top-3, **sans seuil**)
- Fusion RRF, filtre de comparabilité, `top-k = 8`
- Matérialisation des `PAIRE_CANDIDATE`
- **Mesure du rappel du ciblage** — la métrique pilote

**✅ Terminé quand**
- `81 → ~10 paires candidates` sur les fixtures
- **Rappel du ciblage = 7/7**, dont V7 (`24 heures` vs `dans la semaine`) trouvée **par le canal 5 et lui seul**
- Le contre-exemple N3 (phrases de cadrage) est rejeté par le filtre de comparabilité
- Une mini-ablation est produite : rappel **sans** le pont inter-documents → effondrement attendu

> 🚦 **Point de contrôle n°1.** Si le rappel du ciblage n'est pas à 7/7 en fin de J4, **ne pas continuer vers les détecteurs** : diagnostiquer dans l'ordre — alias manquant ? grandeur non extraite ? seuil vectoriel trop haut ? La cause est presque toujours en amont, dans l'extraction du J2.

---

### J5 — Conditions et détecteurs

**Faire**
- Nœuds `Condition` dédupliqués + relations `RECOUVRE` / `INCLUS_DANS` / `DISJOINT_DE` par **règles typées uniquement** (spatial, seuil, condition vide → inclusion) ; le reste part en file d'attente pour J6
- **Test de portées à 4 cas** avec lecture de la monotonie
- **A2** — divergence de valeurs · **A1** — déontique avec écart de force · **A5** — références et normes

**✅ Terminé quand**
- **`D1::C02 ↔ D2::C09` (48 h vs 24 h en cas d'incident grave) → `SPECIALISE`, pas une constatation**
- **Test inverse obligatoire** : en remplaçant artificiellement « 24 heures » par « 72 heures », le verdict devient **CONTRADICTION**. Sans ce test, tu ne sais pas si la monotonie est appliquée ou seulement l'inclusion.
- Sur fixtures : **V1, V3, V5, V6 détectées** · précision = 1,00 · **0 faux positif**
- Les 6 cas symboliques de l'algèbre des conditions passent (`zone A`/`zone B` → DISJOINT, `zone A`/`site` → INCLUS…)

---

### J6 — LLM 🎯 *(point de contrôle n°2)*

**Faire** — un seul client, deux usages :
- `LLMClient` : endpoint OpenAI-compatible, `response_format` JSON Schema, **cache par hash**, une tentative de réparation
- Usage 1 — **arbitrage des alias en zone grise** (2 appels sur fixtures) → débloque V4
- Usage 2 — **juge sur les portées indéterminées et la zone grise**, avec le sous-graphe injecté dans le prompt → débloque V2
- **Deux garde-fous seulement, mais non négociables** : le *filtre contraint* (preuve absente du texte → verdict annulé) et l'*abstention* (`INDECIDABLE` remonte dans le rapport)
- NLI (`cmarkea/distilcamembert-base-nli`) **si et seulement s'il reste du temps** — c'est un `pip install` et 30 lignes, mais ce n'est pas ce qui débloque des cas sur les fixtures

**✅ Terminé quand**
- Même prompt envoyé deux fois → **un seul appel réseau**
- Mock renvoyant une preuve inventée → **verdict annulé**, paire en abstention
- Sur fixtures : **6 constatations sur 7**, 0 faux positif, **≤ 15 appels LLM**

> 🚦 **Point de contrôle n°2.** Si J6 déborde, livrer le système **sans étage C** : 4 constatations sur 7, 0 faux positif, 0 appel LLM. C'est un résultat parfaitement défendable — il faut juste le présenter comme tel, avec l'ablation qui chiffre ce que le LLM aurait apporté.

---

### J7 — Restitution, mesures, démonstration

**Faire**
- `rapport.json` (contrat d'évaluation) + un HTML simple par template Jinja2, avec 3 rubriques : constatations triées par criticité, **hypothèses d'alignement** (les alias utilisés, révisables), **zones non couvertes**
- Regroupement des occurrences en constatations (un simple `groupby` en Python suffit, pas besoin du nœud `Constatation`)
- **Trois ablations**, pilotées par des drapeaux CLI : `--sans-alias`, `--sans-canal5`, `--sans-etage-c`
- **Scénario incrémental** : modifier `D1 §3.1` en « deux fois par an », relancer → 5 constatations, F2 résolue

**✅ Terminé quand**
- 100 % des preuves citées sont des **sous-chaînes littérales** du texte source (vérification programmatique)
- Le tableau des 3 ablations est rempli et chiffré
- Le scénario incrémental tourne en une commande
- **Test d'utilisabilité** : quelqu'un qui ne connaît pas le projet lit le rapport et sait, pour chaque ligne, quelles clauses sont en cause et pourquoi

---

## 3. Les cinq tests qui comptent plus que les autres

Si tu ne dois écrire que cinq tests, ce sont ceux-là :

| # | Test | Jour | Ce qu'il empêche |
|---|---|---|---|
| 1 | `texte_origine[debut:fin] == texte_source` | J1 | Toutes les preuves du rapport décalées, sans que rien ne le signale |
| 2 | Liste noire des alias | J3 | Des faux positifs en cascade sur des dizaines de clauses |
| 3 | Test inverse du recouvrement (72 h → contradiction) | J5 | Croire que la monotonie fonctionne alors que seule l'inclusion est appliquée |
| 4 | Preuve inventée → verdict annulé | J6 | Un LLM qui hallucine une citation pollue le rapport |
| 5 | Rappel du ciblage = 7/7 | J4 | Optimiser le coût en perdant silencieusement des incohérences |

---

## 4. Le tableau de bord

Une ligne par exécution dans `historique.csv`. **Cette table est une figure du rapport de stage** : elle raconte l'architecture mieux qu'un paragraphe.

| Jour | Rappel | Précision | FP | Appels LLM | Paires vérifiées |
|---|---|---|---|---|---|
| J4 | *ciblage 7/7* | — | — | 0 | 10 / 81 |
| J5 | 4/7 | 1,00 | 0 | 0 | 10 |
| J6 | 6/7 | 1,00 | 0 | ~14 | 10 |

---

## 5. Si tu prends du retard

Par ordre de sacrifice :

| Rang | Couper | Conséquence |
|---|---|---|
| 1 | Le HTML (garder le JSON) | Confort de lecture uniquement |
| 2 | Le NLI (étage B) | Sur les fixtures, il ne débloque aucun cas |
| 3 | L'étage C (juge LLM) | 4/7 au lieu de 6/7 — **acceptable si documenté** |
| 4 | Le détecteur A1 | Perte du type Perspective |
| — | **Jamais** : corpus annoté (J1), alias (J3), test de portées (J5), ablations (J7) | Sans eux, **tu ne peux rien affirmer** dans le rapport |

Les quatre intouchables sont ceux qui portent l'argumentation : le corpus parce que sans lui rien n'est mesurable, l'alignement parce que l'inter-documents n'existe pas sans lui, le test de portées parce que les faux positifs rendent le système inutilisable, et les ablations parce qu'elles prouvent que chaque brique sert à quelque chose.
