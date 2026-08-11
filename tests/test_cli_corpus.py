"""`cohera corpus verifier` — la commande qui montre le tableau quand un compte ne tombe pas.

C'est aussi elle qui donne la correspondance « numéro de paragraphe → clause_id » que
`label.json` annonce dans sa note de lecture.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cohera.cli import app

runner = CliRunner()


def test_la_verification_du_corpus_passe() -> None:
    resultat = runner.invoke(app, ["corpus", "verifier", "--jeu", "fixtures", "--muet"])
    assert resultat.exit_code == 0, resultat.output
    assert "Segmentation conforme" in resultat.output
    assert "41 clauses / 41 attendues" in resultat.output
    assert "37 clauses / 37 attendues" in resultat.output


def test_la_sortie_json_donne_la_correspondance_vers_les_clause_id() -> None:
    resultat = runner.invoke(app, ["corpus", "verifier", "--jeu", "fixtures", "--json"])
    assert resultat.exit_code == 0, resultat.output

    controles = json.loads(resultat.output)
    assert controles["echecs"] == []
    assert controles["refs_manquantes"] == []
    assert controles["correspondance"]["D1 §9.2"] == "D1::S9::C02"
    assert {d["doc_id"]: d["clauses"] for d in controles["documents"]} == {"D1": 41, "D2": 37}


def test_un_jeu_inconnu_echoue_sans_trace_python() -> None:
    resultat = runner.invoke(app, ["corpus", "verifier", "--jeu", "inexistant"])
    assert resultat.exit_code == 1
    assert "inexistant" in resultat.output


def test_le_tableau_montre_l_origine_de_chaque_clause() -> None:
    resultat = runner.invoke(app, ["corpus", "verifier", "--document", "D1"])
    assert resultat.exit_code == 0
    assert "TABLEAU" in resultat.output
    assert "LISTE" in resultat.output
