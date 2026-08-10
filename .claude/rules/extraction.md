---
paths:
  - "cohera/extraction/**/*.py"
  - "config/*.yaml"
---

# Règles d'extraction

- Toute grandeur extraite porte `dimension`, `role`, `valeur_si` et `monotonie`.
  Une grandeur sans monotonie fait échouer le chargement de la configuration.
- `source_extraction` trace la provenance champ par champ (`REGLE` ou `LLM`).
  Un détecteur symbolique ne rend un verdict ferme que si tous les champs comparés
  viennent de `REGLE`.
- Les expressions vagues (`dans la semaine`, `sous quinzaine`, `sans délai`) produisent
  une grandeur avec le drapeau `IMPRECIS`, jamais `null`.
- `bimensuel` / `bimestriel` : ne jamais trancher silencieusement, produire `AMBIGU`.
- Jours ouvrés : stocker `valeur_si` (nominale) ET `valeur_si_calendaire`.