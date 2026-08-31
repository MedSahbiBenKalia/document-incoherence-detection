# COHERA

Détection d'incohérences inter-documents QHSE par graphe de dépendances.

Pipeline Python qui ingère des procédures QHSE en français, construit un graphe de
dépendances dans Neo4j, cible les paires de clauses à vérifier, et détecte les incohérences
entre documents.

## Installation

Le venv est délibérément créé **hors du dossier OneDrive** : 5 Go de `site-packages` posés
dans un dossier synchronisé, c'est de la lenteur et des verrous de fichiers en plein
`pip install`.

```powershell
python -m venv C:\Users\DELL\venvs\cohera
C:\Users\DELL\venvs\cohera\Scripts\Activate.ps1

# torch d'abord, depuis l'index correspondant au backend voulu
pip install -r requirements/torch-cuda.txt     # ou torch-cpu.txt
pip install -e ".[dev]"
python -m spacy download fr_core_news_lg
```

## Bascules

| Bascule | Commande | Portée |
|---|---|---|
| Device torch | `$env:COHERA_DEVICE="cpu"` | instantanée, sans réinstallation |
| Roue torch | `cohera torch --backend cpu` | réinstalle torch depuis l'autre index |
| Fournisseur LLM | `cohera doctor --llm gemini`, `$env:COHERA_LLM="gemini"` | par appel ou par session |

Les valeurs par défaut sont dans `config/technique.yaml`. Les clés d'API ne s'y trouvent
jamais : seul le *nom* de la variable d'environnement qui les porte y figure.

## Pipeline complet, jusqu'au rapport final

```powershell
docker compose up -d                                             # Neo4j d'abord, tout en dépend
cohera doctor                                                    # 6/6 attendu

cohera graphe charger --jeu fixtures                              # segmente, extrait, charge le graphe
cohera detecter --jeu fixtures --llm local                        # cascade A→B→C, écrit rapport.json
cohera detecter --jeu fixtures --llm groq --rapport rapport_groq.json  # second profil, pour la bascule

cohera rapport --jeu fixtures --comparer rapport_groq.json `
               --profils evaluation/profils.json                  # écrit rapport.html

cohera evaluer --jeu fixtures                                    # précision, rappel, F1 vs label.json
```

`rapport.html` est la page finale : autonome (ouvrable hors ligne), avec bascule entre les
deux profils de jugement et le détail de chaque incohérence détectée. Un second appel
LLM n'est nécessaire que si le cache disque (`.cache/llm/`) ne contient pas déjà les
réponses ; `cohera rapport` seul, sans `--comparer`, se contente du profil local.

## Commandes

```
cohera doctor                  # vérifie Neo4j, spaCy, embeddings, NLI, LLM
cohera evaluer --jeu fixtures  # compare rapport.json à corpus/fixtures/label.json
cohera torch --backend cuda    # bascule la roue PyTorch
pytest                         # tests unitaires
docker compose up -d           # démarre Neo4j
```

## Documentation

- `CLAUDE.md` — invariants du projet et règles non négociables
- `docs/architecture.md` — architecture complète
- `docs/plan-1-semaine.md` — plan de la semaine et critères d'acceptation
- `corpus/fixtures/label.json` — vérité terrain, **en lecture seule**
