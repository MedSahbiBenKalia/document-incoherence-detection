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