"""Tests for the shared reactive prompt helpers (``prompt_secret`` / ``prompt_text``).

These are the single centralized entry points for non-login, in-flow prompts so
individual CLIs never call ``typer.prompt()`` / ``input()`` directly (enforced by
the fleet ``test_no_direct_prompting`` compliance test). The behavior that matters:
hidden input for secrets, TTY-gating that fails loud instead of blocking on EOF,
and whitespace-stripped results.
"""
import pytest

from cli_tools_shared import output
from cli_tools_shared.exceptions import ClientError


def _set_tty(monkeypatch, value):
    monkeypatch.setattr(output, "_stdin_is_interactive_tty", lambda: value)


# ---- prompt_secret --------------------------------------------------------

def test_prompt_secret_returns_stripped_value(monkeypatch):
    _set_tty(monkeypatch, True)
    captured = {}

    def fake_prompt(label, **kwargs):
        captured["label"] = label
        captured["kwargs"] = kwargs
        return "  123 "

    monkeypatch.setattr("typer.prompt", fake_prompt)
    assert output.prompt_secret("Enter CVV") == "123"
    # Required secret: hidden input, and no blank default (so empty re-prompts).
    assert captured["kwargs"].get("hide_input") is True
    assert "default" not in captured["kwargs"]


def test_prompt_secret_allow_empty_permits_skip(monkeypatch):
    _set_tty(monkeypatch, True)
    captured = {}

    def fake_prompt(label, **kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr("typer.prompt", fake_prompt)
    assert output.prompt_secret("Enter CVV", allow_empty=True) == ""
    # Optional secret: blank default + hidden + no echoed default.
    assert captured.get("default") == ""
    assert captured.get("hide_input") is True
    assert captured.get("show_default") is False


def test_prompt_secret_non_interactive_raises_and_never_prompts(monkeypatch):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr("typer.prompt", lambda *a, **k: pytest.fail("must not prompt without a TTY"))
    with pytest.raises(ClientError):
        output.prompt_secret("Enter CVV")


def test_prompt_secret_non_interactive_uses_custom_message(monkeypatch):
    _set_tty(monkeypatch, False)
    with pytest.raises(ClientError) as exc:
        output.prompt_secret("Enter CVV", non_interactive_message="run checkout in a real terminal")
    assert "run checkout in a real terminal" in str(exc.value)


# ---- prompt_text ----------------------------------------------------------

def test_prompt_text_returns_stripped_value(monkeypatch):
    _set_tty(monkeypatch, True)
    monkeypatch.setattr("typer.prompt", lambda label, **k: "  amex-personal  ")
    assert output.prompt_text("Name this card") == "amex-personal"


def test_prompt_text_passes_default(monkeypatch):
    _set_tty(monkeypatch, True)
    captured = {}

    def fake_prompt(label, **kwargs):
        captured.update(kwargs)
        return "fallback"

    monkeypatch.setattr("typer.prompt", fake_prompt)
    assert output.prompt_text("Name this card", default="fallback") == "fallback"
    assert captured.get("default") == "fallback"


def test_prompt_text_non_interactive_raises(monkeypatch):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr("typer.prompt", lambda *a, **k: pytest.fail("must not prompt without a TTY"))
    with pytest.raises(ClientError):
        output.prompt_text("Name this card")
