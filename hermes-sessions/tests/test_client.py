"""Client tests against a synthetic Hermes state store."""
import sqlite3

import pytest
from cli_tools_shared.exceptions import ClientError

from hermes_sessions_cli import client as client_module
from hermes_sessions_cli import config as config_module
from hermes_sessions_cli.client import HermesSessionsClient
from hermes_sessions_cli.config import Config
from hermes_sessions_cli.parsers import NO_WORKSPACE
from conftest import CHILD_SESSION, GATEWAY_SESSION, PROJECT_CWD, ROOT_SESSION


@pytest.fixture
def client(hermes_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return HermesSessionsClient(config=Config())


@pytest.fixture
def ambiguous_client(ambiguous_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(ambiguous_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return HermesSessionsClient(config=Config())


class TestStateAccess:
    def test_missing_state_store_is_a_clear_error(self, missing_home, monkeypatch):
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(missing_home))
        with pytest.raises(ClientError, match="Hermes state store not found"):
            HermesSessionsClient(config=Config()).list_projects()

    def test_a_corrupt_state_store_reports_a_query_failure(self, tmp_path, monkeypatch):
        home = tmp_path / "corrupt"
        home.mkdir()
        (home / "state.db").write_bytes(b"this is not a sqlite database at all")
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(home))
        with pytest.raises(ClientError):
            HermesSessionsClient(config=Config()).list_projects()

    def test_a_store_missing_the_sessions_table_is_reported(self, tmp_path, monkeypatch):
        home = tmp_path / "wrong-schema"
        home.mkdir()
        connection = sqlite3.connect(home / "state.db")
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
        connection.commit()
        connection.close()
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(home))
        with pytest.raises(ClientError, match="no 'sessions' table"):
            HermesSessionsClient(config=Config()).list_sessions()

    def test_an_empty_store_returns_empty_lists(self, empty_home, monkeypatch):
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(empty_home))
        instance = HermesSessionsClient(config=Config())
        assert instance.list_projects() == []
        assert instance.list_sessions() == []
        assert instance.list_timeline() == []

    def test_the_store_is_opened_read_only(self, client):
        connection = client.store.connect()
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM sessions")


class TestProjects:
    def test_sessions_without_a_cwd_collect_in_one_bucket(self, client):
        names = {project.name for project in client.list_projects()}
        assert names == {"demo", NO_WORKSPACE}

    def test_subagent_sessions_are_counted_separately(self, client):
        demo = next(p for p in client.list_projects() if p.name == "demo")
        assert demo.session_count == 2
        assert demo.subagent_session_count == 1

    def test_a_project_resolves_by_name_and_by_absolute_path(self, client):
        assert client.get_project("demo").full_path == PROJECT_CWD
        assert client.get_project(PROJECT_CWD).name == "demo"

    def test_a_trailing_slash_resolves_to_the_same_project(self, client):
        assert client.get_project(PROJECT_CWD + "/").full_path == PROJECT_CWD

    def test_the_no_workspace_bucket_is_addressable(self, client):
        assert client.get_project(NO_WORKSPACE).full_path is None

    def test_an_unknown_project_is_rejected(self, client):
        with pytest.raises(ClientError, match="Unknown project"):
            client.get_project("nope")

    def test_a_blank_project_name_is_rejected(self, client):
        with pytest.raises(ClientError, match="project name is required"):
            client.get_project("   ")

    def test_a_basename_shared_by_two_workspaces_is_ambiguous(self, ambiguous_client):
        with pytest.raises(ClientError, match="ambiguous"):
            ambiguous_client.get_project("demo")

    def test_the_ambiguity_error_names_every_candidate_path(self, ambiguous_client):
        with pytest.raises(ClientError) as raised:
            ambiguous_client.get_project("demo")
        assert "/work/demo" in str(raised.value)
        assert "/elsewhere/demo" in str(raised.value)

    def test_an_absolute_path_still_resolves_when_the_basename_is_ambiguous(self, ambiguous_client):
        assert ambiguous_client.get_project("/elsewhere/demo").full_path == "/elsewhere/demo"


class TestSessions:
    def test_sessions_are_returned_newest_first(self, client):
        assert [row.id for row in client.list_sessions()][0] == GATEWAY_SESSION

    def test_limit_bounds_the_result(self, client):
        assert len(client.list_sessions(limit=1)) == 1

    def test_a_zero_limit_returns_nothing(self, client):
        assert client.list_sessions(limit=0) == []

    def test_subagent_sessions_can_be_excluded(self, client):
        ids = {row.id for row in client.list_sessions(include_subagents=False)}
        assert CHILD_SESSION not in ids

    def test_project_scoping_uses_the_workspace_path(self, client):
        ids = {row.id for row in client.list_sessions(project="demo")}
        assert ids == {ROOT_SESSION, CHILD_SESSION}

    def test_the_no_workspace_bucket_scopes_to_gateway_sessions(self, client):
        ids = {row.id for row in client.list_sessions(project=NO_WORKSPACE)}
        assert ids == {GATEWAY_SESSION}

    def test_source_scoping_matches_the_gateway_source(self, client):
        assert [row.id for row in client.list_sessions(source="cron")] == [GATEWAY_SESSION]

    def test_effective_tokens_weight_cache_reads(self, client):
        root = next(row for row in client.list_sessions() if row.id == ROOT_SESSION)
        assert root.effective_tokens == 1700

    def test_get_session_counts_derived_records_without_message_bodies(self, client):
        session = client.get_session(ROOT_SESSION)
        assert session.turn_count == 3
        assert session.conversation_count == 2
        assert session.todo_count == 2
        assert session.skill_count == 2
        assert session.error_count == 1
        assert session.tool_names == ["skill_view", "terminal", "todo"]

    def test_get_session_previews_are_bounded(self, client):
        session = client.get_session(ROOT_SESSION, max_chars=12)
        assert len(session.first_user_prompt) <= 12

    def test_assistant_previews_are_redacted(self, client):
        summaries = [event.summary or "" for event in client.get_timeline(ROOT_SESSION, max_chars=500)]
        secretive = [text for text in summaries if "[REDACTED]" in text]
        assert secretive, "expected the credential-bearing message to be redacted"
        assert not any("supersecretvalue" in text for text in summaries)
        assert not any("abcdefghijklmnop" in text for text in summaries)

    def test_an_unknown_session_is_reported(self, client):
        with pytest.raises(ClientError, match="not found"):
            client.get_session("no-such-session")


class TestSessionResolution:
    def test_an_exact_id_resolves_to_itself(self, client):
        assert client.resolve_session_id(ROOT_SESSION) == ROOT_SESSION

    def test_a_title_resolves_case_insensitively(self, client):
        assert client.resolve_session_id("demo SESSION") == ROOT_SESSION

    def test_a_blank_reference_is_rejected(self, client):
        with pytest.raises(ClientError, match="required"):
            client.resolve_session_id("  ")

    def test_an_unknown_reference_is_rejected(self, client):
        with pytest.raises(ClientError, match="No session with id or title"):
            client.resolve_session_id("nothing like this")

    def test_titles_colliding_only_by_case_are_reported_as_ambiguous(self, ambiguous_client):
        with pytest.raises(ClientError, match="matches 2 sessions"):
            ambiguous_client.resolve_session_id("Shared Title")

    def test_the_title_ambiguity_error_lists_the_session_ids(self, ambiguous_client):
        with pytest.raises(ClientError) as raised:
            ambiguous_client.resolve_session_id("shared title")
        assert "20260901_150000_dupe01" in str(raised.value)
        assert "20260901_150100_dupe02" in str(raised.value)


class TestConversationsAndTurns:
    def test_a_compaction_opens_a_second_conversation(self, client):
        rows = client.list_conversations(session_id=ROOT_SESSION)
        assert [row.started_by for row in rows] == ["session_start", "compaction"]

    def test_conversation_ids_are_session_scoped_and_one_based(self, client):
        rows = client.list_conversations(session_id=ROOT_SESSION)
        assert rows[0].id == f"{ROOT_SESSION}:1"

    def test_a_conversation_is_addressable_by_reference(self, client):
        assert client.get_conversation(f"{ROOT_SESSION}:2").index == 2

    def test_an_out_of_range_conversation_is_reported(self, client):
        with pytest.raises(ClientError, match="out of range"):
            client.get_conversation(f"{ROOT_SESSION}:99")

    @pytest.mark.parametrize("reference", ["no-colon", f"{ROOT_SESSION}:", f"{ROOT_SESSION}:abc"])
    def test_a_malformed_reference_is_rejected(self, client, reference):
        with pytest.raises(ClientError, match="Invalid reference"):
            client.get_conversation(reference)

    def test_a_session_id_containing_a_colon_splits_from_the_right(self, client):
        assert client.split_indexed_id("a:b:3") == ("a:b", 3)

    def test_turns_open_at_each_user_message(self, client):
        rows = client.list_turns(session_id=ROOT_SESSION)
        assert [row.index for row in rows] == [1, 2, 3]

    def test_a_turn_reports_its_tools_and_error_state(self, client):
        second = client.get_turn(f"{ROOT_SESSION}:2")
        assert second.tools_used == ["terminal", "todo"]
        assert second.has_errors is True

    def test_an_out_of_range_turn_is_reported(self, client):
        with pytest.raises(ClientError, match="out of range"):
            client.get_turn(f"{ROOT_SESSION}:99")


class TestToolCallsTodosSkills:
    def test_tool_calls_pair_with_their_results(self, client):
        rows = client.list_tool_calls(session_id=ROOT_SESSION)
        assert [row.tool for row in rows] == ["skill_view", "todo", "terminal"]
        assert rows[2].status == "error"

    def test_tool_calls_carry_their_turn_number(self, client):
        rows = client.list_tool_calls(session_id=ROOT_SESSION)
        assert rows[0].turn == 1
        assert rows[2].turn == 2

    def test_tool_scoping_filters_at_the_client(self, client):
        rows = client.list_tool_calls(session_id=ROOT_SESSION, tool="terminal")
        assert [row.tool for row in rows] == ["terminal"]

    def test_tool_call_previews_are_bounded(self, client):
        rows = client.list_tool_calls(session_id=ROOT_SESSION, max_chars=10)
        assert all(len(row.arguments) <= 10 for row in rows if row.arguments)

    def test_a_tool_call_is_addressable_by_call_id(self, client):
        assert client.get_tool_call("call-3", session_id=ROOT_SESSION).tool == "terminal"

    def test_an_unknown_call_id_is_reported(self, client):
        with pytest.raises(ClientError, match="not found"):
            client.get_tool_call("call-missing", session_id=ROOT_SESSION)

    def test_todos_reflect_the_final_list(self, client):
        rows = client.list_todos(session_id=ROOT_SESSION)
        assert [(row.position, row.status) for row in rows] == [(0, "completed"), (1, "in_progress")]

    def test_a_todo_is_addressable_by_position(self, client):
        assert client.get_todo(f"{ROOT_SESSION}:1").content == "Second task"

    def test_an_out_of_range_todo_position_is_reported(self, client):
        with pytest.raises(ClientError, match="out of range"):
            client.get_todo(f"{ROOT_SESSION}:9")

    def test_a_session_without_todos_returns_none(self, client):
        assert client.list_todos(session_id=GATEWAY_SESSION) == []

    def test_skills_cover_both_tool_loads_and_slash_commands(self, client):
        rows = client.list_skills(session_id=ROOT_SESSION)
        assert {(row.kind, row.name) for row in rows} == {
            ("command", "demo-command"),
            ("skill", "demo-skill"),
        }

    def test_a_skill_record_is_addressable_by_id(self, client):
        record = client.list_skills(session_id=ROOT_SESSION)[0]
        assert client.get_skill(record.id, session_id=ROOT_SESSION).name == record.name

    def test_an_unknown_skill_record_is_reported(self, client):
        with pytest.raises(ClientError, match="not found"):
            client.get_skill("nope:1:0", session_id=ROOT_SESSION)


class TestSubagentActivity:
    def test_children_are_listed_for_their_parent(self, client):
        rows = client.list_subagent_activity(session_id=ROOT_SESSION)
        assert [row.child_session for row in rows] == [CHILD_SESSION]

    def test_the_delegated_goal_comes_from_the_child_first_prompt(self, client):
        row = client.get_subagent_activity(CHILD_SESSION)
        assert row.label == "Investigate the failing check"
        assert row.result == "Investigation complete."

    def test_duration_is_derived_from_the_child_session_bounds(self, client):
        assert client.get_subagent_activity(CHILD_SESSION).duration_seconds == 100.0

    def test_listing_without_a_parent_returns_every_subagent_session(self, client):
        assert [row.id for row in client.list_subagent_activity()] == [CHILD_SESSION]

    def test_a_parent_without_children_returns_nothing(self, client):
        assert client.list_subagent_activity(session_id=GATEWAY_SESSION) == []


class TestTimeline:
    def test_event_types_cover_the_documented_vocabulary(self, client):
        events = client.get_timeline(ROOT_SESSION)
        assert {event.event_type for event in events} == {
            "user_message", "command", "skill_load", "assistant_message",
            "todo_write", "tool_call", "error", "compaction",
        }

    def test_events_are_numbered_in_chronological_order(self, client):
        events = client.get_timeline(ROOT_SESSION)
        assert [event.index for event in events] == list(range(1, len(events) + 1))
        assert [event.timestamp for event in events] == sorted(event.timestamp for event in events)

    def test_errors_only_keeps_failures(self, client):
        events = client.get_timeline(ROOT_SESSION, errors_only=True)
        assert events and all(
            event.status == "error" or event.event_type == "error" for event in events
        )

    def test_the_timeline_is_bounded_by_limit(self, client):
        assert len(client.get_timeline(ROOT_SESSION, limit=3)) == 3

    def test_summaries_are_bounded_by_max_chars(self, client):
        events = client.get_timeline(ROOT_SESSION, max_chars=15)
        assert all(len(event.summary) <= 15 for event in events if event.summary)

    def test_consolidated_merges_subagent_events(self, client):
        events = client.consolidated_timeline(ROOT_SESSION)
        assert {event.subagent_session for event in events} == {None, CHILD_SESSION}

    def test_consolidated_events_stay_chronological_across_sessions(self, client):
        events = client.consolidated_timeline(ROOT_SESSION)
        assert [event.timestamp for event in events] == sorted(event.timestamp for event in events)

    def test_consolidated_can_exclude_subagents(self, client):
        events = client.consolidated_timeline(ROOT_SESSION, include_subagents=False)
        assert all(event.subagent_session is None for event in events)

    def test_consolidated_is_bounded_by_limit(self, client):
        assert len(client.consolidated_timeline(ROOT_SESSION, limit=2)) == 2


class TestSearch:
    def test_full_text_search_finds_message_content(self, client):
        matches = client.search_messages("nightly")
        assert matches and {match.session_id for match in matches} == {GATEWAY_SESSION}

    def test_search_can_be_scoped_to_one_session(self, client):
        assert client.search_messages("nightly", session_id=ROOT_SESSION) == []

    def test_search_snippets_are_bounded(self, client):
        matches = client.search_messages("nightly", max_chars=10)
        assert all(len(match.snippet) <= 10 for match in matches if match.snippet)

    def test_a_blank_query_is_rejected(self, client):
        with pytest.raises(ClientError, match="query is required"):
            client.search_messages("   ")

    def test_title_search_matches_substrings(self, client):
        assert [row.id for row in client.search_sessions("demo")] == [ROOT_SESSION]

    def test_title_search_rejects_a_blank_query(self, client):
        with pytest.raises(ClientError, match="query is required"):
            client.search_sessions("")
