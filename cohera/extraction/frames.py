"""Schéma pydantic de la Clause Frame et fusion règles/LLM.

Invariant : la fusion se fait ICI, côté Python. Le LLM ne remplit que les
champs laissés `null` par les règles — jamais par consigne au modèle."""
