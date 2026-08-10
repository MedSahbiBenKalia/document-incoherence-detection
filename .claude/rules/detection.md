---
paths:
  - "cohera/detection/**/*.py"
  - "cohera/ciblage/**/*.py"
---

# Règles de détection

- Avant tout verdict de divergence de valeurs, appeler le test de recouvrement des portées.
  Quatre cas : IDENTIQUE → contradiction · DISJOINTE → rien · INCLUSION + plus strict →
  `SPECIALISE` · INCLUSION + plus permissif → contradiction.
- « Plus strict » se lit dans `config/registre_grandeurs.yaml`, jamais en dur.
  Pour `delai`, plus petit ; pour `duree_conservation`, plus grand.
- En cas de doute, un détecteur **escalade**, il ne rejette pas. Un rejet est définitif
  et silencieux ; une escalade reste visible.
- Toute paire écartée par un filtre est journalisée avec son motif.