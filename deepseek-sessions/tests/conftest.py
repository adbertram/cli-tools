"""Shared fixtures: synthetic dsh session logs in both physical encodings.

Tests build their own logs rather than reading the developer's real dsh home,
so they are deterministic and run anywhere.
"""
import io
import json
from compression import zstd
from pathlib import Path

import pytest


def header(session_id: str, cwd: str, created_at: int = 1_787_000_000_000, **extra) -> dict:
    """Build a dsh session header line."""
    return {
        "type": "session",
        "version": 0,
        "id": session_id,
        "createdAt": created_at,
        "cwd": cwd,
        "delegationDepth": 0,
        **extra,
    }


def event(kind: str, seq: int, time: int, **data) -> dict:
    """Build a dsh event row."""
    return {"type": kind, "seq": seq, "time": time, "data": data}


def write_log(session_dir: Path, records: list, compressed: bool = True) -> Path:
    """Write records as a dsh session log in the chosen encoding.

    When compressed, each record becomes its own Zstandard frame, matching the
    harness's append-a-frame-per-batch container.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(record) for record in records) + "\n"

    if not compressed:
        path = session_dir / "session.jsonl"
        path.write_text(body, encoding="utf-8")
        return path

    path = session_dir / "session.jsonl.zstd"
    frames = b"".join(
        zstd.compress((json.dumps(record) + "\n").encode("utf-8")) for record in records
    )
    path.write_bytes(frames)
    return path


@pytest.fixture
def sessions_root(tmp_path: Path) -> Path:
    """An empty dsh sessions root."""
    root = tmp_path / "dsh" / "sessions"
    root.mkdir(parents=True)
    return root


# `projectKey("/work/demo")` -> "--work-demo--"
PROJECT_KEY = "--work-demo--"
PROJECT_CWD = "/work/demo"


@pytest.fixture
def simple_log(sessions_root: Path) -> Path:
    """One root session: two turns, a tool call, a todo write, and a retry."""
    session_id = "session-11111111-1111-4111-8111-111111111111"
    records = [
        header(session_id, PROJECT_CWD),
        event("session/title", 1, 1_787_000_000_100, title="Demo session",
              source={"kind": "provider"}),
        event("turn/start", 2, 1_787_000_000_200, turn=1),
        event("step/start", 3, 1_787_000_000_300, turn=1, step=1),
        event("user/message", 4, 1_787_000_000_400,
              content=[{"type": "text", "text": "do the thing"}],
              source={"kind": "user"}, role="user", id="u1"),
        event("tool/call", 5, 1_787_000_000_500, turn=1, step=1,
              callId="call_1", name="bash",
              arguments=json.dumps({"command": "ls"})),
        event("tool/result", 6, 1_787_000_000_600, turn=1, step=1, message={
            "source": {"kind": "tool", "callId": "call_1"},
            "content": [{
                "type": "tool-result",
                "toolCallId": "call_1",
                "content": [{"type": "text", "text": "file.txt"}],
                "isError": False,
            }],
            "role": "user",
            "id": "r1",
        }),
        event("assistant/message", 7, 1_787_000_000_700, turn=1, step=1, message={
            "role": "assistant",
            "content": [
                {"type": "reasoning", "text": "thinking hard"},
                {"type": "text", "text": "done"},
                {"type": "tool-call", "toolCallId": "call_1"},
            ],
            "source": {"kind": "model", "provider": "deepseek-official",
                       "model": "deepseek-v4-pro"},
            "id": "a1",
        }, usage={"inputTokens": 100, "outputTokens": 50,
                  "cacheReadTokens": 1000, "reasoningTokens": 20}),
        event("step/end", 8, 1_787_000_000_800, turn=1, step=1),
        event("todo/write", 9, 1_787_000_000_900, todos=[
            {"content": "first", "status": "completed"},
            {"content": "second", "status": "pending"},
        ]),
        event("turn/end", 10, 1_787_000_001_000, turn=1,
              reason={"kind": "completed"}),
        # Turn 2 fails and leaves its step open.
        event("turn/start", 11, 1_787_000_001_100, turn=2),
        event("step/start", 12, 1_787_000_001_200, turn=2, step=1),
        event("llm/retry", 13, 1_787_000_001_300, retryId="retry-1", turn=2, step=1,
              provider="deepseek-official", mode="normal", retry=1, maxRetries=2,
              delayMs=500.0,
              failure={"message": "stream idle timeout", "code": "TIMEOUT"}),
        event("llm/retry-started", 14, 1_787_000_001_400, retryId="retry-1",
              turn=2, step=1, retry=1),
        event("turn/end", 15, 1_787_000_001_500, turn=2, reason={
            "kind": "error",
            "error": {"message": "provider gave up", "code": "TIMEOUT"},
        }),
    ]
    return write_log(sessions_root / PROJECT_KEY / session_id, records)


@pytest.fixture
def subagent_pair(sessions_root: Path) -> tuple:
    """A parent session that spawns one subagent, plus the child's own log."""
    parent_id = "session-22222222-2222-4222-8222-222222222222"
    child_id = "33333333-3333-4333-8333-333333333333"

    parent = [
        header(parent_id, PROJECT_CWD, created_at=1_787_000_100_000),
        event("session/title", 1, 1_787_000_100_100, title="Parent",
              source={"kind": "provider"}),
        event("turn/start", 2, 1_787_000_100_200, turn=1),
        event("step/start", 3, 1_787_000_100_300, turn=1, step=1),
        event("tool/call", 4, 1_787_000_100_400, turn=1, step=1,
              callId="call_sub", name="subagent",
              arguments=json.dumps({"description": "Crawl a source",
                                    "prompt": "You are a worker agent."})),
        event("tool/result", 5, 1_787_000_100_500, turn=1, step=1, message={
            "source": {"kind": "tool", "callId": "call_sub"},
            "content": [{
                "type": "tool-result",
                "toolCallId": "call_sub",
                "content": [{"type": "text", "text": f"started subagent {child_id}"}],
                "isError": False,
            }],
            "role": "user",
            "id": "r_sub",
        }),
        event("step/end", 6, 1_787_000_100_600, turn=1, step=1),
        event("turn/end", 7, 1_787_000_100_700, turn=1, reason={"kind": "completed"}),
    ]

    child = [
        header(child_id, PROJECT_CWD, created_at=1_787_000_100_450,
               parentSession=parent_id, origin="subagent", delegationDepth=1,
               agentPreset="standard"),
        event("subagent/descriptor", 0, 1_787_000_100_450, version=2,
              mode="continuable", provider="spawn", label="Crawl a source",
              agentProvider="deepseek-official", agentModel="deepseek-v4-pro"),
        event("turn/start", 1, 1_787_000_100_460, turn=1),
        event("step/start", 2, 1_787_000_100_470, turn=1, step=1),
        event("tool/call", 3, 1_787_000_100_480, turn=1, step=1,
              callId="call_child", name="report",
              arguments=json.dumps({"output": "crawl finished"})),
        event("assistant/message", 4, 1_787_000_100_490, turn=1, step=1, message={
            "role": "assistant",
            "content": [{"type": "text", "text": "reporting"}],
            "source": {"kind": "model", "provider": "deepseek-official",
                       "model": "deepseek-v4-pro"},
            "id": "ca1",
        }, usage={"inputTokens": 10, "outputTokens": 5,
                  "cacheReadTokens": 200, "reasoningTokens": 1}),
        event("step/end", 5, 1_787_000_100_495, turn=1, step=1),
        event("turn/end", 6, 1_787_000_100_499, turn=1, reason={"kind": "completed"}),
    ]

    project = sessions_root / PROJECT_KEY
    write_log(project / parent_id, parent)
    write_log(project / child_id, child)
    return parent_id, child_id


@pytest.fixture
def compacted_log(sessions_root: Path) -> str:
    """A session that was compacted once, so it holds two conversations."""
    session_id = "session-44444444-4444-4444-8444-444444444444"
    records = [
        header(session_id, PROJECT_CWD, created_at=1_787_000_200_000),
        event("user/message", 1, 1_787_000_200_100,
              content=[{"type": "text", "text": "before compaction"}],
              source={"kind": "user"}, role="user", id="u1"),
        event("turn/start", 2, 1_787_000_200_200, turn=1),
        event("turn/end", 3, 1_787_000_200_300, turn=1, reason={"kind": "completed"}),
        event("compaction/start", 4, 1_787_000_200_400),
        event("compaction/summary", 5, 1_787_000_200_450,
              summary="we discussed the thing"),
        event("compaction/end", 6, 1_787_000_200_500),
        event("user/message", 7, 1_787_000_200_600,
              content=[{"type": "text", "text": "after compaction"}],
              source={"kind": "user"}, role="user", id="u2"),
        event("turn/start", 8, 1_787_000_200_700, turn=2),
        event("turn/end", 9, 1_787_000_200_800, turn=2, reason={"kind": "completed"}),
    ]
    write_log(sessions_root / PROJECT_KEY / session_id, records)
    return session_id


@pytest.fixture
def compacted_block_summary_log(sessions_root: Path) -> str:
    """A compacted session whose summary is a content-block array, not a string.

    dsh records `compaction/summary` either as plain text or as the same
    provider-native content-block list it uses for message content.
    """
    session_id = "session-55555555-5555-4555-8555-555555555555"
    records = [
        header(session_id, PROJECT_CWD, created_at=1_787_000_300_000),
        event("user/message", 1, 1_787_000_300_100,
              content=[{"type": "text", "text": "before compaction"}],
              source={"kind": "user"}, role="user", id="u1"),
        event("turn/start", 2, 1_787_000_300_200, turn=1),
        event("turn/end", 3, 1_787_000_300_300, turn=1, reason={"kind": "completed"}),
        event("compaction/start", 4, 1_787_000_300_400),
        event("compaction/summary", 5, 1_787_000_300_450, summary=[
            {"type": "text", "text": "## Primary Request and Intent"},
            {"type": "text", "text": "Spawn `debugger` on failures."},
        ]),
        event("compaction/end", 6, 1_787_000_300_500),
        event("user/message", 7, 1_787_000_300_600,
              content=[{"type": "text", "text": "after compaction"}],
              source={"kind": "user"}, role="user", id="u2"),
        event("turn/start", 8, 1_787_000_300_700, turn=2),
        event("turn/end", 9, 1_787_000_300_800, turn=2, reason={"kind": "completed"}),
    ]
    write_log(sessions_root / PROJECT_KEY / session_id, records)
    return session_id
