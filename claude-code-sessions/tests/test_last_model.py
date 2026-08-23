"""Regression tests for the last-model-used field on sessions, conversations,
and search results.

Claude Code session transcripts record a `model` field on `message` for each
assistant entry. A session or conversation can span multiple models (mid-
session model switches), so the correct "last model used" value is the model
from the LAST assistant turn, not the first and not a blank/None value when
later turns do carry a model.
"""
import json

from claude_code_sessions_cli.parsers import (
    parse_session_summary,
    parse_full_session,
    parse_conversation_summaries,
    search_session_file,
    scan_last_model,
)


def _write_lines(path, entries):
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def _assistant_entry(uuid, parent_uuid, timestamp, text, model, is_sidechain=False):
    entry = {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent_uuid,
        "timestamp": timestamp,
        "message": {
            "content": [{"type": "text", "text": text}],
            "model": model,
            "usage": {"input_tokens": 5, "output_tokens": 2},
        },
    }
    if is_sidechain:
        entry["isSidechain"] = True
    return entry


def _user_entry(uuid, parent_uuid, timestamp, text, is_sidechain=False):
    entry = {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent_uuid,
        "timestamp": timestamp,
        "message": {"content": text},
    }
    if is_sidechain:
        entry["isSidechain"] = True
    return entry


def test_session_summary_reports_model_from_last_assistant_turn(tmp_path):
    session_path = tmp_path / "session-1.jsonl"
    _write_lines(
        session_path,
        [
            _user_entry("user-1", None, "2026-06-25T12:00:00.000Z", "hi"),
            _assistant_entry(
                "assistant-1", "user-1", "2026-06-25T12:00:01.000Z",
                "first reply", "claude-sonnet-4",
            ),
            _user_entry("user-2", "assistant-1", "2026-06-25T12:00:02.000Z", "again"),
            _assistant_entry(
                "assistant-2", "user-2", "2026-06-25T12:00:03.000Z",
                "second reply, after a model switch", "claude-sonnet-5",
            ),
        ],
    )

    summary = parse_session_summary(session_path, "TestProject")

    assert summary is not None
    assert summary.model == "claude-sonnet-5"


def test_session_summary_model_is_none_when_never_recorded(tmp_path):
    session_path = tmp_path / "session-1.jsonl"
    _write_lines(
        session_path,
        [
            _user_entry("user-1", None, "2026-06-25T12:00:00.000Z", "hi"),
            {
                "type": "assistant",
                "uuid": "assistant-1",
                "parentUuid": "user-1",
                "timestamp": "2026-06-25T12:00:01.000Z",
                "message": {
                    "content": [{"type": "text", "text": "no model field"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
        ],
    )

    summary = parse_session_summary(session_path, "TestProject")

    assert summary is not None
    assert summary.model is None
    assert summary.model_dump()["model"] is None


def test_session_model_excludes_sidechain_subagent_turns(tmp_path):
    session_path = tmp_path / "session-1.jsonl"
    _write_lines(
        session_path,
        [
            _user_entry("user-1", None, "2026-06-25T12:00:00.000Z", "run a subagent"),
            _assistant_entry(
                "assistant-1", "user-1", "2026-06-25T12:00:01.000Z",
                "main thread reply", "claude-sonnet-5",
            ),
            # Sidechain (subagent) turn comes later in file order but must not
            # override the main-thread session/summary model.
            _user_entry("sub-user-1", "assistant-1", "2026-06-25T12:00:02.000Z", "Warmup", is_sidechain=True),
            _assistant_entry(
                "sub-assistant-1", "sub-user-1", "2026-06-25T12:00:03.000Z",
                "subagent reply", "claude-haiku-4", is_sidechain=True,
            ),
        ],
    )

    summary = parse_session_summary(session_path, "TestProject")
    session = parse_full_session(session_path, "TestProject")

    assert summary is not None
    assert summary.model == "claude-sonnet-5"
    assert session is not None
    assert session.model == "claude-sonnet-5"


def test_conversation_summaries_track_model_per_conversation(tmp_path):
    session_path = tmp_path / "session-1.jsonl"
    _write_lines(
        session_path,
        [
            # Conversation 1
            _user_entry("user-1", None, "2026-06-25T12:00:00.000Z", "first convo"),
            _assistant_entry(
                "assistant-1", "user-1", "2026-06-25T12:00:01.000Z",
                "reply 1", "claude-sonnet-4",
            ),
            # Conversation 2 (chain break: parentUuid references nothing seen)
            _user_entry("user-2", "missing-parent", "2026-06-25T12:05:00.000Z", "second convo"),
            _assistant_entry(
                "assistant-2", "user-2", "2026-06-25T12:05:01.000Z",
                "reply 2", "claude-sonnet-5",
            ),
        ],
    )

    conversations = parse_conversation_summaries(session_path, "TestProject")

    by_id = {c.conversation_id: c for c in conversations}
    assert by_id[1].model == "claude-sonnet-4"
    assert by_id[2].model == "claude-sonnet-5"


def test_search_result_reports_model_from_last_turn_even_when_match_is_earlier(tmp_path):
    session_path = tmp_path / "session-1.jsonl"
    _write_lines(
        session_path,
        [
            _user_entry("user-1", None, "2026-06-25T12:00:00.000Z", "find this thing"),
            _assistant_entry(
                "assistant-1", "user-1", "2026-06-25T12:00:01.000Z",
                "found the needle", "claude-sonnet-4",
            ),
            _user_entry("user-2", "assistant-1", "2026-06-25T12:00:02.000Z", "unrelated followup"),
            _assistant_entry(
                "assistant-2", "user-2", "2026-06-25T12:00:03.000Z",
                "unrelated reply after a model switch", "claude-sonnet-5",
            ),
        ],
    )

    result = search_session_file(session_path, "needle", "TestProject")

    assert result is not None
    assert result.match_count == 1
    assert result.model == "claude-sonnet-5"


def test_scan_last_model_returns_none_for_session_without_model_field(tmp_path):
    session_path = tmp_path / "session-1.jsonl"
    _write_lines(
        session_path,
        [
            _user_entry("user-1", None, "2026-06-25T12:00:00.000Z", "hi"),
        ],
    )

    assert scan_last_model(session_path) is None


def test_synthetic_rate_limit_notice_is_not_reported_as_last_model(tmp_path):
    """
    Claude Code appends a synthetic assistant entry (model="<synthetic>")
    when a rate-limit notice like "You've hit your weekly limit" is shown.
    That is not a real model turn, so it must not override the last real
    model used.
    """
    session_path = tmp_path / "session-1.jsonl"
    _write_lines(
        session_path,
        [
            _user_entry("user-1", None, "2026-06-25T12:00:00.000Z", "hi"),
            _assistant_entry(
                "assistant-1", "user-1", "2026-06-25T12:00:01.000Z",
                "real reply", "claude-fable-5",
            ),
            _assistant_entry(
                "assistant-2", "assistant-1", "2026-06-25T12:00:02.000Z",
                "You've hit your weekly limit", "<synthetic>",
            ),
        ],
    )

    summary = parse_session_summary(session_path, "TestProject")
    session = parse_full_session(session_path, "TestProject")

    assert summary is not None
    assert summary.model == "claude-fable-5"
    assert session is not None
    assert session.model == "claude-fable-5"
    assert scan_last_model(session_path) == "claude-fable-5"
