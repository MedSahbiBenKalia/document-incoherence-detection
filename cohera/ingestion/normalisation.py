"""Normalisation du texte brut.

Doit préserver la correspondance des offsets avec le texte d'origine :
`texte_origine[debut:fin] == texte_source` pour toute clause. Perdre cet
alignement est irréparable en aval — toutes les preuves du rapport seraient
décalées."""
