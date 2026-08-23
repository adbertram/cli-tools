"""Tests for `airtable records delete` confirmation behavior.

Regression coverage for the non-interactive (no-TTY) bug: invoking a destructive
command from an agent's Bash tool (stdin is not a terminal) without ``--yes``
used to block on an unanswerable ``typer.confirm`` prompt, hit EOF, and print a
bare ``Error:`` with exit 1. It must instead fail fast with a clear, actionable
message and never reach the API client. ``--yes`` must still delete.
"""
import typer
from typer.testing import CliRunner

from airtable_cli.commands import records


runner = CliRunner()


class _ClientShouldNotRun:
    def delete_record(self, *args, **kwargs):
        raise AssertionError("client.delete_record must not run without confirmation")


class _RecordingClient:
    def __init__(self):
        self.calls = []

    def delete_record(self, base_id, table_id, record_id):
        self.calls.append((base_id, table_id, record_id))
        return {"deleted": True, "id": record_id}


def test_records_delete_non_tty_without_yes_refuses_clearly(monkeypatch):
    """No TTY + no --yes: clear refusal, exit 1, no prompt, no API call, no bare Error:.

    CliRunner does not attach a real terminal to stdin, so this reproduces the
    agent/non-interactive context that triggered the original bug.
    """
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(records, "get_client", lambda: _ClientShouldNotRun())

    result = runner.invoke(
        records.app,
        ["delete", "Feedback", "recABC", "--base", "appBase"],
    )

    assert result.exit_code == 1
    # Actionable message naming the action and the remedy.
    assert "Refusing to delete record recABC without confirmation." in result.stderr
    assert "Re-run with --yes in non-interactive contexts." in result.stderr
    # The interactive prompt must never have been emitted.
    assert "Are you sure" not in result.stdout
    assert "Are you sure" not in result.stderr
    # And never a bare "Error:" with no detail.
    assert "Error:\n" not in result.stderr
    assert result.stderr.strip() != "Error:"


def test_records_delete_with_yes_skips_confirmation_and_deletes(monkeypatch):
    """--yes proceeds without prompting and calls the delete API."""
    client = _RecordingClient()
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(records, "get_client", lambda: client)

    result = runner.invoke(
        records.app,
        ["delete", "Feedback", "recABC", "--base", "appBase", "--yes"],
    )

    assert result.exit_code == 0, result.stderr
    assert client.calls == [("appBase", "Feedback", "recABC")]
    assert "Are you sure" not in result.stdout
    assert "Refusing to delete" not in result.stderr


def test_records_delete_interactive_decline_exits_zero(monkeypatch):
    """Interactive decline cancels cleanly with exit 0 and no error.

    Forcing the interactive branch (stdin is a TTY) and answering "no" must
    produce a clean cancellation, not the ``Error: 0`` that resulted when the
    cancel ``typer.Exit(0)`` was swallowed by the broad ``except Exception``.
    """
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(records, "get_client", lambda: _ClientShouldNotRun())
    # Pretend stdin is an interactive terminal so confirm() actually prompts.
    monkeypatch.setattr(
        "cli_tools_shared.output._stdin_is_interactive_tty", lambda: True
    )

    result = runner.invoke(
        records.app,
        ["delete", "Feedback", "recABC", "--base", "appBase"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert "Cancelled" in result.stderr
    assert "Error:" not in result.stderr
