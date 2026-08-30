"""Le harnais de tests, déclaré comme un **paquet** et non comme un simple dossier.

Motif, mesuré : plusieurs bibliothèques scientifiques publient un paquet `tests` de premier
niveau dans `site-packages` — `ultralytics` le fait. Un dossier `tests/` sans `__init__.py`
n'est qu'une *portion* d'espace de noms : l'import s'y arrête pas, il continue le long de
`sys.path` et tombe sur le paquet régulier de la bibliothèque, qui gagne. Les quatre
modules qui écrivent `from tests.conftest import ...` ou `from tests.test_llm_client import
...` cessent alors d'être importables, et la collecte s'interrompt avant le premier test.

Ce fichier rend `tests` régulier, donc prioritaire : la racine du dépôt vient avant
`site-packages` dans `sys.path`.
"""
