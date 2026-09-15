"""Contract tests: every command group is mounted and its options exist."""
import json

import pytest
from typer.testing import CliRunner

from deepseek_sessions_cli import client as client_module
from deepseek_sessions_cli import config as config_module
from deepseek_sessions_cli.commands import sessions as sessions_commands
from deepseek_sessions_cli.main import app
from conftest import PROJECT_KEY

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


def test_impossible_missing_field_filter_skips_session_scan(cli, monkeypatch):
    class NoScanClient:
        def list_sessions(self, **_kwargs):
            raise AssertionError("session scan ran")

    monkeypatch.setattr(sessions_commands, "get_client", lambda: NoScanClient())

    payload = json.loads(
        invoke(
            [
                "sessions",
                "list",
                "--limit",
                "5",
                "--filter",
                "name:eq:__zzz_nonexistent_xyzzy__",
            ]
        ).output
    )

    assert payload == []


OLDEST_ROOT_SESSION = "session-11111111-1111-4111-8111-111111111111"


def test_id_filter_with_limit_one_returns_non_newest_session(cli):
    # agent-issues #584: the compacted session is newest, so a pre-fix
    # limit-before-filter run returned [] for this older id.
    payload = json.loads(
        invoke([
            "sessions", "list",
            "--filter", f"id:eq:{OLDEST_ROOT_SESSION}",
            "--properties", "id,last_activity",
            "--limit", "1",
        ]).output
    )
    assert [row["id"] for row in payload] == [OLDEST_ROOT_SESSION]
    assert payload[0]["last_activity"]


def test_id_filter_opens_only_the_named_session_log(cli, sessions_root, monkeypatch):
    opened = []
    real_load_log = client_module.load_log

    def recording_load_log(log_path):
        opened.append(log_path)
        return real_load_log(log_path)

    monkeypatch.setattr(client_module, "load_log", recording_load_log)

    payload = json.loads(
        invoke(["sessions", "list", "--filter", f"id:eq:{OLDEST_ROOT_SESSION}", "--properties", "id"]).output
    )

    assert payload == [{"id": OLDEST_ROOT_SESSION}]
    assert opened == [sessions_root / PROJECT_KEY / OLDEST_ROOT_SESSION / "session.jsonl.zstd"]


def test_id_filter_for_unknown_id_returns_empty(cli):
    payload = json.loads(
        invoke(["sessions", "list", "--filter", "id:eq:session-99999999-9999-4999-8999-999999999999"]).output
    )
    assert payload == []


def test_exact_session_ids_bounds_only_fully_pinned_filters():
    assert sessions_commands.exact_session_ids([f"id:eq:{OLDEST_ROOT_SESSION}"]) == [OLDEST_ROOT_SESSION]
    assert sessions_commands.exact_session_ids([f"id:{OLDEST_ROOT_SESSION}"]) == [OLDEST_ROOT_SESSION]
    assert sessions_commands.exact_session_ids(
        [f"id:eq:{OLDEST_ROOT_SESSION},turn_count:gte:1", "id:eq:session-x"]
    ) == [OLDEST_ROOT_SESSION, "session-x"]
    assert sessions_commands.exact_session_ids(["turn_count:gte:1"]) is None
    assert sessions_commands.exact_session_ids([f"id:eq:{OLDEST_ROOT_SESSION}", "turn_count:gte:1"]) is None
    assert sessions_commands.exact_session_ids([f"id:contains:{OLDEST_ROOT_SESSION[:12]}"]) is None


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
