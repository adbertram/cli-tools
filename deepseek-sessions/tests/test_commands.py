"""Contract tests: every command group is mounted and its options exist."""
import json

import pytest
from typer.testing import CliRunner

from deepseek_sessions_cli import client as client_module
from deepseek_sessions_cli import config as config_module
from deepseek_sessions_cli.main import app

runner = CliRunner()

# Every group the CLI promises, and whether its list command is project-scoped.
GROUPS = {
    "projects": False,
    "sessions": False,
    "conversations": True,
    "subagent-activity": True,
    "tool-calls": True,
    "todos": True,
    "skills": True,
    "timeline": True,
    "turns": True,
    "retries": True,
    "approvals": True,
    "goals": True,
}


@pytest.fixture
def cli(monkeypatch, sessions_root, simple_log, subagent_pair, compacted_log):
    """Point the CLI at the synthetic dsh home and reset the singletons."""
    monkeypatch.setenv("DSH_HOME", str(sessions_root.parent))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return runner


def invoke(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, f"{args} failed:\n{result.output}"
    return result


def test_every_group_is_mounted(cli):
    output = invoke(["--help"]).output
    for group in GROUPS:
        assert group in output, f"{group} missing from --help"
    assert "auth" in output


@pytest.mark.parametrize("group", sorted(GROUPS))
def test_list_commands_expose_the_required_options(cli, group):
    """cli-tools requires --table, --limit, --filter, --properties on every list."""
    output = invoke([group, "list", "--help"]).output
    for option in ("--table", "--limit", "--filter", "--properties"):
        assert option in output, f"{group} list is missing {option}"


@pytest.mark.parametrize("group", sorted(GROUPS))
def test_get_commands_expose_table(cli, group):
    assert "--table" in invoke([group, "get", "--help"]).output


@pytest.mark.parametrize("group, scoped", sorted(GROUPS.items()))
def test_list_commands_emit_json(cli, group, scoped):
    args = [group, "list"] + (["--project", "demo"] if scoped else [])
    payload = json.loads(invoke(args).output)
    assert isinstance(payload, list)


@pytest.mark.parametrize("group, scoped", sorted(GROUPS.items()))
def test_list_commands_render_tables(cli, group, scoped):
    args = [group, "list", "--table"] + (["--project", "demo"] if scoped else [])
    invoke(args)
    invoke(args + ["--wide"])


def test_search_run_emits_json(cli):
    payload = json.loads(invoke(["search", "run", "do the thing"]).output)
    assert payload[0]["session_id"].startswith("session-1111")


def test_auth_status_uses_the_shared_profile_shape(cli):
    payload = json.loads(invoke(["auth", "status"]).output)
    profile = payload["profiles"][0]
    assert profile["authenticated"] is True
    assert "credential_types" in profile


def test_properties_selects_fields(cli):
    payload = json.loads(invoke(["sessions", "list", "--properties", "id,project"]).output)
    assert set(payload[0]) == {"id", "project"}


def test_filter_narrows_rows(cli):
    payload = json.loads(
        invoke(["sessions", "list", "--filter", "origin:eq:subagent"]).output
    )
    assert payload
    assert all(row["origin"] == "subagent" for row in payload)


def test_limit_caps_rows(cli):
    assert len(json.loads(invoke(["sessions", "list", "--limit", "1"]).output)) == 1


def test_mutually_exclusive_date_selectors_are_rejected(cli):
    result = runner.invoke(
        app, ["sessions", "list", "--date", "2026-08-19", "--date-alias", "today"]
    )
    assert result.exit_code != 0
    assert "only one of" in result.output.lower()


def test_session_id_and_name_are_mutually_exclusive(cli):
    result = runner.invoke(
        app, ["sessions", "get", "some-id", "--session-name", "Demo session"]
    )
    assert result.exit_code != 0


def test_session_can_be_addressed_by_title(cli):
    payload = json.loads(invoke(["sessions", "get", "Demo session"]).output)
    assert payload["id"] == "session-11111111-1111-4111-8111-111111111111"


def test_unknown_project_exits_non_zero(cli):
    result = runner.invoke(app, ["tool-calls", "list", "--project", "absent"])
    assert result.exit_code != 0


def test_conversations_get_accepts_colon_form(cli, compacted_log):
    payload = json.loads(invoke(["conversations", "get", f"{compacted_log}:2"]).output)
    assert payload["conversation_id"] == 2
    assert payload["started_by"] == "compaction"


def test_timeline_consolidated_includes_subagents(cli, subagent_pair):
    parent_id, child_id = subagent_pair
    payload = json.loads(
        invoke(["timeline", "consolidated", "--session-id", parent_id]).output
    )
    assert any(row["agent_id"] == child_id for row in payload)

    hidden = json.loads(
        invoke(
            ["timeline", "consolidated", "--session-id", parent_id, "--hide-agent-tools"]
        ).output
    )
    assert all(row["event_type"] != "subagent_tool" for row in hidden)
