# COHERA — détection d'incohérences inter-documents QHSE

Pipeline Python qui ingère des fichiers `.txt` (procédures QHSE en français), construit un
graphe de dépendances dans Neo4j, cible les paires de clauses à vérifier, et détecte les
incohérences entre documents. PoC de stage, 7 jours.

## Invariants (ne jamais les enfreindre)

1. **Règles d'abord, LLM ensuite.** Un extracteur LLM ne remplit que les champs laissés `null`
   par les règles. La fusion se fait côté Python, jamais par consigne au modèle.
2. **Rien de cher avant le ciblage.** Aucun appel NLI ou LLM sur une paire qui n'est pas
   sortie du graphe comme `PAIRE_CANDIDATE`.
3. **Aucun verdict sans preuve littérale.** `preuve_a` et `preuve_b` doivent être des
   sous-chaînes exactes de `texte_source`, vérifiées en Python après l'appel.
4. **Le détecteur le moins cher traite le cas.** Une divergence de valeur est une comparaison
   d'entiers, pas un appel LLM.

## Où sont les choses

- Architecture complète : `docs/architecture.md` — lis **la section concernée**, pas le fichier
  entier. §5 modèle de graphe, §6 ciblage, §7 cascade de détection.
- Plan de la semaine et critères d'acceptation : `docs/plan-1-semaine.md`
- Corpus de test et vérité terrain : `corpus/fixtures/`

## Commandes

- `cohera doctor` — vérifie Neo4j, spaCy, embeddings, LLM
- `cohera run --corpus fixtures` — pipeline complet, écrit `rapport.json`
- `cohera evaluer --jeu fixtures` — compare `rapport.json` à `label.json`
- `pytest` — tests unitaires et d'intégration
- `docker compose up -d` — démarre Neo4j

## Règles non négociables

- **`corpus/fixtures/` est en lecture seule.** Ne jamais modifier `file-1.txt`, `file-2.txt`
  ni `label.json`, même pour faire passer un test. Si un test échoue, c'est le code ou le
  seuil qui est en cause. Si tu penses que la vérité terrain est fausse, **dis-le, ne la
  corrige pas.**
- **Aucune valeur métier en dur dans le code.** Seuils, lexiques, acronymes, rôles QHSE,
  normes, monotonies : tout va dans `config/*.yaml`. `grep -rn "ISO 45001\|responsable qse"
  cohera/ --include=*.py` doit ne rien retourner hors tests.
- **Neo4j : `MERGE`, jamais `CREATE`.** Le chargement doit être idempotent.
- **Les offsets pointent dans le texte d'origine**, pas dans le texte normalisé.
  `texte_origine[debut:fin] == texte_source` pour toute clause.
- **Un détecteur = un test positif ET un test négatif.** Jamais l'un sans l'autre.
- Ne jamais relâcher un seuil ou assouplir une assertion pour faire passer un test sans me
  le signaler explicitement dans ta réponse.

## Git

- **Jamais de ligne `Co-Authored-By: Claude` ni de mention de génération par IA dans les
  messages de commit.** Ni dans le corps, ni en trailer.

## Style

- Python 3.11, `pydantic` v2 pour tous les schémas de données, `typer` pour la CLI.
- Français pour les noms de domaine (`clause`, `modalite`, `portee`), anglais pour la
  plomberie technique.
- Fonctions courtes, testables isolément. Pas de classe quand une fonction suffit.

## Workflow

- Une session par journée du plan. Je lance `/clear` entre deux journées.
- En début de journée : plan mode, puis exécution.
- Écris les tests **avant** l'implémentation, à partir des critères d'acceptation du plan.
- Arrête-toi et signale-le si un critère chiffré n'est pas atteint. Ne continue pas la
  journée suivante avec un critère rouge.

## État du projet — fin J8 (2026-08-20)

Le pipeline est **complet de bout en bout, restitution comprise**, et la cascade a
désormais ses **trois** étages : L0 ingestion → L1 extraction → L2 graphe → L3 ciblage →
L4 cascade **A puis B puis C** → L5 consolidation → L6 restitution. Le plan de la semaine
était terminé au J7 ; le J8 ajoute l'étage B (NLI), qui était la dette n° 2 de
l'architecture.

| | Mesure (profil local) | Cible | |
|---|---|---|---|
| Tests | 806 + 2 xfail, 0 skip | — | ✅ |
| `cohera doctor` | 6 / 6 | — | ✅ |
| Clauses segmentées | 78 (41 + 37) | 78 | ✅ |
| **Preuves littérales** | **33 / 33 = 100 %** | 100 % | ✅ |
| Rappel du ciblage | 12 / 12 | 12 / 12 | ✅ |
| Facteur de réduction | 0,95 (1517 → 72) | ≥ 0,91 | ✅ |
| Dérogations en vigueur | N05 listée | listée | ✅ |
| Scénario incrémental | I02 → `RESOLUE`, 0 appel LLM | 1 commande | ✅ |
| Ablations | 3 branches chiffrées | tableau rempli | ✅ |
| **Étage B — paires soumises au juge** | **57 → 51** (−10,5 %) | gain chiffré | ✅ |
| Étage B — rappel et précision | inchangés (9/12, 3 FP) | ne pas baisser | ✅ |
| Paires candidates | 72 | 80 – 140 | 🔴 |
| Rappel (périmètre) | **9 / 12** | ≥ 10 / 12 | 🔴 |
| Faux positifs | **3** | 0 | 🔴 |

### Le profil de référence, et pourquoi

**`rapport.json` est produit par le profil local** (`saiga_mistral_7b`). Motif : F1 supérieur
sur les deux barèmes (0,75 et 0,78 contre 0,65 et 0,68), trois fois moins de constatations
fausses, et rien ne sort du réseau — ce qui compte pour des procédures QHSE internes. Le
profil distant est **conservé et présenté à côté**, dans `rapport_groq.json` et dans
l'en-tête du HTML : il atteint 10/12 en rappel, le seul critère dur qu'un profil fasse
passer, en payant 9 faux positifs. Il n'y a pas de gagnant, il y a un arbitrage documenté.

| | **A — local** (`saiga_mistral_7b`) | **B — distant** (`llama-3.3-70b`) |
|---|---|---|
| Paires soumises | 57 / 57 | 57 / 57 |
| **Réparations de format** | **41** | **0** |
| Constatations | 17 | 25 |
| Précision / rappel (périmètre) | **0,75** / 9 sur 12 | 0,53 / **10 sur 12** |
| Faux positifs | **3** | 9 |

### Les critères rouges, et ce qu'ils valent

1. **Faux positifs : 3, contre 0.** Les trois viennent de l'étage C : `D1 §5.3 ↔ D2 §5.1`,
   `D1 §5.2 ↔ D2 §8.1`, `D1 §6.3 ↔ D2 §4.2`. Décision actée au J6 et **maintenue au J7** :
   aucune règle ad hoc pour les faire disparaître. Le garde-fou des objets ne les sépare pas
   — mesuré, le premier partage 3 objets canoniques, plus qu'I11 et I03 qui en partagent 1 —
   et le transposer tuerait les vrais positifs. C'est une limite mesurée du jugement.
   ⭐ **L'étage A seul produit désormais 0 faux positif et une précision de 1,00** : le
   regroupement du J7 a supprimé le seul qui restait, et qui n'en était pas un.
2. **Rappel 9/12.** I03, I05 et I12 manquent ; les trois causes sont établies et mesurées
   (tableau ci-dessous).
3. **72 paires candidates au lieu de 80–140.** Critère du J4, inchangé et reconfirmé au J7 :
   aucun canal n'a été appauvri, c'est le corpus qui produit moins de bruit que l'estimation
   du plan. `xfail(strict=True)` dans `tests/test_ciblage.py`.
4. **Durée du scénario incrémental : 18 s, contre « < 5 s » annoncé dans la consigne.** Le
   critère du plan §J7 — « le scénario incrémental tourne en une commande » — est atteint, et
   les 0 appels LLM aussi. Les 18 s sont le coût du pipeline lui-même : resegmentation spaCy,
   réextraction, rechargement du graphe, reciblage, cascade, puis restauration du graphe de
   référence. Aucune de ces étapes n'est incrémentale — le J7 rend le *scénario* incrémental,
   pas le *pipeline*. Chiffre donné tel quel, non maquillé.
5. Rappels des journées précédentes, inchangés : les deux alias attendus « par vecteur »
   sont portés par le lexique (J3) ; `archiver ~ conserver` = 0,613, sous la bande.

### Incohérences non détectées, et cause de chacune

| | Cause, mesurée |
|---|---|
| **I03** | `archiver ~ conserver` = 0,613, sous le plancher de la zone grise (J3) : l'alias n'existe pas. Soumise au juge, qui a **inventé sa citation** — le filtre contraint a annulé le verdict (`PREUVE_INVENTEE`), sur les deux profils. Le garde-fou a travaillé : il a évité une fausse constatation, il n'a pas pu produire la vraie. |
| **I05** | Écart de force 1 (OBLIGATION contre RECOMMANDATION) : non ferme **par construction** (`ecart_conflit_fort: 2`). Jugée COHERENT en local, trouvée par le profil distant. |
| **I12** | Zéro objet canonique partagé — profil **identique à N08**, qui doit être rejeté. Le garde-fou de précision du J5 les traite donc pareil. Jugée COHERENT par les deux profils. |
| I07, I18 | Hors périmètre : A4 + CAP03 et A8 non implémentés. I07 est en outre écartée par la comparabilité. |

### Reprendre le travail — après le J8

```powershell
docker compose up -d                                    # Neo4j d'abord, tout en dépend
cohera doctor                                           # 6/6 attendu, NLI compris
pytest -q                                               # 806 passed, 2 xfailed, 0 skipped
cohera graphe charger --jeu fixtures                    # 505 nœuds / 848 arêtes (776 + 72 paires)
cohera detecter --jeu fixtures --llm local              # étage B : 57 -> 51 ; 0 appel réseau
cohera detecter --jeu fixtures --llm local --sans-etage-b --rapport rapport_sans_etage_b.json
cohera rapport --jeu fixtures --profils evaluation/profils.json
cohera evaluer --jeu fixtures                           # 9/12, 3 FP, ciblage 12/12
cohera ablation --jeu fixtures                          # les 3 branches du J7, étage A constant
cohera incrementer --jeu fixtures --llm local           # I02 -> RESOLUE, 0 appel
cohera historique --jeu fixtures --rapport "rapport_local.json=J7=local=0=16" `
                  --rapport "rapport_groq.json=J6=groq=43=420" `
                  --rapport "rapport_sans_etage_b.json=J8=local=0=17" `
                  --rapport "rapport.json=J8=local=0=24"
```

⚠️ **L'interpréteur du projet est Python 3.12**, pas celui du PATH. Sur cette machine :
`C:\Users\DELL\AppData\Local\Programs\Python\Python312\python.exe`. Le `python` du PATH est
un 3.14 sans `neo4j`, hors de la borne `requires-python = ">=3.11,<3.13"` du `pyproject.toml`.

**À vérifier en premier, dans cet ordre.** (a) `pytest -q` : 806 + 2 xfail, **0 skip** — un
test sauté n'est pas un test vert, et `test_cascade.py` se saute en silence si Neo4j est
éteint. (b) `git diff -- corpus/` doit être **vide** : la vérité terrain n'a jamais été
touchée et ne doit pas l'être. (c) Le cache `.cache/llm/` contient les réponses des deux
profils : `cohera detecter` rejoué doit faire **0 appel réseau**, en `--llm local` comme en
`--llm groq` (vérifié au J7 : 57/57 servis par le cache des deux côtés ; au J8 : 91 accès
servis, 0 réseau, sur les 51 paires restantes). Le signal d'alarme n'est pas « un appel a eu
lieu » mais **« le cache ne sert quasiment rien »** : un prompt modifié manquerait le cache
sur toutes les paires. C'est ce cas-là qui rendrait les mesures incomparables — et c'est
précisément pour cela que l'étage B du J8 **n'écrit rien dans le prompt de l'étage C**.

**Ce qui reste ouvert**, par ordre de valeur :

0. **Le NLI ne sert pas la précision, et c'est mesuré** (J8). Les 3 faux positifs de
   l'étage C ne sont pas séparables par lui : l'un est 2ᵉ de tout le corpus (0,910), les
   deux autres sont au milieu de la zone grise (0,48 / 0,47). La piste n° 1 reste donc
   l'auto-cohérence, ci-dessous.
1. **Auto-cohérence bornée** (garde-fou n°3, architecture.md §7.4) : 3 échantillons à
   T = 0,2, vote majoritaire 2/3. C'est la piste la plus prometteuse contre les 3 faux
   positifs de l'étage C, qui sont précisément des affirmations peu stables. Le plafond
   porté à 200 au J6 leur laisse la place.
2. **Anti-biais de position** (garde-fou n°2) : ordre (A,B) puis (B,A) sur les cas de
   gravité maximale, verdicts divergents → abstention.
3. **Détecteurs manquants** : A3 (contenu), A4 (RACI — débloque I07 avec CAP03), A6
   (terminologique, I19), A7 (temporel, I16), A8 (dérogations, I17 et I18), A9 (inversion
   hiérarchique — la donnée existe déjà, `consolidation/criticite.py` la calcule).
4. **`w_portee` dans la criticité** : la portée effective est calculée au J5 mais n'est pas
   reportée sur la constatation, donc le facteur vaut 1,0 pour tout le monde. Documenté dans
   `config/restitution.yaml` et **figé par un test** qui échouera si on la branche sans
   mettre la limite à jour.
5. **`file_attente_conditions.jsonl`** (244 paires) n'est toujours pas arbitré au LLM.

**Dettes connues, sans blocage** : `RENVOIE_A` n'est pas chargé dans le graphe (A5 source
depuis `Reference.resolu`, décision actée au J4) ; `file_attente_conditions.jsonl` (244
paires) n'est pas arbitré au LLM ; Gemini répond 404 sur `gemini-2.5-flash`. L'étage B
existe depuis le J8 mais **ne débloque aucun cas** — il ne fait que retirer 6 paires au
juge, ce que le plan §5 annonçait ; le tableau d'ablation du J7 tourne toujours à étage A
constant et n'est donc pas affecté.

---

## Journal

- **J0** (2026-08-10) — Fait : environnement vert (`cohera doctor` 5/5, 38/38 tests). Reste
  ouvert : pipeline (ingestion/extraction/ciblage/détection) à l'état de stubs — c'est J1.
- **J1** (2026-08-11) — Fait : L0 complet, 41+37 clauses, 0 offset désaligné, 157/157 tests.
  Reste ouvert : extraction par règles — c'est J2.
- **J2** (2026-08-11) — Fait : extraction par règles (5 extracteurs), 303/303 tests, seuils
  ≥35/40 et ≥25/30 dépassés. Reste ouvert : graphe, concepts, alias — c'est J3.
- **J3** (2026-08-11) — Fait : schéma + chargement idempotent (521 nœuds / 803 arêtes,
  rejoué à l'identique), 347 concepts, pont 3 niveaux (22 alias), liste noire tenue,
  450/450 tests + 1 xfail, 0 skip. **2 critères ROUGES** : (a) « Responsable QSE ~ Référent
  sécurité » et « contrôle ~ vérification » attendus en VECTEUR ~0,88/~0,91, mesurés
  0,546/0,624 (bge-m3) et 0,450/0,561 (Solon) — aucun seuil ne les sépare de la liste noire
  (`anomalie/écart` = 0,541), donc portés par le LEXIQUE, méthode enregistrée telle quelle ;
  (b) `zone_grise.jsonl` a bien 2 paires mais pas celles attendues (archiver/conserver
  = 0,613, sous le budget) — **I03 restera bloquée au J6**. Calibrage détaillé dans
  `config/lexique_qhse.yaml`. Reste ouvert : ciblage 5 canaux — c'est J4.
- **Avant J4** (2026-08-15) — Correction de la clé de comparaison de D1 §4.2 / D2 §4.2, qui
  divergeait sur **deux** positions et non une seule (le J3 n'avait signalé que la première,
  et sans test) : `''` vs `valider` en position action, `responsable` vs `fiche de controle`
  en position objet. Les deux clés valent maintenant
  `responsable qse|valider|fiche de controle|TEMPS|delai`, prérequis du canal CLE que
  `label.json` attend pour I01. Causes : (a) `fr_core_news_lg` étiquette « valide » en ADJ et
  sa table `lemma_rules` n'a pas la règle « -e → -er » du présent 3ᵉ pers. sing. ; (b) la tête
  nue du sujet (« Responsable », IDF 4,36) raflait la position objet devant « fiche de
  contrôle » (3,66). Effet de bord mesuré et corrigé en cours de route : exclure les *jetons*
  d'un rôle trouait les groupes qui le contiennent (« réseau des des ateliers ») — on écarte
  donc le groupe par sa **tête**. Conséquences chiffrées : 347 → 331 concepts, 22 → 21 alias
  (perte de `atelier ~ ateliers`, EXACT — « atelier » n'existait que comme fragment de « chef
  d'atelier »), 521/803 → 505/767 nœuds/arêtes, chargement toujours idempotent. 464 tests +
  1 xfail, 0 skip. Les 2 critères rouges du J3 sont inchangés.
- **J4** (2026-08-15) — Fait : ciblage complet (4 canaux, fusion RRF, filtre de
  comparabilité, budgets, matérialisation `PAIRE_CANDIDATE` idempotente), `cohera cibler`,
  mini-ablation du pont. **1517 → 72 paires candidates, rappel du ciblage 12/12** — le point
  de contrôle n°1 est franchi — facteur de réduction 0,9525 pour une cible de 0,91. I12 sort
  **par le canal DIMENSION et lui seul**, N03 et N02 ne sortent pas, N08 sort par DIMENSION
  comme prévu. 538 tests + 2 xfail, 0 skip.
  **1 critère ROUGE** : **mesuré 72** paires candidates, **attendu 80 à 140**. L'union des
  canaux donne 87 paires, 13 tombent à la comparabilité et 2 aux budgets. **Aucun canal n'a
  été appauvri, aucun paramètre resserré** par rapport à `architecture.md` §6 — vérifié par
  la mesure : le seuil vectoriel est plus permissif (0,65 contre 0,70 en cosinus brut),
  `k_voisins` plus large (24 contre 12, et k = 12 rend les **mêmes 41 paires** — c'est le
  seuil qui borne, pas k), top-3 du canal 5, top-k = 8, poids RRF et B = 4 × max identiques,
  filtre de comparabilité porté de 3 à 5 branches donc plus permissif. Les deux garde-fous
  ajoutés au Cypher sont des **no-ops mesurés** : retirer `cle_comparaison <> ''` laisse le
  canal CLE à 1 paire, retirer `valeur_si IS NOT NULL` laisse le canal DIMENSION à 70 lignes.
  C'est donc le corpus qui produit moins de bruit que l'estimation du plan. Les deux critères
  que cette borne basse sert à protéger sont atteints. Rien n'a été relâché pour fabriquer
  les 8 paires manquantes ; `xfail(strict=True)` dans `tests/test_ciblage.py`, avec les deux
  chiffres et la même explication.
  **Correction d'échelle, en amont de tout le reste.** Neo4j ne rend jamais un cosinus :
  `vector.similarity.cosine()` comme `db.index.vector.queryNodes` renvoient `(1 + cos) / 2`.
  Le Cypher de `architecture.md` §6.4 compare donc un score normalisé à un seuil pensé en
  cosinus brut ; appliqué tel quel, `score >= 0.70` retient 1232 paires sur 1517. Le projet
  n'a qu'une échelle, le cosinus brut (`lexique_qhse.yaml`, `label.json`) : la conversion est
  faite une fois, dans `canaux/vectoriel.py::cosinus_brut`.
  **Seuil vectoriel 0,70 → 0,65** (cosinus brut), soit −0,05, exactement à la limite de la
  tolérance. Motif : I08 (« ISO 45001:2018 » contre « OHSAS 18001 ») mesure 0,670 et n'a
  aucun autre canal — ni clé, ni concept partagé, ni grandeur ; à 0,70 le rappel tombe à
  11/12. Le seuil est au percentile 97,3 de la distribution mesurée (41 paires sur 1517).
  **Erreur de vérité terrain, signalée et non corrigée** : `label.json` affirme pour I12
  « cos clause ~0,67 < 0,70 » ; la mesure donne **0,598** en cosinus brut (0,799 normalisé).
  Le chiffre est faux, la conclusion qu'il en tire — I12 hors de portée du canal vectoriel —
  reste juste. `corpus/fixtures/` n'a pas été touché.
  **Écart à `architecture.md` §6.6** : filtre de comparabilité porté de 3 à 5 branches.
  Ajouts : branche NORME (les deux clauses citent un référentiel externe → I08) et branche
  CONCEPTUELLE (≥ 2 concepts canoniques d'IDF > 1,5, le critère exact du canal 3 → I11).
  Cause commune : « est arrêtée immédiatement » et « intervient après validation » sont
  prescriptifs sans marqueur déontique, donc le J2 laisse `modalite = null`.
  **Écart plan / vérité terrain** : `docs/plan-1-semaine.md` §J4 annonce « 81 → ~10 paires »
  et « rappel 7/7 », avec des V1…V7 définis nulle part ; `label.json` annonce 1517 → 80–140
  et 12/12. Référentiel retenu : `label.json`.
  **Ablation du pont inter-documents** : 12/12 → **11/12** (I11 perdue), 72 → 62 paires
  candidates, canal conceptuel 40 → 23 appariements, canaux vectoriel et dimension inchangés.
  Effet net mais modeste, pas l'« effondrement » annoncé par le plan : le canal vectoriel
  rattrape l'essentiel. La branche « sans pont » **surestime** le canal CLE, dont la clé est
  canonicalisée au *chargement* et non à la requête ; l'apport réel du pont sur la clé vaut
  1 paire, mesuré à part par `ablations.apport_du_pont_sur_la_cle`.
  **Observations** : le canal CLE n'apparie qu'une paire (I01) là où `label.json` liste `CLE`
  pour I01, I02, I13, I14 et I15 — sans coût de rappel, les quatre autres passant par
  d'autres canaux. Rappel du ciblage sur les 19 incohérences : 18/19, seule I07 (RACI, hors
  périmètre) est écartée par la comparabilité.
  **Dette identifiée, à traiter au J5 ou au J7** : `RENVOIE_A` n'est jamais chargé dans le
  graphe. Le canal 1 (structurel) n'a donc aucune donnée — son absence du J4 ne coûte rien,
  I09 et I10 étant des anomalies mono-clause couvertes par `Reference.resolu` au J2 — mais la
  propagation d'impact de `architecture.md` §8.4 sera incomplète le jour où on l'implémentera.
  Même arbitrage que pour la comparabilité : soit charger l'arête, soit sourcer depuis les
  Clause Frames.
  Reste ouvert : conditions, algèbre des portées et détecteurs A1/A2/A5 — c'est J5.
- **J5** (2026-08-16) — Fait : algèbre des conditions (règles typées seules, 23 conditions
  distinctes, 9 arêtes — 5 `INCLUS_DANS`, 3 `DISJOINT_DE`, 1 `RECOUVRE` —, 244 paires en
  file d'attente pour le J6 dans `file_attente_conditions.jsonl`), test de recouvrement des
  portées à 5 cas, détecteurs A2, A1 et A5, cascade de l'étage A. Chargement toujours
  idempotent (505 nœuds / 776 arêtes hors `PAIRE_CANDIDATE`). **650 tests + 2 xfail,
  0 skip.**
  **Les deux critères durs sont atteints : précision = 1,00 et 0 faux positif** sur les
  7 contre-exemples du périmètre (N01, N02, N03, N04, N06, N08, N09 — les deux derniers
  ajoutés, ils manquaient à la consigne). 11 constatations, toutes présentes dans
  `label.json`. N01 sort en `SPECIALISATION` et le test inverse est en place : en portant
  « 24 heures » à 72 h dans une **copie mémoire** de la frame, le verdict bascule en
  `CONTRADICTION` — `corpus/fixtures/` n'a pas été touché.
  **Étage A : 8 des 9 incohérences que `label.json` y attend.** I01, I02, I04, I08, I09,
  I10, I14, I15 sont conclues fermement. I03, I05 et I11 escaladent, ce qui est exactement
  leur `etage_attendu: "C"`.
  **1 critère ROUGE : I12 escalade au lieu de sortir à l'étage A.** D1 §6.2 et D2 §6.2 ne
  partagent **aucun** objet canonique — `anomalie`/`écart` et `chef d'atelier`/`hiérarchie`
  sont sous le seuil d'alias depuis le J3, volontairement. Elle a donc le profil exact de
  N08, qui doit être rejeté : mêmes rôles, portées identiques, zéro objet partagé. Aucun
  séparateur symbolique ne les distingue. Il fallait choisir entre 4 faux positifs plus N08
  et l'escalade d'I12 ; la précision et le zéro faux positif sont les critères durs de la
  journée. I12 escalade **avec son motif**, sera reprise au J6, et un test l'exige explicite.
  Second garde-fou indépendant sur la même paire : « dans la semaine » porte
  `statut = IMPRECIS` (CAP04) et ne fonde pas une affirmation.
  **⭐ Garde-fou de précision : deux objets canoniques partagés minimum.** Sans lui, A2 rend
  4 constatations fausses — D1 §5.3 ↔ D2 §5.1, D1 §6.5 ↔ D2 §6.5, D1 §6.3 ↔ D2 §4.5,
  D1 §6.5 ↔ D2 §5.1 — toutes de la même forme : même rôle, valeurs différentes, objets sans
  rapport. Précision 12/16 = 0,75 sans, 1,00 avec. Le seuil n'est pas inventé : c'est
  `partages_min: 2` du canal conceptuel (`config/ciblage.yaml`, architecture.md §6.3),
  transposé aux seuls concepts de type OBJET. Distribution mesurée sur les 72 candidates :
  29 paires à 0 objet, 11 à 1, 20 à 2, 8 à 3, 3 à 4, 1 à 7.
  **Garde-fou envisagé puis retiré parce que MESURÉ inutile** : une garde sur les canaux du
  ciblage (« un verdict ferme exige CLE, CONCEPTUEL ou VECTORIEL »). Sur les 72 candidates,
  26 échouent aux deux gardes, 14 n'échouent qu'à celle des objets, et **aucune n'échoue
  qu'à celle des canaux**. Strictement redondante, donc supprimée plutôt que conservée en
  no-op — deux gardes dont une ne travaille jamais rendent le chiffre de précision
  inexplicable.
  **Correction de configuration : `seuil_declenchement` PLUS_GRAND → PLUS_PETIT.** La valeur
  contredisait la sémantique déclarée de `Monotonie` (« le sens de *plus strict* »),
  l'en-tête de `registre_grandeurs.yaml` lui-même, et `label.json` I13
  (`clause_fautive: "D1 (niveau 3, plus permissif)"`, « à plus de 3 m » contre « à plus de
  2 m »). `tests/test_extraction_config.py` est retourné et renommé. **Écart au plan** : la
  consigne du J5 annonçait « monotonies opposées (`seuil_declenchement` vs
  `seuil_exposition`) » ; après correction ces deux rôles se durcissent dans le **même**
  sens, et c'était le bug qui donnait l'illusion d'une opposition. La vraie opposition du
  corpus est `duree_conservation` (PLUS_GRAND) contre les rôles de délai et de seuil
  (PLUS_PETIT) — D1 est « plus permissive » dans I13 (3 m, la plus grande valeur) comme dans
  I03 (3 ans, la plus petite), ce qu'aucune comparaison en dur ne peut produire.
  **Découverte qui sauve I13 et I14** : trois conditions du corpus ne font que **redire une
  grandeur de leur propre clause** — « pour les interventions réalisées à plus de 3 mètres »
  face à la grandeur « 3 mètres » (D1 §7.1 et D2 §7.1), « dès lors que l'exposition dépasse
  80 dB(A) » face à « 80 dB(A) » (D2 §5.5). Comptées comme restriction de portée, I13
  devient INDÉTERMINÉE et I14 une SPÉCIALISATION : les deux incohérences disparaissent.
  `portee_effective` les écarte ; la condition de N01 (« En cas d'accident… ») ne contient
  pas « 24 heures » et reste donc une vraie restriction.
  **Asymétrie A1/A2 sur la portée indéterminée**, mesurée et testée : A2 rétrograde (comparer
  deux valeurs suppose de savoir si elles s'appliquent au même cas), A1 non — §7.1 ne lui
  demande que des conditions « non disjointes ». I04 oppose une condition POPULATIONNELLE à
  une SPATIALE, sans règle typée pour les relier ; A1 la perdrait sinon.
  **A5 trouve une quatrième clause, non prévue** : D1 §10.2 (« Par dérogation à la procédure
  PR-QSE-02 § 3.1 », absente du corpus). Ce n'est pas un faux positif — c'est I17
  (DEROGATION / ORPHELINE), une incohérence réelle simplement attribuée à A8 hors périmètre.
  A5 l'attrape plus tôt par sa règle « renvoi non résolu ». Étiquette de détecteur
  différente de la vérité terrain, constat juste ; `corpus/fixtures/` n'a pas été touché.
  **Dette du J4 non traitée, sans conséquence ici** : `RENVOIE_A` n'est toujours pas chargé.
  A5 source les références depuis `Reference.resolu` des Clause Frames, décision actée.
  **Pas de commande CLI au J5** : la restitution est le J7. `cohera graphe charger` écrit
  désormais la file d'attente des conditions, comme il écrivait déjà la zone grise.
  Reste ouvert : étage B (NLI), étage C (LLM juge), arbitrage de la zone grise et de la file
  d'attente des conditions — c'est J6.
- **J6** (2026-08-17) — Fait : `LLMClient` complet (cache disque par hash, compteurs
  d'appels et de jetons, réparation bornée à 1 essai, bascule de profil par variable
  d'environnement), arbitrage des alias de zone grise, étage C (LLM juge) avec ses deux
  garde-fous, commande `cohera detecter`, rapport étendu (abstentions nommées, hypothèses
  d'alias, statistiques LLM). **713 tests + 2 xfail, 0 skip.**
  **Périmètre du juge : 57 paires, mesuré avant d'écrire le juge.** Décision explicite
  d'élargir le juge à toutes les paires que le symbolique n'a pas conclues, pour qu'aucune
  ne soit écartée par construction. Le tri se fait sur le **motif**, pas sur la rubrique :
  36 escalades + 21 paires « sans donnée », contre 8 conclues, 6 fermées par compatibilité
  (`VALEURS_EGALES` 5, `ECART_DE_FORCE_NUL` 1) et 1 par portées disjointes.
  ⭐ **Piège révélé par la mesure : I11 n'est dans aucune escalade.** `label.json` la désigne
  comme « le cas qui justifie l'étage C », or sans modalité ni grandeur elle produit trois
  verdicts `AUCUNE` et tombe dans `muets`. Un juge branché sur `Detection.escalades` — la
  lecture littérale — la manquerait. Second piège de la même mesure : **N04 entrait dans le
  périmètre**, aucun détecteur ne posant `PORTEES_DISJOINTES` (A2 s'arrête sur
  `PAS_DE_GRANDEUR_COMPARABLE`, A1 sur `MODALITE_ABSENTE`). Corrigé en testant la disjonction
  **sur la paire**, comme le veut architecture.md §7.2 : 58 → 57 paires.
  **Deux BUGS du premier run, corrigés — et non consignés en rouge, parce qu'un défaut de
  conception se répare, il ne se documente pas comme une limite du système.**
  (a) *Plafond trop serré.* À 60, il a mordu en exécution : 60 appels réseau pour
  **34 paires seulement**, à cause de 24 réparations (chacune est un appel) et de
  10 dépassements de délai ; 13 paires n'ont jamais été soumises. Le plafond mesurait la
  faiblesse du modèle, pas celle du corpus. **Porté à 200**, hors d'atteinte sur ce corpus
  même à deux appels par paire. Le mécanisme reste exercé par un test à budget forcé à 3.
  (b) *Ordre de soumission alphabétique.* Le tri se faisait par `clause_id` ; D1 §9.2 étant
  en fin d'alphabet, **I03 n'a jamais été soumise**, ce qui vidait de son sens la décision
  d'élargir le périmètre « pour qu'aucune cible ne soit écartée par construction ». **Tri
  par score RRF décroissant**, comme le plan le prévoyait : si le plafond mord, il mord les
  paires les moins prometteuses. Trois tests le figent, dont un de bout en bout.
  Deux autres défauts trouvés en chemin : le compteur `non_verifiees_budget` comptait aussi
  les paires sautées par le coupe-circuit, et la CLI annonçait « plafond de budget » sur une
  panne de service — les deux causes sont désormais comptées et affichées séparément.
  **⚠️ CRITÈRE ROUGE n°1 — faux positifs : 4 en local, 10 en distant, contre 0 exigé.**
  **⚠️ CRITÈRE ROUGE n°2 — rappel du périmètre : 9/12 en local** contre ≥ 10/12 visé.
  Le profil distant atteint 10/12, mais en payant 10 faux positifs.
  **⭐ ABLATION PROFIL A / PROFIL B, la mesure que ce J6 rend enfin possible.** Même corpus,
  mêmes 57 paires, même prompt, seule la variable `COHERA_LLM` change.
  | | **A — local** (`saiga_mistral_7b`) | **B — distant** (`llama-3.3-70b`, Groq) |
  |---|---|---|
  | Paires soumises | 52 / 57 (5 délais dépassés) | **57 / 57** |
  | Appels réseau | 33 (+ 60 servis par le cache) | 43 (+ 14 par le cache) |
  | **Réparations** | **39** | **0** |
  | Verdicts annulés (preuve inventée) | 8 — 15,4 % | 7 — 12,3 % |
  | Constatations (dont étage C) | 18 | 26 |
  | Précision / rappel (périmètre) | 0,69 / **9 sur 12** | 0,50 / **10 sur 12** |
  | Faux positifs | 4 | 10 |
  | Durée du run | ~20 min | ~7 min (cadencé à 8 s) |
  **Ce que l'ablation démontre.** Le format n'est pas un problème de modèle *distant* :
  **39 réparations contre 0**. Le 7B local ne tient pas le contrat de sortie, le 70B distant
  le tient parfaitement — c'est exactement l'avertissement d'architecture.md §7.4 (« un bon
  extracteur contraint, un juge médiocre »), mesuré. Mais le distant **échange de la
  précision contre du rappel** : il conclut plus souvent, donc trouve I05 *et* affirme
  6 constatations fausses de plus. Aucun des deux profils n'atteint les deux critères durs
  à la fois. Le seul critère chiffré du plan que le profil B fait passer est le rappel.
  **Sort nommé des quatre cibles**, identique sur les deux profils sauf mention :
  I11 → **constatation** (les deux profils) · I05 → COHERENT en local, **constatation** en
  distant · I03 → **abstention `PREUVE_INVENTEE`** (les deux) : soumise cette fois, le juge
  a inventé sa citation et le filtre contraint l'a annulée — le garde-fou travaille · I12 →
  jugée COHERENT par les deux, verdict faux mais issue légitime du contrat. N08 → abstention
  en local, **jugée COHERENT en distant** : les deux réponses sont correctes.
  **Cadencement des profils distants, mesuré.** Sans pause, le palier gratuit de Groq répond
  429 après 14 paires, le juge lit ce quota comme une panne et son coupe-circuit saute au
  bout de 3 échecs — 40 paires perdues. `pause_entre_appels_s: 8.0` sur le profil, appliquée
  après le cache et le budget, avant le réseau : 57/57 paires, 0 échec de transport.
  **Gemini inutilisable en l'état** : 404 sur `gemini-2.5-flash` à l'endpoint compatible
  OpenAI. Non diagnostiqué plus avant, Groq suffisant pour l'ablation.
  **Ablation `--sans-etage-c`, mesurée** : étage A seul = 11 constatations, 8 VP / **1 FP**,
  rappel 8/12. L'étage C apporte donc **+3 vrais** (I06, I11, I19) et **+3 faux**.
  **Le seul FP de l'étage A n'en est pas un** : c'est `D2 §10.1` (A5 mono-clause,
  « OHSAS 18001 retirée »), la **seconde moitié du double constat d'I08**, que `label.json`
  décrit lui-même comme « double constat : référentiels divergents ET OHSAS 18001 retirée ».
  Le harnais ne sait pas l'apparier parce qu'I08 y est modélisée en une seule entrée de
  paire. C'est un défaut de **regroupement** (architecture.md §8.2), explicitement au J7 —
  pas une constatation infondée. Il était déjà là au J5 : le J5 mesurait sa précision sur
  les seuls contre-exemples, `cohera evaluer` n'ayant pas tourné faute de CLI. **La ligne
  « précision = 1,00 » du J5 est donc à lire comme « 1,00 sur les 7 contre-exemples », pas
  comme la précision du harnais.**
  **Les faux positifs de l'étage C sont ceux que le garde-fou des objets du J5 avait
  supprimés** : D1 §5.2 ↔ D2 §8.1, D1 §5.3 ↔ D2 §5.1, D1 §6.3 ↔ D2 §4.2 — même forme, objets
  sans rapport, et le modèle affirme quand même. Les deux profils produisent les mêmes,
  le distant y ajoutant six autres. **Le garde-fou des objets ne les sépare pas à l'étage
  C**, mesuré : le premier faux positif partage **3** objets canoniques, plus qu'I11 (1) et
  qu'I03 (1). Le transposer tuerait les vrais et garderait le faux.
  **Décision actée : aucun garde-fou supplémentaire n'est ajouté.** Aucun séparateur
  symbolique connu ne distingue ces paires des vrais positifs sans détruire I03 et I11.
  Elles restent **acceptées et documentées comme limite mesurée du jugement**, pas comme un
  défaut à corriger par une règle ad hoc taillée pour ce corpus. C'est la contrepartie
  assumée de l'élargissement du périmètre.
  **Ce que le juge a réussi** : I11 sort en constatation sur les deux profils, avec ses deux
  preuves littérales — c'est le cas qui justifie l'étage C, et il est acquis. I06 et I19
  (hors périmètre, détecteurs A3 et A6 non implémentés) sont trouvées en prime, et I16 en
  distant.
  **⚠️ Écart à architecture.md §4.4, mesuré : le décodage contraint est indisponible en
  local.** §4.4 pose que « LM Studio accepte `response_format: json_schema` : le décodage
  contraint rend le JSON invalide impossible ». Faux pour `saiga_mistral_7b_gguf` : tout
  schéma, fût-il réduit à une propriété `string`, échoue en HTTP 400 (« Failed to initialize
  samplers: Unexpected empty grammar stack »), et LM Studio refuse par ailleurs
  `json_object`. Il ne reste que le texte libre. `ProfilLLM.json_schema: bool` est donc
  devenu `format_sortie` à **trois** valeurs. Conséquence directe : la boucle de réparation
  porte seule la contrainte de forme, d'où les 24 réparations qui ont épuisé le budget.
  **Prompt : gabarit JSON explicite, mesuré et non deviné.** Sans gabarit, le modèle rend un
  JSON partiel — `preuve_a` et `preuve_b` absentes — puis verse le reste en prose ; le filtre
  contraint annule alors *tous* les verdicts et l'étage C ne mesure que sa propre inutilité.
  Avec gabarit, sur le même cas : un appel au lieu de deux, deux preuves littérales.
  **Taux d'annulation du filtre contraint : 15,4 % en local, 12,3 % en distant.** Le
  garde-fou travaille pour de bon, sans tout annuler — et c'est lui qui sauve I03 d'une
  fausse constatation sur les deux profils.
  **Arbitrage de la zone grise : 2 appels, 0 alias retenu, 2 abstentions** (réponse non
  conforme au schéma après réparation). Rappel du J3, inchangé : les deux paires de
  `zone_grise.jsonl` ne sont **pas** celles qu'I03 demande — `archiver ~ conserver` mesure
  0,613, sous le plancher de la bande, et la bande n'a pas été élargie pour l'y forcer.
  **Écart plan / consigne sur le budget, signalé et non maquillé** : `plan-1-semaine.md` §J6
  chiffre « ≤ 15 appels LLM » (tableau de bord ~14) ; la consigne du J6 fixe ≤ 60, et le
  périmètre élargi mène à 59 nominal. Le plafond dur testé est 60.
  **Écart assumé à architecture.md §7.4** : garde-fous n°2 (anti-biais de position, ×2
  appels) et n°3 (auto-cohérence 3 échantillons, ×3 appels) **non implémentés** — la consigne
  dit « deux garde-fous seulement ». Ce n'est pas un oubli : c'est le premier candidat à la
  reprise, et le plafond porté à 200 leur laisse désormais la place. L'auto-cohérence est la
  piste la plus prometteuse contre les faux positifs de l'étage C, qui sont précisément des
  affirmations peu stables.
  **Écart d'A1 à architecture.md §7.1, documenté et figé par un test** (décision 3) : §7.1
  exige l'égalité de `acteur_canonique`, `action_canonique` et `objet_canonique` ; A1 applique
  en fait `objets_partages >= 2`. Mesuré sur I04, les trois positions canoniques diffèrent
  des deux côtés et A1 conclut quand même — l'égalité stricte perdrait une incohérence
  CRITIQUE. Test : `test_a1_ne_teste_pas_l_egalite_stricte_acteur_action_objet`.
  **Asymétrie A1/A2 sur la portée indéterminée : test ajouté** (décision 2). Le test existait
  de nom mais n'asserait que la moitié A1 ; la moitié A2 est désormais vérifiée sur la même
  paire, grandeurs comparables injectées dans des copies mémoire.
  **Deux profils, deux rapports conservés** : `rapport_local.json` et `rapport_groq.json`,
  pour que le tableau d'ablation du J7 soit rejouable sans repayer les appels — le cache
  disque contient les deux jeux de réponses.
  Reste ouvert : regroupement des constatations (§8.2, qui corrige le « FP » D2 §10.1),
  choix du profil de référence pour la soutenance, les 3 ablations du plan et la restitution
  HTML — c'est J7.
- **J7** (2026-08-17) — Fait : consolidation (§8.2 regroupement, §8.3 criticité et arbitrage),
  vérification bloquante des preuves littérales, `rapport.html` par gabarit Jinja2 à quatre
  rubriques, dérogations en vigueur, les trois ablations pilotées par drapeaux, scénario
  incrémental sur jeu dérivé, `evaluation/historique.csv`. Quatre commandes nouvelles :
  `cohera rapport`, `cohera ablation`, `cohera incrementer`, `cohera historique`.
  **793 tests + 2 xfail, 0 skip.** Le plan de la semaine est terminé.
  **⭐ Preuves littérales : 33/33 = 100 %**, premier critère d'acceptation du J7, vérifié
  **programmatiquement et de façon bloquante** — `cohera rapport` sort en code 1 et n'écrit
  aucun HTML si une seule citation n'existe pas dans son texte source. La vérification est
  volontairement **plus stricte** que `CoteClause.preuve_est_litterale`, qui rend `True`
  quand `texte_source` vaut `None` : permissif pour un rapport partiel, ce serait ici un
  laissez-passer (« rien contre quoi vérifier » deviendrait « la preuve est bonne »).
  **⭐ Regroupement : le faux positif `D2 §10.1` tombe, sur les DEUX profils.** Local 4 → 3,
  distant 10 → 9, **rappel inchangé** (9/12 et 10/12), une seule absorption chacun. Précision
  du périmètre 0,69 → **0,75** en local, 0,50 → 0,53 en distant. Effet secondaire notable :
  **l'étage A seul passe à 0 faux positif et précision 1,00** — le « FP » qu'il produisait
  depuis le J5 était la moitié mono-clause du double constat d'I08, et non une constatation
  infondée. La ligne « précision = 1,00 » du J5, qu'il fallait lire « sur les 7
  contre-exemples », vaut désormais sur le harnais entier à l'étage A.
  **L'absorption s'appuie sur la PREUVE LITTÉRALE, pas sur la clause commune.** Trois
  conditions cumulatives : même type de taxonomie, la clause du constat mono-clause est un
  côté de la paire, et les deux preuves se citent l'une l'autre (l'une sous-chaîne de
  l'autre — elles portent donc sur le même passage du même `texte_source`). Le garde-fou
  s'est **vérifié sur données réelles** : le profil distant produit une paire
  `D1 §10.2 ↔ D2 §4.2`, et l'anomalie mono-clause `D1 §10.2` n'a **pas** été absorbée, ses
  preuves désignant un autre passage. Sans cette condition, un vrai constat aurait disparu.
  **Le regroupement de §8.2 lui-même ne fusionne rien sur ce corpus**, et c'est une propriété
  du corpus : aucune paire ne partage sa clé `(type, clé de comparaison, valeurs en conflit)`
  avec une autre. Il est écrit quand même, il est testé, et il **refuse de travailler sur une
  clé partielle** — sans clé de comparaison, chaque constatation reste seule. Regrouper sur
  le seul `type` fusionnerait toutes les divergences numériques du corpus en une ligne.
  **⭐ CRITICITÉ : l'arbitrage de §8.3 reproduit `relation_hierarchique` de `label.json` sur
  les 5 cas détectés**, sans que la règle ait été écrite en les regardant. I01 et I02
  (`DECLINAISON_PLUS_STRICTE`) ne désignent aucun fautif ; I13, I14 et I15
  (`INVERSION_HIERARCHIQUE`) désignent D1 §7.1, D1 §5.5 et D1 §8.2 — et `label.json` nomme
  explicitement « D1 (niveau 3, plus permissif que le niveau 1) » pour I13. I08 désigne
  D2 §10.1 par la branche « exigence externe », avec le multiplicateur ×2,0 qui la place en
  tête du rapport (criticité 3,71). Test piloté par la vérité terrain, non circulaire :
  l'entrée vient de la mesure, l'attendu de `label.json`.
  **Correction en cours de route : `clause_fautive` désignait trop largement.** Je désignais
  la clause la plus permissive dans tous les cas ; §8.3 ne désigne que « celle du document de
  niveau inférieur **si elle est plus permissive** ». Reprocher à une politique d'être plus
  souple que la procédure qui en dérive est faux — c'est l'ordre normal d'une déclinaison, et
  c'est le cas d'I01 (D1 exige 48 h là où D2 accorde 5 jours). La règle resserrée rend `""`,
  et le rapport le dit en toutes lettres plutôt que de laisser un blanc.
  **Deux limites de la criticité, dites plutôt que masquées.** (a) L'étage C rend ses
  constatations **sans gravité** — 7 sur 17 ; son contrat de sortie (§7.4) demande un verdict,
  une confiance et deux preuves, et n'a pas de quoi calculer une gravité. Elle est donc
  **déduite du type de taxonomie**, jamais des cas individuels, et jamais quand elle est déjà
  posée. (b) **`w_portee` est neutre** : la portée effective est calculée au J5 mais n'est pas
  reportée sur la constatation. Écrit dans `config/restitution.yaml` **et figé par un test**
  qui échouera le jour où quelqu'un la branche sans mettre la limite à jour — un commentaire
  seul ne tient pas une limite.
  **Dérogations en vigueur : N05 listée, I17 et I18 écartées.** Quatre conditions cumulatives
  (cible résolue, motivée, approuvée, non expirée à la date de référence) séparent proprement
  les trois dérogations du corpus. `cohera evaluer` affiche désormais « toutes listées » là où
  il disait « absentes du rapport » depuis le J0.
  **Défaut trouvé et corrigé en chemin** : la dérogation ne portait que sa clause source, or
  `label.json` désigne N05 par la **paire** `D1 §10.1 ↔ D2 §6.4` et le harnais apparie sur le
  `frozenset` des deux couples. La rubrique était remplie et restait comptée « absente ». La
  cible est maintenant résolue et portée en `clause_b`, sans preuve citée — la dérogation ne
  reproche rien à la clause visée, elle s'en exempte.
  **⚠️ `date_reference` ajoutée à `config/corpus.yaml` (2026-08-10).** Sans elle, « cette
  échéance est-elle dépassée ? » se répondrait avec `date.today()`, et le rapport changerait
  de contenu d'un jour à l'autre sans qu'aucun code ne bouge. La valeur **doit** coïncider
  avec `date_reference_evaluation` de `label.json`, mais elle y est recopiée : le pipeline
  n'a pas le droit de lire la vérité terrain.
  **⭐ LES TROIS ABLATIONS, mesurées à étage A constant.**
  | branche | candidates | ciblage | constatations | VP | FP | rappel | précision |
  |---|---|---|---|---|---|---|---|
  | référence (étage A) | 72 | 12/12 | 10 | 8 | **0** | 8/12 | **1,00** |
  | `--sans-alias` | 62 | 11/12 | 8 | 6 | 0 | **6/12** | 1,00 |
  | `--sans-canal5` | 46 | 11/12 | 10 | 8 | 0 | 8/12 | 1,00 |
  **Ce que les ablations démontrent.** Le **pont d'alias est la brique la plus coûteuse à
  retirer** : −10 paires candidates, ciblage 12/12 → 11/12, et surtout **rappel 8/12 → 6/12**,
  I01 et I02 perdues. Son apport est donc bien plus fort à la *détection* qu'au *ciblage* —
  le canal vectoriel rattrape le ciblage, mais la comparaison de clauses a besoin des alias.
  Le **canal DIMENSION coûte cher en bruit et rapporte au ciblage** : le retirer supprime
  26 paires candidates (72 → 46, un tiers) et fait tomber le ciblage à 11/12 (I12), **sans
  perdre un seul vrai positif à l'étage A** — puisqu'I12 n'y est de toute façon pas détectée.
  C'est le canal du rappel futur, pas du rappel actuel.
  **`--sans-etage-c` n'est pas une branche à part** : toutes les branches tournent à étage A
  seul, donc la **référence de ce tableau EST le système sans étage C**. L'apport de l'étage C
  se lit en la comparant au rapport complet : 8 VP / 0 FP → 9 VP / 3 FP. **+1 vrai, +3 faux.**
  **Deux honnêtetés portées DANS le tableau, pas en note de bas de page.** (a) La branche
  « sans alias » **surestime le canal CLE**, dont la clé est canonicalisée au *chargement* et
  non à la requête ; `apport_du_pont_sur_la_cle` chiffre l'écart réel à 1 paire, affiché sous
  le tableau. (b) **Aucune branche ne fait tourner l'étage C**, et c'est délibéré : changer le
  ciblage change les paires soumises au juge, donc toutes les clés de cache — chaque branche
  coûterait ~50 appels neufs et le tableau mêlerait l'effet du canal à celui du modèle.
  **`--sans-canal5` ne mute PAS la configuration** : le drapeau passe un `frozenset[Canal]` en
  paramètre d'exécution de `cibler()`. La config déclare ce qui existe, le drapeau éteint pour
  un run. Muter le YAML serait de toute façon sans effet — `canal_actif` est mis en cache par
  `lru_cache` — mais surtout, une ablation qui laisserait une trace dans la configuration
  contaminerait toutes les exécutions suivantes. Un test l'exige.
  **⭐ SCÉNARIO INCRÉMENTAL : I02 → `RESOLUE`, 0 appel LLM, 18 s.** D1 §5.1 passe de « tous les
  trimestres » à « deux fois par an » ; A2 conclut `VALEURS_EGALES`, la constatation disparaît,
  et le rapport la **conserve au statut RESOLUE** plutôt que de l'oublier — une correction qui
  s'efface du rapport ne se démontre pas. 17 constatations → 16 actives + 1 résolue.
  **`corpus/fixtures/` n'est pas touché** : le jeu `incremental` est déclaré `derive_de:
  fixtures` avec ses substitutions, et la copie est matérialisée dans `.cache/corpus/`. La
  chaîne métier « deux fois par an » vit ainsi en YAML, jamais dans un `.py`. Une substitution
  dont la chaîne source n'apparaît pas **exactement une fois** est refusée : une substitution
  ambiguë modifierait une clause non visée.
  **Le graphe est rendu à son état de référence dans un `finally`** : les `clause_id` du jeu
  dérivé sont ceux du jeu source, donc le chargement écrase les textes de D1. Vérifié après
  coup : 505 nœuds / 848 arêtes, idempotence confirmée.
  **⚠️ ÉCART CHIFFRÉ, signalé : durée 18 s contre « < 5 s » dans la consigne.** Le critère du
  plan §J7 (« tourne en une commande ») est atteint et les 0 appels aussi, mais pas les 5 s.
  Les 18 s sont le coût du pipeline : resegmentation spaCy, réextraction, rechargement,
  reciblage, cascade, restauration. **Aucune de ces étapes n'est incrémentale** — le J7 rend
  le *scénario* incrémental, pas le *pipeline*. Rien n'a été raccourci pour tenir la cible.
  **⚠️ TROIS ERREURS DU PLAN sur ce scénario, signalées et non recopiées.**
  `docs/plan-1-semaine.md:138` écrit « modifier `D1 §3.1` en *deux fois par an* → 5
  constatations, F2 résolue ». (a) D1 §3.1 est la **définition d'« anomalie »** : aucune
  périodicité, la substitution n'y aurait aucun sens ; I02 est en **D1 §5.1** d'après
  `label.json`, et c'est la seule clause du corpus où « tous les trimestres » apparaît.
  (b) « F2 » est le filtre d'éligibilité sur les périodes de validité disjointes, sans aucun
  rapport avec une périodicité. (c) « 5 constatations » vient du référentiel à 7 incohérences
  abandonné au J4. Référentiel retenu : `label.json`. `corpus/fixtures/` n'a pas été touché.
  **`evaluation/historique.csv` : 6 lignes, du J4 au J7, et une colonne `source`.** Les lignes
  J4 (ciblage seul) et J5 (étage A seul) sont **remesurées**, pas transcrites : ces deux
  configurations se rejouent exactement. Seule la ligne du run distant du J6 porte
  `source = journal`, pour ses 43 appels et ses 7 minutes — le rejeu, lui, est servi
  intégralement par le cache et coûterait 0. La colonne existe pour que le lecteur sache
  quelles cellules sont des mesures et lesquelles des souvenirs. `historique.csv` est **sorti
  du `.gitignore`** : `plan-1-semaine.md` §4 en fait « une figure du rapport de stage ».
  **`rapport_groq.json` régénéré au schéma du J7 sans un seul appel réseau** : 57/57 servis
  par le cache disque du J6, mêmes 7 verdicts annulés, même 12,3 %. Le tableau d'ablation A/B
  est donc rejouable à volonté, et il figure dans l'en-tête du HTML — présenter un profil sans
  son alternative reviendrait à cacher l'arbitrage.
  **Défaut de test corrigé en fin de journée**, et il est instructif : le test d'intégration du
  regroupement supposait que `rapport_local.json` soit **non consolidé**. Rafraîchir cet
  artefact au schéma du J7 l'a fait échouer alors qu'aucun comportement n'avait changé — le
  test dépendait de l'état d'un fichier généré. Il reconstruit désormais l'état « avant » en
  défaisant le regroupement à partir des occurrences que la consolidation conserve
  précisément pour cela.
  **Écart à la consigne, assumé** : la consigne demandait 3 rubriques HTML, le rapport en a
  **4** — les dérogations en vigueur s'ajoutent aux constatations, aux hypothèses d'alignement
  et aux zones non couvertes. Décision prise explicitement : le champ existait dans le schéma,
  le harnais le vérifiait, les données étaient déjà dans les frames, et N05 attend d'être
  *listée* et non *signalée*.
  Reste ouvert : les garde-fous n°2 et n°3 de §7.4 (anti-biais de position, auto-cohérence —
  la piste contre les 3 faux positifs restants), les détecteurs A3, A4, A6, A7, A8, A9, et
  `w_portee` dans la criticité.
- **J8** (2026-08-20) — Fait : étage B (NLI bidirectionnel) inséré entre A et C, seuils
  calibrés sur la distribution mesurée, drapeau `--sans-etage-b`, statistiques NLI au
  rapport. **806 tests + 2 xfail, 0 skip.** `cohera doctor` 6/6.
  **⭐ LA MESURE D'ABORD, L'ÉCRITURE ENSUITE.** L'étape 0 du plan §J8 est bloquante et elle
  a été tenue : les 57 paires réellement soumises au juge (`paires_a_juger`, pas une
  reconstruction) ont été passées au NLI **avant** qu'une ligne de `nli.py` ne soit écrite,
  et le tableau a été rendu avant décision. C'est cette mesure qui a fixé les seuils,
  écarté la branche haute et choisi la forme de l'étage.
  **Distribution mesurée** de `max P(contradiction)` sur 57 paires : min 0,0172 · médiane
  **0,4372** · max 0,9535, **étalée sur toute la plage** — le modèle a un avis sur tout,
  marque d'un classifieur générique appliqué à du français normatif. Elle n'offre que deux
  frontières franches, et ce sont elles qui bornent : écart de 0,0556 entre 0,0635 et 0,1191
  (6 paires en dessous) et écart de 0,0595 entre 0,8025 et 0,8620 (5 au-dessus). D'où
  **`seuil_rejet: 0.09`** et **`seuil_contradiction: 0.83`**. Le placement des cas de
  `label.json` a été relevé **après** coup et n'a déplacé aucune borne.
  **⭐ LE GAIN, ET IL SE LIT EN PAIRES, PAS EN APPELS.** 57 → **51 paires** soumises au juge,
  soit **−10,5 %**, à rappel et précision **strictement inchangés** (9/12, 3 FP, précision
  0,75, 17 constatations identiques). Le chiffre honnête n'est pas « appels réseau
  économisés » : le cache disque est complet, l'étage C passe **0 appel avant comme après**.
  Ce qui bouge est le nombre d'accès au cache, **100 → 91** (les deux arbitrages d'alias
  compris), qui est ce que coûterait un cache froid. Abstentions 25 → 23.
  **⚠️ RÉSULTAT NÉGATIF n° 1 — la branche « contradiction ferme » est DISQUALIFIÉE par la
  mesure.** À tout seuil ≥ 0,83 la bande haute contient 5 paires : I03 (vraie, non
  détectée), I06 (vraie, hors périmètre), **l'un des trois faux positifs de l'étage C**
  (D1 §6.3 ↔ D2 §4.2, à 0,910, 2ᵉ de tout le corpus) et **le contre-exemple N05**
  (D1 §10.1 ↔ D2 §6.4, à 0,862), qui doit rester silencieux. Un étage B qui affirmerait
  ajouterait **au moins deux constatations fausses** et casserait le critère « 0 faux
  positif » immédiatement. Écart assumé à architecture.md §7.3, qui pose « ≥ 0,85
  contradiction ferme » : **l'étage B ne conclut jamais seul.** Second motif, indépendant du
  premier et suffisant à lui seul : le NLI ne produit aucune citation, et l'invariant #3
  interdit un verdict sans preuve littérale. Il n'existe donc **volontairement aucun motif
  symétrique de `REJET_NLI`** dans `Motif` — la seule chose que cet étage sait faire est
  fermer par le bas. Deux tests le figent.
  **⚠️ RÉSULTAT NÉGATIF n° 2 — aucun gain de précision, et c'était le second espoir du J8.**
  Les 3 faux positifs de l'étage C **ne sont pas séparables** par le NLI : 0,910 pour le
  premier, 0,482 et 0,466 pour les deux autres, en plein milieu de la zone grise. Aucun
  seuil ne les retire sans détruire le reste. L'étage B ne rapporte donc que du coût
  économisé, pas de la crédibilité.
  **⚠️ RÉSULTAT NÉGATIF n° 3 — le seuil théorique de §7.3 est NOCIF sur ce corpus.** À 0,15
  — la valeur de départ de l'architecture — on fermerait 10 paires au lieu de 6, mais parmi
  elles **I19** (0,1394), une vraie incohérence que l'étage C constate aujourd'hui. Le plan
  §J8 avait raison d'interdire de recopier la valeur ; elle n'a pas été « arrondie » vers le
  bas pour épargner I19 non plus — c'est la distribution qui borne, et elle borne à 0,09,
  indépendamment de là où tombe I19.
  **⭐ L'OBSERVATION LA PLUS INTÉRESSANTE DU J8, sans effet opérationnel : le maximum
  bidirectionnel est le mauvais opérateur.** §7.3 prescrit de retenir le maximum des deux
  sens. Mesuré : **19 paires sur 57 changent de zone selon l'ordre** (23 sur les bandes
  théoriques de §7.3), écart médian 0,150 et **maximum 0,842**. Et dans la bande haute, le
  partage est net : les deux paires **stables** entre les deux sens sont les **vraies**
  incohérences (I03 : 0,954/0,893 · I06 : 0,802/0,870), les deux **instables** sont **le
  faux positif** (0,068/0,910) et **le contre-exemple N05** (0,862/0,424). Le maximum
  promeut donc une instabilité de modèle en confiance. Ce n'est **pas** transformé en
  règle : la mesure porte sur 5 paires, et une règle choisie parce qu'elle sépare les cas de
  la vérité terrain est exactement ce que le projet s'interdit. `ScoreNLI.stable` expose la
  propriété et le rapport compte les paires instables ; la piste est notée pour le stage
  n° 2. Elle est sans conséquence ici, l'étage B n'affirmant pas.
  **⭐ LE CACHE DU J6 EST PROTÉGÉ PAR CONSTRUCTION, ET PAR UN TEST.** L'étage B **n'écrit
  aucun verdict** hors des rejets. Motif mécanique, vérifié : un verdict rangé dans les
  escalades deviendrait `escalades[0]`, donc le `SIGNAL AMONT` du prompt, pour les 21 paires
  que l'étage A laisse sans donnée — dont I11. Leur clé de cache changerait et les mesures
  des J6 et J7 cesseraient d'être comparables sans être intégralement repayées.
  `test_l_etage_b_ne_change_pas_le_signal_amont_du_prompt` l'exige sur les deux formes de
  paire. Vérifié en exécution : 0 appel réseau, 91 accès servis par le cache.
  **L'exclusion passe par la CONFIGURATION, pas par du code neuf.** `REJET_NLI` est ajouté à
  `juge.motifs_fermants` ; `paires_a_juger` n'a pas bougé d'une ligne. Le commentaire du J6
  prévoyait exactement ce cas : « y ajouter un motif, c'est retirer des paires au juge ».
  **⚠️ ERREUR DE `label.json` SIGNALÉE, non corrigée.** La vérité terrain annonce pour N02
  `"teste": "Liste noire des alias + rejet NLI"`. Mesuré sur les deux vraies clauses du
  corpus, le NLI **ne rejette pas N02** : il y voit une contradiction à **0,94** dans un sens
  et 0,71 dans l'autre, entre deux obligations portant sur deux équipements différents.
  C'est bien la liste noire des alias qui protège N02, pas le NLI — N02 n'atteint d'ailleurs
  jamais l'étage B, le ciblage l'ayant écartée avant. Rien n'est cassé, `corpus/fixtures/`
  n'a pas été touché, et le fait est figé par
  `test_le_nli_ne_rejette_PAS_n02_contrairement_a_ce_qu_annonce_label_json`. C'est aussi la
  démonstration directe du résultat négatif n° 1.
  **L'indice de l'étiquette « contradiction » est LU dans le modèle, jamais supposé.**
  `distilcamembert-base-nli` la range en 0 ; les deux alternatives de §7.3
  (`camembert-base-xnli`, `mDeBERTa-…-xnli`) la rangent en 2. Coder l'indice en dur
  donnerait des probabilités **inversées sans lever la moindre erreur**.
  **Coût mesuré** : chargement 1,4 s, **114 inférences en 2,7 s sur CPU**, soit 47 ms/paire
  pour les deux sens — conforme aux ~25 ms/sens annoncés par §7.3.
  **⚠️ ÉCART CHIFFRÉ, signalé : le scénario incrémental passe de 18 s à 27 s.** L'étage B y
  tourne aussi — délibérément : le sauter ferait comparer deux pipelines différents et le
  « 0 appel LLM » ne voudrait plus rien dire. I02 → `RESOLUE` et 0 appel sont conservés. La
  cible « < 5 s » de la consigne du J7, déjà manquée à 18 s, s'éloigne donc ; rien n'a été
  raccourci pour la tenir.
  **Ce qui n'a pas bougé, et c'est voulu** : le tableau d'ablation du J7 tourne toujours à
  **étage A constant** (`evaluation/ablations.py` appelle `cascade.detecter` directement),
  donc ses trois branches sont inchangées et restent comparables au J7. `--sans-etage-c`
  rend toujours **11 constatations**, l'étage B ne pouvant par construction pas en créer.
  Preuves littérales toujours **33/33 = 100 %**.
  **`rapport.json` réparé.** Il avait été écrasé le 19/08 par une exécution de `cohera
  cibler` et ne contenait plus aucune constatation depuis. Régénéré au J8 depuis le cache,
  **0 appel réseau**. `evaluation/historique.csv` compte 8 lignes, et son libellé de
  configuration se lit désormais dans le rapport lui-même (« pipeline étages AC / ABC »)
  plutôt que dans le nom du fichier : deux exécutions du même jour ne se distinguent que par
  les étages qui ont tourné, et un nom de fichier peut mentir.
  Reste ouvert : inchangé par rapport au J7, moins l'étage B — garde-fous n°2 et n°3 de
  §7.4 (l'auto-cohérence reste la seule piste crédible contre les 3 faux positifs, le NLI
  ayant échoué à les séparer), détecteurs A3, A4, A6, A7, A8, A9, et `w_portee`.
