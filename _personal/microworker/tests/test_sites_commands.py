"""`sites list` / `sites get` against the fixture config.json."""

from __future__ import annotations

import json

from conftest import SITES, write_config
from microworker_cli.main import app


def test_list_rows_mirror_config(project, runner):
    outcome = runner.invoke(app, ["sites", "list"])
    assert outcome.exit_code == 0, outcome.output
    rows = json.loads(outcome.stdout)
    assert [row["name"] for row in rows] == list(SITES)
    assert rows[0] == {"name": "taskerdata", **SITES["taskerdata"]}


def test_list_filter_limit_properties(project, runner):
    outcome = runner.invoke(app, ["sites", "list", "--filter", "account:eq:true",
                                  "--limit", "2", "--properties", "name,cli"])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout) == [
        {"name": "taskerdata", "cli": "taskerdata"},
        {"name": "microworkers", "cli": "microworkers"},
    ]


def test_list_table(project, runner):
    outcome = runner.invoke(app, ["sites", "list", "--table", "--limit", "1"])
    assert outcome.exit_code == 0, outcome.output
    assert "taskerdata" in outcome.stdout and "Lastpass Item" in outcome.stdout


def test_list_bad_filter_exits_nonzero(project, runner):
    outcome = runner.invoke(app, ["sites", "list", "--filter", "nonsense"])
    assert outcome.exit_code != 0


def test_get(project, runner):
    outcome = runner.invoke(app, ["sites", "get", "oneforma"])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout) == {"name": "oneforma", **SITES["oneforma"]}


def test_get_properties_and_table(project, runner):
    outcome = runner.invoke(app, ["sites", "get", "oneforma", "--properties", "cli", "--table"])
    assert outcome.exit_code == 0, outcome.output
    assert "cli" in outcome.stdout and "None" in outcome.stdout


def test_get_unknown_exits_2(project, runner):
    outcome = runner.invoke(app, ["sites", "get", "nope"])
    assert outcome.exit_code == 2, outcome.output
    assert "unknown site 'nope'" in outcome.output


def test_unexpected_key_is_config_error(project, runner, tmp_path):
    sites = dict(SITES)
    sites["toloka"] = dict(sites["toloka"], extra=True)
    write_config(tmp_path, sites)
    outcome = runner.invoke(app, ["sites", "list"])
    assert outcome.exit_code == 2, outcome.output
    assert "unexpected keys: extra" in outcome.output


def test_wrong_type_is_config_error(project, runner, tmp_path):
    sites = dict(SITES)
    sites["toloka"] = dict(sites["toloka"], account="yes")
    write_config(tmp_path, sites)
    outcome = runner.invoke(app, ["sites", "list"])
    assert outcome.exit_code == 2, outcome.output
    assert "'account' must be bool" in outcome.output


def test_missing_config_file_is_config_error(tmp_path, monkeypatch, runner):
    monkeypatch.setenv("MICROWORKER_ROOT", str(tmp_path))
    outcome = runner.invoke(app, ["sites", "list"])
    assert outcome.exit_code == 2, outcome.output
    assert "config.json not found" in outcome.output
