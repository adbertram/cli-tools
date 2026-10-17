"""Shared fixtures: a synthetic Hermes `state.db`.

Tests build their own state store rather than reading the developer's real
Hermes home, so they are deterministic and run anywhere.
"""
import json
import sqlite3
from pathlib import Path

import pytest

# A trimmed copy of the Hermes schema: every column this CLI reads, in the
# shapes Hermes writes them.
SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    api_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL,
    cwd TEXT,
    title TEXT,
    title_source TEXT,
    profile_name TEXT,
    chat_type TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    last_activity_at REAL,
    system_prompt_hash TEXT,
    tool_names TEXT
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    compacted INTEGER NOT NULL DEFAULT 0,
    _compressed_summary INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    display_kind TEXT
);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content, tool_name, tool_calls, content='messages', content_rowid='id'
);
"""

# Fixed epochs so every assertion is deterministic.
T0 = 1_789_000_000.0
PROJECT_CWD = "/work/demo"
OTHER_CWD = "/elsewhere/demo"
ROOT_SESSION = "20260901_120000_root01"
CHILD_SESSION = "20260901_120500_child1"
GATEWAY_SESSION = "cron_abc123_20260901_130000"


def tool_call(call_id: str, name: str, arguments: dict) -> str:
    """Render one Hermes-shaped tool_calls payload."""
    return json.dumps(
        [
            {
                "id": call_id,
                "call_id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ]
    )


def _session(connection, **overrides):
    row = {
        "source": "cli",
        "user_id": None,
        "model": "openai/gpt-5",
        "parent_session_id": None,
        "started_at": T0,
        "ended_at": None,
        "end_reason": None,
        "message_count": 0,
        "tool_call_count": 0,
        "api_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
        "estimated_cost_usd": 0.0,
        "cwd": PROJECT_CWD,
        "title": None,
        "title_source": None,
        "profile_name": "default",
        "chat_type": None,
        "archived": 0,
        "hidden": 0,
        "pinned": 0,
        "last_activity_at": None,
        "system_prompt_hash": None,
        "tool_names": None,
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    connection.execute(
        f"INSERT INTO sessions ({columns}) VALUES ({placeholders})", tuple(row.values())
    )


def _message(connection, session_id, role, timestamp, **overrides):
    row = {
        "session_id": session_id,
        "role": role,
        "content": None,
        "tool_call_id": None,
        "tool_calls": None,
        "tool_name": None,
        "timestamp": timestamp,
        "token_count": None,
        "finish_reason": None,
        "compacted": 0,
        "_compressed_summary": 0,
        "active": 1,
        "display_kind": None,
    }
    row.update(overrides)
    columns = ", ".join(f'"{name}"' for name in row)
    placeholders = ", ".join("?" for _ in row)
    connection.execute(
        f"INSERT INTO messages ({columns}) VALUES ({placeholders})", tuple(row.values())
    )


@pytest.fixture
def hermes_home(tmp_path: Path) -> Path:
    """A synthetic Hermes home holding a populated `state.db`."""
    home = tmp_path / "hermes"
    home.mkdir()
    connection = sqlite3.connect(home / "state.db")
    connection.executescript(SCHEMA)

    # A root session: two turns, a compaction, a skill load, a todo write,
    # a failed tool call, and one delegated subagent.
    _session(
        connection,
        id=ROOT_SESSION,
        title="Demo session",
        title_source="llm",
        started_at=T0,
        ended_at=T0 + 600,
        end_reason="cli_close",
        last_activity_at=T0 + 600,
        message_count=9,
        tool_call_count=3,
        api_call_count=4,
        input_tokens=1000,
        output_tokens=200,
        cache_read_tokens=5000,
        reasoning_tokens=50,
        estimated_cost_usd=0.01,
        system_prompt_hash="hash1",
    )
    _message(connection, ROOT_SESSION, "user", T0 + 1, content="/demo-command run the demo")
    _message(
        connection, ROOT_SESSION, "assistant", T0 + 2,
        tool_calls=tool_call("call-1", "skill_view", {"name": "demo-skill"}),
        finish_reason="tool_calls",
    )
    _message(
        connection, ROOT_SESSION, "tool", T0 + 3, tool_call_id="call-1",
        tool_name="skill_view", content='{"success": true, "name": "demo-skill"}',
    )
    _message(
        connection, ROOT_SESSION, "assistant", T0 + 4,
        content="Loaded the skill. Token is Bearer abcdefghijklmnop and key=supersecretvalue",
        finish_reason="stop",
    )
    _message(connection, ROOT_SESSION, "user", T0 + 10, content="now write the todos")
    _message(
        connection, ROOT_SESSION, "assistant", T0 + 11,
        tool_calls=tool_call(
            "call-2", "todo",
            {"todos": [
                {"id": "1", "content": "First task", "status": "completed"},
                {"id": "2", "content": "Second task", "status": "in_progress"},
            ]},
        ),
        finish_reason="tool_calls",
    )
    _message(
        connection, ROOT_SESSION, "tool", T0 + 12, tool_call_id="call-2",
        tool_name="todo", content='{"todos": []}',
    )
    _message(
        connection, ROOT_SESSION, "assistant", T0 + 13,
        tool_calls=tool_call("call-3", "terminal", {"command": "ls /nope"}),
        finish_reason="tool_calls",
    )
    _message(
        connection, ROOT_SESSION, "tool", T0 + 14, tool_call_id="call-3",
        tool_name="terminal", content='{"success": false, "error": "no such directory"}',
    )
    # A compaction boundary opens a second conversation.
    _message(
        connection, ROOT_SESSION, "user", T0 + 20, _compressed_summary=1,
        content="[CONTEXT COMPACTION - REFERENCE ONLY] Earlier turns were compacted.",
    )
    _message(connection, ROOT_SESSION, "assistant", T0 + 21, content="Continuing.", finish_reason="stop")

    # A delegated subagent session.
    _session(
        connection,
        id=CHILD_SESSION,
        source="subagent",
        parent_session_id=ROOT_SESSION,
        started_at=T0 + 100,
        ended_at=T0 + 200,
        end_reason="agent_close",
        last_activity_at=T0 + 200,
        message_count=2,
        tool_call_count=1,
        input_tokens=500,
        output_tokens=100,
        cache_read_tokens=1000,
    )
    _message(connection, CHILD_SESSION, "user", T0 + 101, content="Investigate the failing check")
    _message(connection, CHILD_SESSION, "assistant", T0 + 102, content="Investigation complete.", finish_reason="stop")

    # A gateway session in a different workspace, with no cwd at all.
    _session(
        connection,
        id=GATEWAY_SESSION,
        source="cron",
        cwd=None,
        title="Nightly job",
        title_source="derived",
        started_at=T0 + 3600,
        ended_at=T0 + 3660,
        end_reason="cron_complete",
        last_activity_at=T0 + 3660,
        message_count=2,
        tool_call_count=0,
    )
    _message(connection, GATEWAY_SESSION, "user", T0 + 3601, content="run the nightly job")
    _message(connection, GATEWAY_SESSION, "assistant", T0 + 3602, content="Nightly job done.", finish_reason="stop")

    connection.execute(
        "INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')"
    )
    connection.commit()
    connection.close()
    return home


@pytest.fixture
def ambiguous_home(hermes_home: Path) -> Path:
    """Adds a second workspace whose basename collides with the first."""
    connection = sqlite3.connect(hermes_home / "state.db")
    _session(
        connection,
        id="20260901_140000_other1",
        cwd=OTHER_CWD,
        title="Other workspace session",
        started_at=T0 + 7200,
        last_activity_at=T0 + 7200,
    )
    # Two sessions whose titles differ only by case: name lookup is
    # case-insensitive, so this pair must be reported as ambiguous.
    _session(connection, id="20260901_150000_dupe01", title="Shared Title",
             started_at=T0 + 7300, last_activity_at=T0 + 7300)
    _session(connection, id="20260901_150100_dupe02", title="shared title",
             started_at=T0 + 7400, last_activity_at=T0 + 7400)
    connection.commit()
    connection.close()
    return hermes_home


@pytest.fixture
def empty_home(tmp_path: Path) -> Path:
    """A Hermes home whose state store exists but holds no sessions."""
    home = tmp_path / "empty-hermes"
    home.mkdir()
    connection = sqlite3.connect(home / "state.db")
    connection.executescript(SCHEMA)
    connection.commit()
    connection.close()
    return home


@pytest.fixture
def missing_home(tmp_path: Path) -> Path:
    """A Hermes home directory with no state store at all."""
    home = tmp_path / "missing-hermes"
    home.mkdir()
    return home
