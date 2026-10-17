"""Command-level unit tests for atlas-capture (refusal stub + JSON contract).

Uses typer's CliRunner so no browser or live site is touched.
"""

from __future__ import annotations

from typer.testing import CliRunner

from atlas_capture_cli import main as main_mod
from atlas_capture_cli.browser import _extract_code
from atlas_capture_cli import parsers

runner = CliRunner()


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def list_tasks(self, limit: int = 100):
        return self.rows

    def close(self):
        self.closed = True


def test_tasks_list_empty_outputs_json_array(monkeypatch):
    fake = _FakeClient([])
    monkeypatch.setattr(main_mod, "get_client", lambda: fake)
    result = runner.invoke(main_mod.app, ["tasks", "list"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "[]"
    assert fake.closed


def test_tasks_apply_always_refuses(monkeypatch):
    # Even with --confirm, apply must refuse and never touch a client.
    def boom():
        raise AssertionError("apply must not construct a client")

    monkeypatch.setattr(main_mod, "get_client", boom)
    result = runner.invoke(main_mod.app, ["tasks", "apply", "abc123", "--confirm"])
    assert result.exit_code == 1
    assert "does not apply to tasks" in result.stderr
    assert "abc123" in result.stderr


def test_account_show_emits_record_fields(monkeypatch):
    fake_rows = parsers.normalize_user_me({
        "id": "u1", "email": "a@b.c", "firstName": "A", "lastName": "B",
        "onboardingCompleted": True, "onboardingStep": 4,
        "gtProbationCompleted": False,
    })
    monkeypatch.setattr(main_mod, "get_client",
                        lambda: type("C", (), {
                            "account": lambda self: fake_rows,
                            "close": lambda self: None})())

    result = runner.invoke(main_mod.app, ["account", "show"])
    assert result.exit_code == 0, result.output
    assert '"email": "a@b.c"' in result.stdout
    assert '"onboarding_completed": true' in result.stdout


def test_extract_code_returns_isolated_six_digits():
    assert _extract_code("Your code is 123456. It expires soon.") == "123456"
    assert _extract_code("123456") == "123456"
    # Embedded-in-longer-number digits are not a code; None means no code.
    assert _extract_code("reference 1234567 has no code") is None
    assert _extract_code("no digits here") is None
    assert _extract_code("") is None
