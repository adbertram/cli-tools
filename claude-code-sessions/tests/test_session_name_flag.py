"""Tests for the --session-name / -N flag and the shared resolve helpers."""
import pytest
import typer
from typer.testing import CliRunner

from claude_code_sessions_cli.commands import timeline as timeline_cmd
from claude_code_sessions_cli.commands import sessions as sessions_cmd
from claude_code_sessions_cli.commands import skills as skills_cmd
from claude_code_sessions_cli.commands.session_arg import (
    resolve_session_arg,
    require_session_arg,
)


class FakeClient:
    """Echoes resolution: records calls, returns 'id-for:<value>'."""

    def __init__(self):
        self.calls = []

    def resolve_session_id(self, identifier, project=None):
        self.calls.append((identifier, project))
        return f"id-for:{identifier}"


runner = CliRunner()


# ---- resolve_session_arg (optional) ----

def test_resolve_arg_session_id_routes_through_resolver():
    client = FakeClient()
    assert resolve_session_arg(client, "abc", None, project="P") == "id-for:abc"
    assert client.calls == [("abc", "P")]


def test_resolve_arg_session_name_routes_through_resolver():
    client = FakeClient()
    assert resolve_session_arg(client, None, "My Name", project="P") == "id-for:My Name"
    assert client.calls == [("My Name", "P")]


def test_resolve_arg_neither_returns_none_without_resolving():
    client = FakeClient()
    assert resolve_session_arg(client, None, None, project="P") is None
    assert client.calls == []


def test_resolve_arg_both_raises_usage_error():
    client = FakeClient()
    with pytest.raises(typer.BadParameter) as exc:
        resolve_session_arg(client, "abc", "My Name", project="P")
    assert "only one of --session-id / --session-name" in str(exc.value)
    assert client.calls == []


# ---- require_session_arg (mandatory) ----

def test_require_arg_resolves_provided_value():
    client = FakeClient()
    assert require_session_arg(client, None, "My Name") == "id-for:My Name"


def test_require_arg_neither_raises_usage_error():
    client = FakeClient()
    with pytest.raises(typer.BadParameter) as exc:
        require_session_arg(client, None, None)
    assert "provide a session" in str(exc.value)


def test_require_arg_both_raises_usage_error():
    client = FakeClient()
    with pytest.raises(typer.BadParameter):
        require_session_arg(client, "abc", "My Name")


# ---- CLI wiring (representative commands via CliRunner) ----

def _patch_client(monkeypatch, module, fake):
    monkeypatch.setattr(module, "get_client", lambda: fake)


def test_cli_session_name_long_flag_resolves(monkeypatch):
    """timeline get --session-name resolves and reaches get_timeline."""
    fake = FakeClient()
    seen = {}

    def fake_get_timeline(session_id, project, limit, **kwargs):
        seen["session_id"] = session_id
        seen["project"] = project
        return []

    fake.get_timeline = fake_get_timeline
    _patch_client(monkeypatch, timeline_cmd, fake)

    result = runner.invoke(
        timeline_cmd.app,
        ["get", "--session-name", "My Session", "--project", "P"],
    )
    assert result.exit_code == 0, result.output
    assert seen["session_id"] == "id-for:My Session"
    assert fake.calls == [("My Session", "P")]


def test_cli_session_name_short_flag_resolves(monkeypatch):
    """-N short flag works on an optional-filter command (skills list)."""
    fake = FakeClient()
    fake.list_skills = lambda **kwargs: []
    _patch_client(monkeypatch, skills_cmd, fake)

    result = runner.invoke(
        skills_cmd.app,
        ["list", "--project", "P", "-N", "My Session"],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls == [("My Session", "P")]


def test_cli_both_flags_is_usage_error(monkeypatch):
    """Passing --session-id and --session-name together errors, non-zero exit."""
    fake = FakeClient()
    fake.get_timeline = lambda **kwargs: []
    _patch_client(monkeypatch, timeline_cmd, fake)

    result = runner.invoke(
        timeline_cmd.app,
        [
            "consolidated",
            "--session-id", "abc",
            "--session-name", "My Session",
            "--project", "P",
        ],
    )
    assert result.exit_code != 0
    assert fake.calls == []  # never resolved either


def test_cli_required_session_missing_is_error(monkeypatch):
    """timeline consolidated with no session source errors, non-zero exit."""
    fake = FakeClient()
    fake.get_timeline = lambda **kwargs: []
    _patch_client(monkeypatch, timeline_cmd, fake)

    result = runner.invoke(timeline_cmd.app, ["consolidated", "--project", "P"])
    assert result.exit_code != 0
    assert fake.calls == []


def test_cli_positional_still_works(monkeypatch):
    """sessions get still accepts a positional id/name via the resolver."""
    fake = FakeClient()

    class FakeSession:
        def model_dump(self):
            return {"id": "id-for:abc"}

    fake.get_session = lambda session_id: FakeSession()
    _patch_client(monkeypatch, sessions_cmd, fake)

    result = runner.invoke(sessions_cmd.app, ["get", "abc"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [("abc", None)]


def test_cli_optional_filter_defaults_to_none(monkeypatch):
    """skills list with no session flag does not call the resolver."""
    fake = FakeClient()
    fake.list_skills = lambda **kwargs: []
    _patch_client(monkeypatch, skills_cmd, fake)

    result = runner.invoke(skills_cmd.app, ["list", "--project", "P"])
    assert result.exit_code == 0, result.output
    assert fake.calls == []
