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