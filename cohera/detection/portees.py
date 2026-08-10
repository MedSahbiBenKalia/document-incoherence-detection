"""Test de recouvrement des portées.

Sans lui, N01 devient un faux positif : mêmes clés, valeurs différentes, mais la
portée de D2 §4.6 est incluse dans celle de D1 §4.2 avec une contrainte plus
stricte — c'est une spécialisation compatible, pas une contradiction."""
