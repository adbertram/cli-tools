"""Tests for the shared destructive-action confirmation helper and the
non-empty error-message guard in print_error.

These cover the single confirmation path used by every destructive CLI command:
``--yes`` skips the prompt, a non-interactive stdin fails fast with an
actionable message (instead of blocking and printing a bare ``Error:``), and an
interactive decline cancels cleanly.
"""
import click
import pytest
import typer

from cli_tools_shared import confirm_destructive_action
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared import output


def test_assume_yes_skips_prompt(monkeypatch):
    """assume_yes=True returns without prompting or refusing, even with no TTY."""
    monkeypatch.setattr(output, "_stdin_is_interactive_tty", lambda: False)
    # typer.confirm must never be called.
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: pytest.fail("must not prompt"))

    # Returns None without raising.
    assert confirm_destructive_action(
        "Delete it?", assume_yes=True, action_description="delete thing"
    ) is None


def test_non_tty_refuses_fast_with_actionable_message(monkeypatch):
    """Non-interactive stdin + no assume_yes: raise ClientError, never prompt."""
    monkeypatch.setattr(output, "_stdin_is_interactive_tty", lambda: False)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: pytest.fail("must not prompt"))

    with pytest.raises(ClientError) as excinfo:
        confirm_destructive_action(
            "Delete record recABC?",
            assume_yes=False,
            action_description="delete record recABC",
        )

    message = str(excinfo.value)
    assert "Refusing to delete record recABC without confirmation." in message
    assert "Re-run with --yes in non-interactive contexts." in message


def test_interactive_accept_proceeds(monkeypatch):
    """Interactive TTY + user confirms: return without raising."""
    monkeypatch.setattr(output, "_stdin_is_interactive_tty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)

    assert confirm_destructive_action(
        "Delete it?", assume_yes=False, action_description="delete thing"
    ) is None


def test_interactive_decline_exits_zero(monkeypatch):
    """Interactive TTY + user declines: clean typer.Exit(0), not an error."""
    monkeypatch.setattr(output, "_stdin_is_interactive_tty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: False)

    with pytest.raises(typer.Exit) as excinfo:
        confirm_destructive_action(
            "Delete it?", assume_yes=False, action_description="delete thing"
        )

    assert excinfo.value.exit_code == 0


def test_print_error_never_bare_for_empty_message(capsys):
    """An empty message must not produce a bare 'Error:' line."""
    output.print_error("")
    captured = capsys.readouterr()
    line = captured.err.strip()
    assert line != "Error:"
    assert line.startswith("Error:")
    assert len(line) > len("Error:")


def test_handle_error_uses_fallback_for_empty_exception(capsys):
    """click.Abort carries an empty str(); handle_error must still print detail."""
    rc = output.handle_error(click.exceptions.Abort())
    captured = capsys.readouterr()
    line = captured.err.strip()
    assert rc == 1
    assert line != "Error:"
    assert line.startswith("Error:")
    assert len(line) > len("Error:")
