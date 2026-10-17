"""Regressions for the defects the chaos-engineer pass proved reproducible.

Every fixture credential below is syntactically valid but deliberately fake.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner

from hermes_sessions_cli import client as client_module
from hermes_sessions_cli import config as config_module
from hermes_sessions_cli import parsers
from hermes_sessions_cli.client import HermesSessionsClient
from hermes_sessions_cli.config import Config
from hermes_sessions_cli.main import app
from hermes_sessions_cli.parsers import NO_WORKSPACE
from conftest import SCHEMA, T0, ROOT_SESSION, tool_call

runner = CliRunner()


@pytest.fixture
def client(hermes_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return HermesSessionsClient(config=Config())


@pytest.fixture
def cli(hermes_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return runner


def invoke(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, f"{args} failed ({result.exit_code}):\n{result.output}"
    return result


# --------------------------------------------------------------------- 1

class TestAuthStatusWritesNothing:
    """`auth status` must report local access without bootstrapping any file."""

    def _run_isolated(self, tmp_path, hermes_home):
        data_home = tmp_path / "xdg"
        data_home.mkdir()
        before = sorted(p.relative_to(data_home).as_posix() for p in data_home.rglob("*"))
        env = dict(os.environ)
        env["XDG_DATA_HOME"] = str(data_home)
        env["HERMES_SESSIONS_HERMES_HOME"] = str(hermes_home)
        env.pop("HERMES_HOME", None)
        result = subprocess.run(
            [sys.executable, "-m", "hermes_sessions_cli.main", "auth", "status"],
            capture_output=True, text=True, env=env,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        after = sorted(p.relative_to(data_home).as_posix() for p in data_home.rglob("*"))
        return result, before, after

    def test_no_file_or_directory_is_created(self, tmp_path, hermes_home):
        result, before, after = self._run_isolated(tmp_path, hermes_home)
        assert result.returncode == 0, result.stderr
        assert after == before == [], f"auth status created: {after}"

    def test_status_still_emits_the_shared_profile_shape(self, tmp_path, hermes_home):
        result, _, _ = self._run_isolated(tmp_path, hermes_home)
        payload = json.loads(result.stdout)
        assert isinstance(payload.get("profiles"), list) and payload["profiles"]
        entry = payload["profiles"][0]
        for field in ("name", "auth_type", "active", "authenticated", "credential_types"):
            assert field in entry
        custom = entry["credential_types"]["custom"]
        assert custom["state_db_readable"] is True
        assert custom["api_test"] == "passed"

    def test_unreadable_store_exits_two_and_still_writes_nothing(self, tmp_path):
        missing = tmp_path / "no-hermes"
        missing.mkdir()
        result, before, after = self._run_isolated(tmp_path, missing)
        assert result.returncode == 2
        assert after == before == []
        payload = json.loads(result.stdout)
        custom = payload["profiles"][0]["credential_types"]["custom"]
        assert custom["state_db_readable"] is False
        assert custom["authenticated"] is False

    def test_config_construction_writes_nothing(
        self, tmp_path, hermes_home, monkeypatch
    ):
        data_home = tmp_path / "config-xdg"
        data_home.mkdir()
        monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
        monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(hermes_home))
        Config()
        assert list(data_home.rglob("*")) == []

    def test_representative_session_read_writes_nothing(
        self, tmp_path, hermes_home
    ):
        data_home = tmp_path / "sessions-xdg"
        data_home.mkdir()
        before = list(data_home.rglob("*"))
        env = dict(os.environ)
        env["XDG_DATA_HOME"] = str(data_home)
        env["HERMES_SESSIONS_HERMES_HOME"] = str(hermes_home)
        env.pop("HERMES_HOME", None)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hermes_sessions_cli.main",
                "sessions",
                "list",
                "--limit",
                "1",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 0, result.stderr
        assert list(data_home.rglob("*")) == before == []


# --------------------------------------------------------------------- 2

# Fake but well-formed: base64 of "svc-account:not-a-real-password".
FAKE_BASIC = "Basic c3ZjLWFjY291bnQ6bm90LWEtcmVhbC1wYXNzd29yZA=="
LONG_TODO = "audit step " * 120  # 1,320 characters


@pytest.fixture
def todo_home(tmp_path):
    """A Hermes home whose only session writes one long, secret-bearing todo."""
    home = tmp_path / "todo-hermes"
    home.mkdir()
    connection = sqlite3.connect(home / "state.db")
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO sessions (id, source, started_at, cwd, title) VALUES (?, 'cli', ?, '/work/demo', 'Todo session')",
        ("todo-session", T0),
    )
    connection.execute(
        'INSERT INTO messages (session_id, role, timestamp, tool_calls) VALUES (?, ?, ?, ?)',
        (
            "todo-session", "assistant", T0 + 1,
            tool_call("todo-call", "todo", {"todos": [
                {"id": "1", "content": LONG_TODO, "status": "pending"},
                {"id": "2", "content": f"call the API with {FAKE_BASIC}", "status": "pending"},
            ]}),
        ),
    )
    connection.commit()
    connection.close()
    return home


@pytest.fixture
def todo_cli(todo_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(todo_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return runner


class TestTodoContentIsBoundedAndRedacted:
    def test_todo_list_bounds_content_by_default(self, todo_cli):
        rows = json.loads(invoke(["todos", "list"]).output)
        assert rows
        assert all(len(row["content"]) <= parsers.DEFAULT_MAX_CHARS for row in rows)

    def test_todo_list_honors_max_chars(self, todo_cli):
        rows = json.loads(invoke(["todos", "list", "--max-chars", "30"]).output)
        assert all(len(row["content"]) <= 30 for row in rows)

    def test_todo_get_honors_max_chars(self, todo_cli):
        row = json.loads(invoke(["todos", "get", "todo-session:0", "--max-chars", "25"]).output)
        assert len(row["content"]) <= 25

    def test_todo_content_is_redacted(self, todo_cli):
        rows = json.loads(invoke(["todos", "list", "--max-chars", "500"]).output)
        blob = json.dumps(rows)
        assert "c3ZjLWFjY291bnQ6bm90LWEtcmVhbC1wYXNzd29yZA==" not in blob
        assert "[REDACTED]" in blob

    def test_todo_list_help_advertises_max_chars(self, todo_cli):
        assert "--max-chars" in invoke(["todos", "list", "--help"]).output
        assert "--max-chars" in invoke(["todos", "get", "--help"]).output


# --------------------------------------------------------------------- 3

class TestRedactionCoversMoreCredentialShapes:
    @pytest.mark.parametrize(
        "text,leak",
        [
            (f"Authorization: {FAKE_BASIC}", "c3ZjLWFjY291bnQ6bm90LWEtcmVhbC1wYXNzd29yZA=="),
            ("aws key AKIAIOSFODNN7EXAMPLE here", "AKIAIOSFODNN7EXAMPLE"),
            ("temp creds ASIAIOSFODNN7EXAMPLE here", "ASIAIOSFODNN7EXAMPLE"),
            ('password: "correct horse battery staple"', "battery staple"),
            ("password: 'correct horse battery staple'", "battery staple"),
            ("curl -u svc-account:not-a-real-password https://x", "not-a-real-password"),
            ("https://svc-account:not-a-real-password@example.com/x", "not-a-real-password"),
        ],
    )
    def test_credential_shapes_are_masked(self, text, leak):
        rendered = parsers.preview(text, 500)
        assert leak not in rendered, rendered
        assert "[REDACTED]" in rendered

    def test_ordinary_prose_is_untouched(self):
        assert parsers.preview("the key insight is to read the file") == "the key insight is to read the file"

    def test_redaction_applies_to_consolidated_timeline(self, client):
        summaries = [event.summary or "" for event in client.consolidated_timeline(ROOT_SESSION, max_chars=500)]
        assert not any("supersecretvalue" in text for text in summaries)


# --------------------------------------------------------------------- 4

BIG_SESSION = "big-session"
BIG_MESSAGE_COUNT = 50_001


@pytest.fixture(scope="module")
def big_home(tmp_path_factory):
    """A session with 50,001 messages whose newest rows carry the live state."""
    home = tmp_path_factory.mktemp("big-hermes")
    connection = sqlite3.connect(home / "state.db")
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO sessions (id, source, started_at, cwd, title, message_count) VALUES (?, 'cli', ?, '/work/big', 'Big session', ?)",
        (BIG_SESSION, T0, BIG_MESSAGE_COUNT),
    )
    rows = []
    for index in range(BIG_MESSAGE_COUNT - 3):
        role = "user" if index % 2 == 0 else "assistant"
        rows.append((BIG_SESSION, role, T0 + index, f"filler message {index}", None))
    connection.executemany(
        "INSERT INTO messages (session_id, role, timestamp, content, tool_calls) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    tail = T0 + BIG_MESSAGE_COUNT
    connection.execute(
        "INSERT INTO messages (session_id, role, timestamp, content, tool_calls) VALUES (?, 'user', ?, ?, NULL)",
        (BIG_SESSION, tail - 2, "NEWEST USER PROMPT"),
    )
    connection.execute(
        "INSERT INTO messages (session_id, role, timestamp, content, tool_calls) VALUES (?, 'assistant', ?, NULL, ?)",
        (
            BIG_SESSION, tail - 1,
            tool_call("newest-todo", "todo", {"todos": [{"id": "1", "content": "NEWEST TODO", "status": "in_progress"}]}),
        ),
    )
    connection.execute(
        "INSERT INTO messages (session_id, role, timestamp, content, tool_calls) VALUES (?, 'assistant', ?, ?, NULL)",
        (BIG_SESSION, tail, "NEWEST ASSISTANT MESSAGE"),
    )
    connection.commit()
    connection.close()
    return home


@pytest.fixture
def big_client(big_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(big_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return HermesSessionsClient(config=Config())


class TestNewestContextSurvivesAVeryLongSession:
    def test_the_fixture_really_has_fifty_thousand_and_one_messages(self, big_client):
        total = big_client.store.query(
            "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?", (BIG_SESSION,)
        )[0]["total"]
        assert total == BIG_MESSAGE_COUNT

    def test_session_detail_reports_the_newest_assistant_message(self, big_client):
        session = big_client.get_session(BIG_SESSION)
        assert session.last_assistant_message == "NEWEST ASSISTANT MESSAGE"

    def test_session_detail_reports_the_oldest_user_prompt(self, big_client):
        assert big_client.get_session(BIG_SESSION).first_user_prompt == "filler message 0"

    def test_todos_reflect_the_newest_todo_call(self, big_client):
        todos = big_client.list_todos(session_id=BIG_SESSION)
        assert [todo.content for todo in todos] == ["NEWEST TODO"]

    def test_session_detail_exposes_the_window_explicitly(self, big_client):
        session = big_client.get_session(BIG_SESSION)
        assert session.message_window_truncated is True
        assert session.message_window_size == client_module.MESSAGE_WINDOW

    def test_a_short_session_is_not_marked_truncated(self, client):
        session = client.get_session(ROOT_SESSION)
        assert session.message_window_truncated is False

    def test_timeline_includes_the_newest_events(self, big_client):
        summaries = [event.summary for event in big_client.get_timeline(BIG_SESSION, limit=500)]
        assert "NEWEST ASSISTANT MESSAGE" in summaries

    def test_turn_indices_stay_globally_correct(self, big_client):
        turns = big_client.list_turns(session_id=BIG_SESSION, limit=500)
        assert turns[-1].user_prompt == "NEWEST USER PROMPT"
        # The newest turn is the last of the whole session, not of the window.
        assert turns[-1].index > 20_000

    def test_derived_views_stay_bounded(self, big_client):
        assert len(big_client.list_turns(session_id=BIG_SESSION, limit=10)) == 10
        assert len(big_client.get_timeline(BIG_SESSION, limit=25)) == 25


# --------------------------------------------------------------------- 5

LIST_COMMANDS = [
    ["projects", "list"],
    ["sessions", "list"],
    ["conversations", "list"],
    ["turns", "list"],
    ["tool-calls", "list"],
    ["todos", "list"],
    ["skills", "list"],
    ["subagent-activity", "list"],
    ["timeline", "list"],
    ["search", "run", "demo"],
]


class TestNegativeLimitsNeverExpandOutput:
    @pytest.mark.parametrize("command", LIST_COMMANDS, ids=lambda c: "-".join(c))
    def test_negative_limit_returns_nothing(self, cli, command):
        assert json.loads(invoke([*command, "--limit", "-1"]).output) == []

    @pytest.mark.parametrize("command", LIST_COMMANDS, ids=lambda c: "-".join(c))
    def test_zero_limit_returns_nothing(self, cli, command):
        assert json.loads(invoke([*command, "--limit", "0"]).output) == []

    @pytest.mark.parametrize(
        "command",
        [c for c in LIST_COMMANDS if c[0] != "search"],
        ids=lambda c: "-".join(c),
    )
    def test_negative_limit_with_a_filter_also_returns_nothing(self, cli, command):
        # A filter forces the wide pre-fetch path, which is where a negative
        # limit used to turn into `rows[:-1]` and return nearly everything.
        field = "name" if command[0] == "projects" else "id"
        rows = json.loads(
            invoke([*command, "--limit", "-1", "--filter", f"{field}:ne:__no_such_value__"]).output
        )
        assert rows == []

    def test_a_filtered_negative_limit_does_not_slice_off_only_the_last_row(self, cli):
        unbounded = json.loads(invoke(["sessions", "list", "--filter", "source:ne:nope"]).output)
        assert len(unbounded) > 1
        assert json.loads(invoke(["sessions", "list", "--limit", "-1", "--filter", "source:ne:nope"]).output) == []


# --------------------------------------------------------------------- 6

class TestPreviewNeverExceedsTheRequestedCap:
    @pytest.mark.parametrize("cap", [-5, 0, 1, 2, 3, 4, 10, 200])
    def test_the_whole_preview_fits_inside_the_cap(self, cap):
        rendered = parsers.preview("z" * 5_000, cap)
        assert len(rendered) <= max(1, cap), f"cap={cap} produced {len(rendered)} chars"

    @pytest.mark.parametrize("cap", [-5, 0, 1, 2, 3])
    def test_a_tiny_cap_is_still_bounded_not_unbounded(self, cap):
        assert len(parsers.preview("z" * 5_000, cap)) <= 3

    def test_text_shorter_than_the_cap_is_returned_whole(self):
        assert parsers.preview("short", 200) == "short"

    @pytest.mark.parametrize("cap", [1, 2, 3, 4, 40])
    def test_consolidated_timeline_respects_a_tiny_cap(self, client, cap):
        events = client.consolidated_timeline(ROOT_SESSION, max_chars=cap)
        assert events
        for event in events:
            if event.summary is not None:
                assert len(event.summary) <= cap


# --------------------------------------------------------------------- 7

@pytest.fixture
def unicode_home(tmp_path):
    home = tmp_path / "unicode-hermes"
    home.mkdir()
    connection = sqlite3.connect(home / "state.db")
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO sessions (id, source, started_at, cwd, title) VALUES ('u1', 'cli', ?, '/work/demo', 'über session')",
        (T0,),
    )
    connection.execute(
        "INSERT INTO sessions (id, source, started_at, cwd, title) VALUES ('u2', 'cli', ?, '/work/demo', 'STRASSE run')",
        (T0 + 1,),
    )
    connection.execute(
        "INSERT INTO sessions (id, source, started_at, cwd, title) VALUES ('u3', 'cli', ?, '/work/demo', 'Dupe Ünicode')",
        (T0 + 2,),
    )
    connection.execute(
        "INSERT INTO sessions (id, source, started_at, cwd, title) VALUES ('u4', 'cli', ?, '/work/demo', 'dupe ünicode')",
        (T0 + 3,),
    )
    connection.commit()
    connection.close()
    return home


@pytest.fixture
def unicode_client(unicode_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(unicode_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return HermesSessionsClient(config=Config())


class TestUnicodeTitleLookup:
    @pytest.mark.parametrize("query", ["über session", "ÜBER SESSION", "Über Session", "ÜBER session"])
    def test_case_insensitive_lookup_works_for_non_ascii_titles(self, unicode_client, query):
        assert unicode_client.resolve_session_id(query) == "u1"

    def test_casefold_semantics_apply(self, unicode_client):
        # German ß casefolds to "ss", which lower() alone never matches.
        assert unicode_client.resolve_session_id("straße run") == "u2"

    def test_duplicate_titles_remain_ambiguous(self, unicode_client):
        with pytest.raises(ClientError, match="matches 2 sessions"):
            unicode_client.resolve_session_id("DUPE ÜNICODE")

    def test_an_unknown_unicode_title_is_still_reported(self, unicode_client):
        with pytest.raises(ClientError, match="No session with id or title"):
            unicode_client.resolve_session_id("níente")


# --------------------------------------------------------------------- 8

@pytest.fixture
def blank_cwd_home(tmp_path):
    home = tmp_path / "blank-hermes"
    home.mkdir()
    connection = sqlite3.connect(home / "state.db")
    connection.executescript(SCHEMA)
    for index, cwd in enumerate([None, "", "   ", "\t"]):
        connection.execute(
            "INSERT INTO sessions (id, source, started_at, cwd, title) VALUES (?, 'cron', ?, ?, ?)",
            (f"blank{index}", T0 + index, cwd, f"Blank {index}"),
        )
    connection.execute(
        "INSERT INTO sessions (id, source, started_at, cwd, title) VALUES ('real', 'cli', ?, '/work/demo', 'Real')",
        (T0 + 10,),
    )
    connection.commit()
    connection.close()
    return home


@pytest.fixture
def blank_client(blank_cwd_home, monkeypatch):
    monkeypatch.setenv("HERMES_SESSIONS_HERMES_HOME", str(blank_cwd_home))
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(client_module, "_client", None)
    return HermesSessionsClient(config=Config())


class TestBlankWorkspaceNormalization:
    def test_blank_and_null_cwds_collapse_into_one_bucket(self, blank_client):
        projects = {project.name: project for project in blank_client.list_projects()}
        assert set(projects) == {NO_WORKSPACE, "demo"}
        assert projects[NO_WORKSPACE].session_count == 4

    def test_scoping_the_bucket_returns_every_blank_workspace_session(self, blank_client):
        ids = {row.id for row in blank_client.list_sessions(project=NO_WORKSPACE)}
        assert ids == {"blank0", "blank1", "blank2", "blank3"}

    def test_getting_the_bucket_reports_the_same_count(self, blank_client):
        assert blank_client.get_project(NO_WORKSPACE).session_count == 4

    def test_the_bucket_has_no_full_path(self, blank_client):
        assert blank_client.get_project(NO_WORKSPACE).full_path is None

    def test_real_workspaces_are_unaffected(self, blank_client):
        assert {row.id for row in blank_client.list_sessions(project="demo")} == {"real"}

    def test_title_lookup_scoped_to_the_blank_bucket_works(self, blank_client):
        assert blank_client.resolve_session_id("Blank 1", project=NO_WORKSPACE) == "blank1"
