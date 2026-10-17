"""Tests for the client's discovery, resolution, and scoping behavior."""
import pytest

from deepseek_sessions_cli import client as client_module
from deepseek_sessions_cli import config as config_module
from deepseek_sessions_cli.client import ClientError, DeepSeekSessionsClient
from conftest import PROJECT_CWD, PROJECT_KEY, event, header, write_log


@pytest.fixture
def client(monkeypatch, sessions_root, simple_log, subagent_pair, compacted_log):
    """A client pointed at the synthetic dsh home, with singletons reset."""
    monkeypatch.setenv("DSH_HOME", str(sessions_root.parent))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return DeepSeekSessionsClient()


SIMPLE = "session-11111111-1111-4111-8111-111111111111"


def test_missing_dsh_home_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "nope"))
    monkeypatch.setattr(config_module, "_config", None)
    with pytest.raises(ClientError, match="data directory not found"):
        DeepSeekSessionsClient()


def test_blank_dsh_home_falls_back_to_default(monkeypatch):
    """A blank $DSH_HOME must not resolve the home to the cwd."""
    monkeypatch.setenv("DSH_HOME", "   ")
    monkeypatch.setattr(config_module, "_config", None)
    assert config_module.get_config().dsh_home.name == ".dsh"


def test_list_projects_reads_path_from_the_header(client):
    projects = client.list_projects()
    assert len(projects) == 1
    project = projects[0]
    # The directory name is lossy; the real path comes from the log header.
    assert project.encoded_path == "--work-demo--"
    assert project.full_path == "/work/demo"
    assert project.name == "demo"
    assert project.session_count == 4
    assert project.subagent_session_count == 1


def test_list_projects_does_not_decode_full_transcripts(client, monkeypatch):
    """Project metadata reads headers and file mtimes, not every event row."""
    monkeypatch.setattr(
        client,
        "_load",
        lambda _session_dir: (_ for _ in ()).throw(AssertionError("full log decoded")),
    )

    assert client.list_projects(limit=1)[0].name == "demo"


def test_get_project_by_name_key_and_path(client):
    assert client.get_project("demo").name == "demo"
    assert client.get_project("--work-demo--").name == "demo"
    assert client.get_project("/work/demo").name == "demo"
    with pytest.raises(ClientError, match="Project not found"):
        client.get_project("absent")


def test_list_sessions_can_exclude_subagents(client):
    assert len(client.list_sessions()) == 4
    roots = client.list_sessions(include_subagents=False)
    assert len(roots) == 3
    assert all(session.origin != "subagent" for session in roots)


def test_sessions_sort_newest_first(client):
    sessions = client.list_sessions()
    activity = [session.last_activity for session in sessions]
    assert activity == sorted(activity, reverse=True)


def test_list_sessions_loads_only_the_requested_newest_rows(
    sessions_root, monkeypatch
):
    monkeypatch.setenv("DSH_HOME", str(sessions_root.parent))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)

    for index in range(8):
        session_id = f"session-{index:08d}-1111-4111-8111-111111111111"
        records = [
            header(session_id, PROJECT_CWD, created_at=1_787_000_000_000 + index),
            event("session/title", 1, 1_787_000_000_100 + index, title=f"Session {index}"),
        ]
        write_log(sessions_root / PROJECT_KEY / session_id, records)

    client = DeepSeekSessionsClient()
    loaded = []
    original_load = client._load

    def record_load(session_dir, *, strict=False):
        loaded.append(session_dir.name)
        return original_load(session_dir, strict=strict)

    monkeypatch.setattr(client, "_load", record_load)

    rows = client.list_sessions(limit=2, include_subagents=False)

    assert len(rows) == 2
    assert len(loaded) == 2


def test_resolve_session_id_does_not_load_full_transcripts(
    sessions_root, monkeypatch
):
    monkeypatch.setenv("DSH_HOME", str(sessions_root.parent))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)

    session_id = "session-77777777-7777-4777-8777-777777777777"
    write_log(
        sessions_root / PROJECT_KEY / session_id,
        [
            header(session_id, PROJECT_CWD),
            event("session/title", 1, 1_787_000_000_100, title="Indexed title"),
        ],
    )

    client = DeepSeekSessionsClient()
    monkeypatch.setattr(
        client,
        "_load",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("full transcript loaded")
        ),
    )

    assert client.resolve_session_id("Indexed title") == session_id


def test_malformed_line_warning_is_preserved(sessions_root, monkeypatch, capsys):
    monkeypatch.setenv("DSH_HOME", str(sessions_root.parent))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)

    session_id = "session-66666666-6666-4666-8666-666666666666"
    path = write_log(
        sessions_root / PROJECT_KEY / session_id,
        [header(session_id, PROJECT_CWD)],
        compressed=False,
    )
    path.write_text(path.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")

    client = DeepSeekSessionsClient()
    rows = client.list_sessions(limit=1, include_subagents=False)

    assert [row.id for row in rows] == [session_id]
    assert "skipped 1 malformed line(s) (2)" in capsys.readouterr().err


def test_resolve_session_id_passes_through_ids(client, subagent_pair):
    _, child_id = subagent_pair
    assert client.resolve_session_id(SIMPLE) == SIMPLE
    # A bare uuid is a subagent session id and must also pass through.
    assert client.resolve_session_id(child_id) == child_id


def test_resolve_session_id_matches_title(client):
    assert client.resolve_session_id("Demo session") == SIMPLE
    assert client.resolve_session_id("demo SESSION") == SIMPLE


def test_resolve_session_id_rejects_unknown_title(client):
    with pytest.raises(ClientError, match="No session named"):
        client.resolve_session_id("no such title")


def test_get_session_attaches_subagents(client, subagent_pair):
    parent_id, child_id = subagent_pair
    session = client.get_session(parent_id)
    assert set(session.subagents) == {child_id}

    subagent = session.subagents[child_id]
    assert subagent.label == "Crawl a source"
    assert subagent.parent_tool_call_id == "call_sub"
    assert subagent.messages


def test_get_session_unknown_id_raises(client):
    with pytest.raises(ClientError, match="Session not found"):
        client.get_session("session-does-not-exist")


def test_tool_calls_exclude_subagents_by_default(client):
    plain = client.list_tool_calls("demo")
    assert all(row.is_sidechain is False for row in plain)

    combined = client.list_tool_calls("demo", include_subagents=True)
    assert any(row.is_sidechain for row in combined)
    assert len(combined) > len(plain)


def test_subagent_activity_joins_the_spawn(client, subagent_pair):
    parent_id, child_id = subagent_pair
    rows = client.list_subagent_activity("demo")
    assert [row.id for row in rows] == [child_id]
    assert rows[0].parent_session_id == parent_id
    assert rows[0].prompt == "You are a worker agent."

    scoped = client.list_subagent_activity("demo", session_id=parent_id)
    assert len(scoped) == 1
    assert client.list_subagent_activity("demo", session_id=SIMPLE) == []


def test_get_subagent_rejects_a_root_session(client):
    with pytest.raises(ClientError, match="not a subagent session"):
        client.get_subagent(SIMPLE)


def test_timeline_include_subagents_merges_children(client, subagent_pair):
    parent_id, child_id = subagent_pair
    alone = client.get_timeline(parent_id)
    merged = client.get_timeline(parent_id, include_subagents=True)

    assert len(merged) > len(alone)
    assert any(entry.event_type.value == "subagent_tool" for entry in merged)
    assert any(entry.agent_id == child_id for entry in merged)


def test_get_conversation_returns_only_its_messages(client, compacted_log):
    second = client.get_conversation(None, compacted_log, 2)
    assert second is not None
    assert second.started_by == "compaction"
    assert [message["content"] for message in second.messages] == ["after compaction"]

    assert client.get_conversation(None, compacted_log, 99) is None


def test_search_all_matches_across_projects(client):
    results = client.search_all("do the thing")
    assert [result.session_id for result in results] == [SIMPLE]
    assert results[0].custom_title == "Demo session"
    assert client.search_all("nothing matches this") == []


def test_search_sessions_resolves_title_matches_without_transcript_scan(
    client, monkeypatch
):
    monkeypatch.setattr(
        client,
        "search_all",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("transcript scan ran")
        ),
    )

    rows = client.search_sessions("Demo")

    assert [row.id for row in rows] == [SIMPLE]


def test_todos_and_retries_are_project_scoped(client):
    todos = client.list_todos("demo")
    assert [todo.content for todo in todos] == ["first", "second"]
    assert client.get_todo("demo", todos[0].id) is not None
    assert client.get_todo("demo", "nope:0") is None

    retries = client.list_retries("demo")
    assert [retry.error_code for retry in retries] == ["TIMEOUT"]


def test_get_turn_returns_summary_and_steps(client):
    summary, steps = client.get_turn(SIMPLE, 1)
    assert summary.turn == 1
    assert summary.finish_reason == "completed"
    assert [step.step for step in steps] == [1]

    with pytest.raises(ClientError, match="Turn 9 not found"):
        client.get_turn(SIMPLE, 9)


def test_auth_status_reports_the_local_store(client, sessions_root):
    status = client.auth_status()
    assert status["authenticated"] is True
    assert status["sessions_dir"] == str(sessions_root)
    assert status["project_count"] == 1
