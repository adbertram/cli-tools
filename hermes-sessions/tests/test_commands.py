"""CLI boundary tests: command contract, options, output shape, and errors."""
import json

import pytest
from typer.testing import CliRunner

from hermes_sessions_cli import client as client_module
from hermes_sessions_cli import config as config_module
from hermes_sessions_cli import state as state_module
from hermes_sessions_cli.main import app
from conftest import CHILD_SESSION, GATEWAY_SESSION, PROJECT_CWD, ROOT_SESSION

runner = CliRunner()

# Every group the CLI promises, and whether its list command needs a scope to
# produce rows in the fixture.
GROUPS = [
    "projects",
    "sessions",
    "conversations",
    "turns",
    "tool-calls",
    "todos",
    "skills",
    "subagent-activity",
    "timeline",
]
# Groups whose `get` takes a `<session>:<n>` style reference.
INDEXED_GETS = {"conversations": f"{ROOT_SESSION}:1", "turns": f"{ROOT_SESSION}:1",
                "todos": f"{ROOT_SESSION}:0"}


@pytest.fixture
def cli(hermes_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return runner


@pytest.fixture
def ambiguous_cli(ambiguous_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(ambiguous_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return runner


def invoke(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, f"{args} failed ({result.exit_code}):\n{result.output}"
    return result


def invoke_failing(args):
    result = runner.invoke(app, args)
    assert result.exit_code != 0, f"{args} unexpectedly succeeded:\n{result.output}"
    return result


class TestCommandContract:
    def test_every_group_is_mounted(self, cli):
        output = invoke(["--help"]).output
        for group in GROUPS + ["auth", "search"]:
            assert group in output, f"{group} missing from --help"

    @pytest.mark.parametrize("group", GROUPS)
    def test_list_commands_expose_the_required_options(self, cli, group):
        output = invoke([group, "list", "--help"]).output
        for option in ("--table", "--limit", "--filter", "--properties"):
            assert option in output, f"{group} list is missing {option}"

    @pytest.mark.parametrize("group", GROUPS)
    def test_get_commands_expose_table(self, cli, group):
        assert "--table" in invoke([group, "get", "--help"]).output

    def test_search_run_exposes_the_list_options(self, cli):
        output = invoke(["search", "run", "--help"]).output
        for option in ("--table", "--limit", "--properties"):
            assert option in output

    def test_timeline_exposes_a_consolidated_command(self, cli):
        assert "consolidated" in invoke(["timeline", "--help"]).output

    @pytest.mark.parametrize("verb", ["delete", "remove", "create", "update", "rename", "prune"])
    def test_no_mutation_commands_are_exposed(self, cli, verb):
        output = invoke(["--help"]).output
        assert verb not in output
        for group in GROUPS:
            assert verb not in invoke([group, "--help"]).output


class TestJsonOutput:
    def test_public_read_logs_the_store_and_queries(self, cli, hermes_home, monkeypatch):
        events = []

        class ActivityLogger:
            def info(self, message, *args):
                events.append(message % args)

        monkeypatch.setattr(state_module, "activity", ActivityLogger(), raising=False)

        rows = json.loads(invoke(["projects", "list", "--limit", "1"]).output)

        assert rows
        assert events[0] == f"Opened Hermes state store: {hermes_home / 'state.db'}"
        assert events[1:]
        assert set(events[1:]) == {"Hermes state query: SELECT"}

    @pytest.mark.parametrize("group", GROUPS)
    def test_list_commands_emit_a_json_array(self, cli, group):
        payload = json.loads(invoke([group, "list"]).output)
        assert isinstance(payload, list)

    @pytest.mark.parametrize("group", GROUPS)
    def test_list_commands_render_tables(self, cli, group):
        invoke([group, "list", "--table"])
        invoke([group, "list", "--table", "--wide"])

    def test_search_emits_a_json_array(self, cli):
        assert isinstance(json.loads(invoke(["search", "run", "nightly"]).output), list)

    def test_properties_selects_only_the_named_fields(self, cli):
        rows = json.loads(invoke(["sessions", "list", "--properties", "id,source"]).output)
        assert rows and all(set(row) == {"id", "source"} for row in rows)

    def test_limit_bounds_the_output(self, cli):
        assert len(json.loads(invoke(["sessions", "list", "--limit", "1"]).output)) == 1

    def test_a_filter_applies_after_a_wide_fetch(self, cli):
        rows = json.loads(invoke(["sessions", "list", "--limit", "1", "--filter", "source:eq:cli"]).output)
        assert [row["id"] for row in rows] == [ROOT_SESSION]

    def test_an_invalid_filter_is_rejected(self, cli):
        invoke_failing(["sessions", "list", "--filter", "not-a-filter"])


class TestScopingOptions:
    def test_project_scoping_by_name(self, cli):
        rows = json.loads(invoke(["sessions", "list", "--project", "demo"]).output)
        assert {row["id"] for row in rows} == {ROOT_SESSION, CHILD_SESSION}

    def test_project_scoping_by_absolute_path(self, cli):
        rows = json.loads(invoke(["sessions", "list", "--project", PROJECT_CWD]).output)
        assert {row["id"] for row in rows} == {ROOT_SESSION, CHILD_SESSION}

    def test_an_unknown_project_exits_non_zero(self, cli):
        invoke_failing(["sessions", "list", "--project", "does-not-exist"])

    def test_an_ambiguous_project_basename_exits_non_zero(self, ambiguous_cli):
        result = invoke_failing(["sessions", "list", "--project", "demo"])
        assert "ambiguous" in result.output

    def test_session_scoping_accepts_a_title(self, cli):
        rows = json.loads(invoke(["turns", "list", "--session-id", "Demo session"]).output)
        assert rows and all(row["session_id"] == ROOT_SESSION for row in rows)

    def test_session_id_and_session_name_are_mutually_exclusive(self, cli):
        result = invoke_failing(
            ["turns", "list", "--session-id", ROOT_SESSION, "--session-name", "Demo session"]
        )
        assert "only one of" in result.output

    def test_an_ambiguous_session_title_exits_non_zero(self, ambiguous_cli):
        result = invoke_failing(["turns", "list", "--session-name", "shared title"])
        assert "matches 2 sessions" in result.output

    def test_time_selectors_are_mutually_exclusive(self, cli):
        result = invoke_failing(["sessions", "list", "--since", "1d", "--date-alias", "today"])
        assert "only one of" in result.output

    @pytest.mark.parametrize(
        "args",
        [["--since", "5y"], ["--date", "2026-13-40"], ["--date-range", "2026-09-01"],
         ["--date-alias", "next_week"]],
    )
    def test_malformed_time_selectors_are_rejected(self, cli, args):
        invoke_failing(["sessions", "list", *args])

    def test_source_scoping(self, cli):
        rows = json.loads(invoke(["sessions", "list", "--source", "cron"]).output)
        assert [row["id"] for row in rows] == [GATEWAY_SESSION]

    def test_subagents_can_be_excluded(self, cli):
        rows = json.loads(invoke(["sessions", "list", "--no-subagents"]).output)
        assert CHILD_SESSION not in {row["id"] for row in rows}


class TestGetCommands:
    @pytest.mark.parametrize("group,reference", sorted(INDEXED_GETS.items()))
    def test_indexed_get_commands_return_one_record(self, cli, group, reference):
        record = json.loads(invoke([group, "get", reference]).output)
        assert record["session_id"] == ROOT_SESSION

    @pytest.mark.parametrize("group", sorted(INDEXED_GETS))
    def test_a_malformed_reference_exits_non_zero(self, cli, group):
        result = invoke_failing([group, "get", "no-index-here"])
        assert "Invalid reference" in result.output

    def test_sessions_get_returns_metadata_only(self, cli):
        record = json.loads(invoke(["sessions", "get", ROOT_SESSION]).output)
        assert "messages" not in record
        assert record["turn_count"] == 3

    def test_sessions_get_redacts_previews(self, cli):
        record = json.loads(invoke(["sessions", "get", ROOT_SESSION, "--max-chars", "500"]).output)
        assert "supersecretvalue" not in json.dumps(record)

    def test_projects_get_resolves_the_no_workspace_bucket(self, cli):
        record = json.loads(invoke(["projects", "get", "(no-workspace)"]).output)
        assert record["full_path"] is None

    def test_tool_calls_get_resolves_a_call_id(self, cli):
        record = json.loads(invoke(["tool-calls", "get", "call-3", "-S", ROOT_SESSION]).output)
        assert record["tool"] == "terminal"
        assert record["status"] == "error"

    def test_subagent_activity_get_resolves_a_child_session(self, cli):
        record = json.loads(invoke(["subagent-activity", "get", CHILD_SESSION]).output)
        assert record["parent_session"] == ROOT_SESSION

    def test_an_unknown_session_exits_non_zero(self, cli):
        invoke_failing(["sessions", "get", "no-such-session"])


class TestTimelineViews:
    def test_timeline_get_returns_the_session_events(self, cli):
        events = json.loads(invoke(["timeline", "get", ROOT_SESSION]).output)
        assert [event["index"] for event in events] == list(range(1, len(events) + 1))

    def test_errors_only_narrows_the_timeline(self, cli):
        events = json.loads(invoke(["timeline", "get", ROOT_SESSION, "--errors-only"]).output)
        assert events and all(
            event["status"] == "error" or event["event_type"] == "error" for event in events
        )

    def test_consolidated_merges_subagent_events(self, cli):
        events = json.loads(invoke(["timeline", "consolidated", ROOT_SESSION]).output)
        assert CHILD_SESSION in {event["subagent_session"] for event in events}

    def test_consolidated_is_bounded_by_limit(self, cli):
        events = json.loads(invoke(["timeline", "consolidated", ROOT_SESSION, "--limit", "2"]).output)
        assert len(events) == 2

    def test_consolidated_summaries_are_bounded_by_max_chars(self, cli):
        events = json.loads(
            invoke(["timeline", "consolidated", ROOT_SESSION, "--max-chars", "12"]).output
        )
        assert all(len(event["summary"]) <= 12 for event in events if event["summary"])

    def test_consolidated_requires_a_session(self, cli):
        result = invoke_failing(["timeline", "consolidated"])
        assert "provide a session" in result.output


class TestAuthAndMissingState:
    def test_auth_status_reports_readable_local_state(self, cli):
        payload = json.loads(invoke(["auth", "status"]).output)
        custom = payload["profiles"][0]["credential_types"]["custom"]
        assert custom["state_db_readable"] is True
        assert custom["api_test"] == "passed"

    def test_auth_status_reports_an_unreadable_store(self, missing_home, monkeypatch):
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(missing_home))
        monkeypatch.setattr(config_module, "_config", None)
        monkeypatch.setattr(client_module, "_client", None)
        result = runner.invoke(app, ["auth", "status"])
        payload = json.loads(result.output)
        custom = payload["profiles"][0]["credential_types"]["custom"]
        assert custom["state_db_readable"] is False
        assert custom["api_test"].startswith("failed")

    def test_a_missing_state_store_exits_non_zero_with_a_clear_message(self, missing_home, monkeypatch):
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(missing_home))
        monkeypatch.setattr(config_module, "_config", None)
        monkeypatch.setattr(client_module, "_client", None)
        result = runner.invoke(app, ["sessions", "list"])
        assert result.exit_code != 0
        assert "Hermes state store not found" in result.output

    def test_an_empty_state_store_lists_nothing(self, empty_home, monkeypatch):
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(empty_home))
        monkeypatch.setattr(config_module, "_config", None)
        monkeypatch.setattr(client_module, "_client", None)
        result = runner.invoke(app, ["sessions", "list"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []


# Commands that would write credentials, profiles, or Hermes state. `test` is
# here too: it is not a mutation itself, but it drives the shared credential
# verification flow that this read-only CLI has no business exposing.
FORBIDDEN_COMMAND_NAMES = {
    "add", "archive", "clear", "create", "delete", "edit", "fork", "import",
    "login", "logout", "move", "prune", "purge", "refresh", "remove", "rename",
    "reset", "restore", "revoke", "select", "set", "test", "update", "write",
}
# The complete read-only surface. Anything outside this set is a regression,
# even if its name is not on the forbidden list above.
ALLOWED_LEAF_COMMANDS = {"status", "list", "get", "search", "consolidated", "run"}


def _walk_command_tree(typer_app, prefix=()):
    """Yield (path, name) for every command in the app, at any depth."""
    for command in typer_app.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        yield prefix + (name,), name
    for group in typer_app.registered_groups:
        group_name = group.name or group.typer_instance.info.name
        yield prefix + (group_name,), group_name
        yield from _walk_command_tree(group.typer_instance, prefix + (group_name,))


class TestNoMutationCommandsAnywhere:
    """The whole recursive tree must stay read-only, auth included."""

    def test_the_command_tree_exposes_no_mutation_command(self):
        offenders = [
            "/".join(path)
            for path, name in _walk_command_tree(app)
            if name in FORBIDDEN_COMMAND_NAMES
        ]
        assert offenders == [], f"mutation commands reachable: {offenders}"

    def test_every_leaf_command_is_on_the_read_only_allow_list(self):
        leaves = {
            name
            for path, name in _walk_command_tree(app)
            if name not in {group.name for group in app.registered_groups}
        }
        unexpected = sorted(leaves - ALLOWED_LEAF_COMMANDS)
        assert unexpected == [], f"unexpected commands outside the read-only surface: {unexpected}"

    def test_auth_exposes_status_and_nothing_else(self, cli):
        from hermes_sessions_cli.commands import auth as auth_commands

        names = [
            command.name or command.callback.__name__
            for command in auth_commands.app.registered_commands
        ]
        assert names == ["status"]
        assert auth_commands.app.registered_groups == []

    @pytest.mark.parametrize(
        "args",
        [
            ["auth", "login"],
            ["auth", "logout"],
            ["auth", "test"],
            ["auth", "profiles"],
            ["auth", "profiles", "list"],
            ["auth", "profiles", "create", "x"],
            ["auth", "profiles", "delete", "x"],
            ["auth", "profiles", "remove", "x"],
            ["auth", "profiles", "rename", "x", "y"],
            ["auth", "profiles", "select", "x"],
        ],
    )
    def test_removed_auth_commands_are_unreachable(self, cli, args):
        result = runner.invoke(app, args)
        assert result.exit_code != 0, f"{args} is still reachable:\n{result.output}"

    def test_auth_help_names_no_mutation_command(self, cli):
        output = invoke(["auth", "--help"]).output
        for verb in FORBIDDEN_COMMAND_NAMES | {"profiles"}:
            assert f" {verb} " not in output, f"auth --help still advertises {verb}"

    def test_auth_status_still_emits_the_shared_profile_contract(self, cli):
        payload = json.loads(invoke(["auth", "status"]).output)
        assert isinstance(payload.get("profiles"), list) and payload["profiles"]
        for entry in payload["profiles"]:
            for field in ("name", "auth_type", "active", "authenticated", "credential_types"):
                assert field in entry, f"auth status profile entry missing {field}"
        custom = payload["profiles"][0]["credential_types"]["custom"]
        assert custom["state_db_readable"] is True
        assert custom["api_test"] == "passed"

    def test_auth_status_keeps_its_profile_and_table_flags(self, cli):
        output = invoke(["auth", "status", "--help"]).output
        assert "--profile" in output
        assert "--table" in output
