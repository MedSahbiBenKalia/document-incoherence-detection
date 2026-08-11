"""`cohera extraire` — extraction par règles du J2, sur le modèle de test_cli_corpus.py."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cohera.cli import app

runner = CliRunner()


def test_l_extraction_passe_en_muet() -> None:
    resultat = runner.invoke(app, ["extraire", "--jeu", "fixtures", "--muet"])
    assert resultat.exit_code == 0, resultat.output


def test_la_sortie_json_donne_la_frame_d_une_clause_connue() -> None:
    resultat = runner.invoke(app, ["extraire", "--jeu", "fixtures", "--json"])
    assert resultat.exit_code == 0, resultat.output

    frames = json.loads(resultat.output)
    frame = frames["D1::S5::C01"]  # D1 §5.1 : « doit être renouvelé tous les trimestres »
    assert frame["modalite"] == "OBLIGATION"
    assert frame["quantites"][0]["role"] == "periodicite"


def test_un_jeu_inconnu_echoue_sans_trace_python() -> None:
    resultat = runner.invoke(app, ["extraire", "--jeu", "inexistant"])
    assert resultat.exit_code == 1
    assert "inexistant" in resultat.output


def test_le_filtre_document_ne_montre_qu_un_document() -> None:
    resultat = runner.invoke(app, ["extraire", "--document", "D1"])
    assert resultat.exit_code == 0, resultat.output
    assert "PR-QSE-04" in resultat.output
    assert "POL-SEC-01" not in resultat.output


def test_le_tableau_par_defaut_montre_la_couverture_par_champ() -> None:
    resultat = runner.invoke(app, ["extraire", "--document", "D1"])
    assert resultat.exit_code == 0, resultat.output
    assert "quantites" in resultat.output
    assert "modalite" in resultat.output
