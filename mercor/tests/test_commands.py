"""Command-contract unit tests for the mercor CLI (offline).

The `apply` command is a dry-run-only stub: no client and no network is ever
touched, so these tests exercise the guard paths without a browser.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from mercor_cli.main import app

runner = CliRunner()


def test_apply_refuses_without_confirm():
    result = runner.invoke(app, ["tasks", "apply", "list_abc"])
    assert result.exit_code == 1
    assert "Refusing to run 'mercor tasks apply' without --confirm" in result.stderr


def test_apply_with_confirm_is_still_dry_run():
    result = runner.invoke(
        app, ["tasks", "apply", "list_abc", "--confirm"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["task_id"] == "list_abc"
    assert payload["dry_run"] is True
    assert payload["applied"] is False


def test_apply_help_documents_never_used_stub():
    result = runner.invoke(app, ["tasks", "apply", "--help"])
    assert result.exit_code == 0
    assert "never applies" in result.stdout
    assert "--confirm" in result.stdout


def test_tasks_list_help_exposes_contract_options():
    result = runner.invoke(app, ["tasks", "list", "--help"])
    assert result.exit_code == 0
    for option in ("--table", "--limit", "--filter", "--properties", "--profile"):
        assert option in result.stdout
