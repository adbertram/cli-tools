"""Tests for dsh event parsing."""
from pathlib import Path

import pytest

from deepseek_sessions_cli.logfile import load_log
from deepseek_sessions_cli.parsers import (
    decode_arguments,
    extract_approvals,
    extract_goals,
    extract_retries,
    extract_skill_invocations,
    extract_steps,
    extract_subagent_spawns,
    extract_timeline,
    extract_todos,
    extract_tool_calls,
    extract_turns,
    parse_conversation_summaries,
    parse_full_session,
    parse_include_prompts,
    parse_session_summary,
    parse_since,
    project_key,
    project_name_from_cwd,
    resolve_date_selector,
    search_log,
)


# ==================== Project key encoding ====================


@pytest.mark.parametrize(
    "cwd, expected",
    [
        # Separator runs collapse to one dash and leading dashes are stripped.
        ("/work/demo", "--work-demo--"),
        ("/private/tmp", "--private-tmp--"),
        (
            "/Users/adam/Dropbox/GitRepos/Agents/LegoScout",
            "--Users-adam-Dropbox-GitRepos-Agents-LegoScout--",
        ),
        # Unsafe code units escape as ~XXXX.
        ("/a b", "--a~0020b--"),
        ("/a~b", "--a~007Eb--"),
        # A Windows drive separator is a separator too.
        ("C:\\work", "--C-work--"),
        # Runs of separators collapse rather than repeat.
        ("//a//b", "--a-b--"),
    ],
)
def test_project_key_matches_dsh(cwd, expected):
    """projectKey must reproduce dsh's own directory naming exactly."""
    assert project_key(cwd) == expected


def test_project_key_rejects_empty():
    with pytest.raises(ValueError, match="empty project path"):
        project_key("")


def test_project_name_is_the_cwd_basename():
    assert project_name_from_cwd("/work/demo") == "demo"
    assert project_name_from_cwd(None) == "_no-cwd"


# ==================== Session summary ====================


def test_session_summary_fields(simple_log: Path):
    summary = parse_session_summary(load_log(simple_log), "demo")

    assert summary.custom_title == "Demo session"
    assert summary.title_source == "provider"
    assert summary.project_path == "/work/demo"
    assert summary.model == "deepseek-v4-pro"
    assert summary.provider == "deepseek-official"
    assert summary.turn_count == 2
    # Turn 2's step opened but never closed.
    assert summary.step_count == 1
    assert summary.open_step_count == 1
    assert summary.retry_count == 1
    assert summary.has_errors is True
    assert summary.has_subagents is False
    assert summary.message_count == 2  # one user, one assistant
    assert summary.tool_call_count == 1
    assert summary.conversation_count == 1


def test_token_totals_use_uncached_input(simple_log: Path):
    """dsh's inputTokens excludes cache reads, so they add rather than overlap."""
    summary = parse_session_summary(load_log(simple_log), "demo")

    assert summary.total_input_tokens == 100
    assert summary.total_output_tokens == 50
    assert summary.total_cache_read_tokens == 1000
    assert summary.total_reasoning_tokens == 20
    # 100 + 50 + int(1000 * 0.1)
    assert summary.effective_tokens == 250


# ==================== Messages and tool calls ====================


def test_full_session_messages_and_tool_pairing(simple_log: Path):
    session = parse_full_session(load_log(simple_log), "demo")

    user, assistant = session.messages
    assert user.type == "user"
    assert user.content == "do the thing"
    assert assistant.type == "assistant"
    assert assistant.content == "done"
    assert assistant.reasoning == "thinking hard"
    assert assistant.model == "deepseek-v4-pro"

    call = assistant.tool_calls[0]
    assert call.tool == "bash"
    assert call.input == {"command": "ls"}
    assert call.result == "file.txt"
    assert call.status.value == "success"

    assert session.permission_preset is None
    assert [error["scope"] for error in session.errors] == ["turn"]


def test_tool_call_summaries(simple_log: Path):
    rows = extract_tool_calls(load_log(simple_log), "demo")
    assert len(rows) == 1
    assert rows[0].tool == "bash"
    assert rows[0].turn == 1
    assert rows[0].is_sidechain is False


def test_decode_arguments_handles_every_shape():
    assert decode_arguments('{"a": 1}') == {"a": 1}
    assert decode_arguments({"a": 1}) == {"a": 1}
    # Non-object JSON and invalid JSON are preserved, never dropped.
    assert decode_arguments("[1, 2]") == {"_raw": [1, 2]}
    assert decode_arguments("not json") == {"_raw": "not json"}
    assert decode_arguments(None) == {}


# ==================== Todos, retries, skills ====================


def test_todos_come_from_the_final_write(simple_log: Path):
    todos = extract_todos(load_log(simple_log))
    assert [todo.content for todo in todos] == ["first", "second"]
    assert [todo.status.value for todo in todos] == ["completed", "pending"]
    assert todos[0].id.endswith(":0")


def test_retries_join_started_events(simple_log: Path):
    retries = extract_retries(load_log(simple_log), "demo")
    assert len(retries) == 1
    retry = retries[0]
    assert retry.error_code == "TIMEOUT"
    assert retry.attempt == 1
    assert retry.max_retries == 2
    assert retry.started is True
    assert retry.started_at


def test_turns_carry_finish_reason_and_error(simple_log: Path):
    turns = extract_turns(load_log(simple_log), "demo")
    assert [turn.turn for turn in turns] == [1, 2]

    first, second = turns
    assert first.finish_reason == "completed"
    assert first.step_count == 1
    assert first.duration_ms == 800
    assert first.tool_call_count == 1

    assert second.finish_reason == "error"
    assert second.error_code == "TIMEOUT"
    assert second.error_message == "provider gave up"
    assert second.open_step_count == 1
    assert second.retry_count == 1


def test_steps_scoped_to_a_turn(simple_log: Path):
    steps = extract_steps(load_log(simple_log), "demo", turn=1)
    assert len(steps) == 1
    assert steps[0].input_tokens == 100
    assert steps[0].tool_call_count == 1


# ==================== Subagents ====================


def test_subagent_spawn_links_parent_to_child(subagent_pair, sessions_root: Path):
    parent_id, child_id = subagent_pair
    parent = load_log(sessions_root / "--work-demo--" / parent_id / "session.jsonl.zstd")

    spawns = extract_subagent_spawns(parent)
    assert child_id in spawns
    assert spawns[child_id]["parent_tool_call_id"] == "call_sub"
    assert spawns[child_id]["description"] == "Crawl a source"
    assert spawns[child_id]["prompt"] == "You are a worker agent."


def test_subagent_summary_from_child_log(subagent_pair, sessions_root: Path):
    from deepseek_sessions_cli.parsers import summarize_subagent_session

    parent_id, child_id = subagent_pair
    project = sessions_root / "--work-demo--"
    parent = load_log(project / parent_id / "session.jsonl.zstd")
    child = load_log(project / child_id / "session.jsonl.zstd")

    summary = summarize_subagent_session(
        child, "demo", extract_subagent_spawns(parent)[child_id]
    )
    assert summary.label == "Crawl a source"
    assert summary.parent_session_id == parent_id
    assert summary.parent_tool_call_id == "call_sub"
    assert summary.model == "deepseek-v4-pro"
    assert summary.mode == "continuable"
    assert summary.status == "completed"
    assert summary.report == "crawl finished"
    assert summary.delegation_depth == 1


# ==================== Conversations (compaction) ====================


def test_compaction_splits_conversations(compacted_log, sessions_root: Path):
    log = load_log(
        sessions_root / "--work-demo--" / compacted_log / "session.jsonl.zstd"
    )

    summary = parse_session_summary(log, "demo")
    assert summary.conversation_count == 2

    first, second = parse_conversation_summaries(log, "demo")
    assert first.conversation_id == 1
    assert first.started_by == "session-start"
    assert first.user_message_count == 1

    assert second.conversation_id == 2
    assert second.started_by == "compaction"
    assert second.compaction_summary == "we discussed the thing"
    assert second.user_message_count == 1


def test_session_without_compaction_has_one_conversation(simple_log: Path):
    log = load_log(simple_log)
    assert len(parse_conversation_summaries(log, "demo")) == 1


# ==================== Timeline ====================


def test_timeline_covers_every_recorded_activity(simple_log: Path):
    entries = extract_timeline(load_log(simple_log), "demo")
    kinds = [entry.event_type.value for entry in entries]

    assert "user_message" in kinds
    assert "assistant_message" in kinds
    assert "tool_call" in kinds
    assert "todo_write" in kinds
    assert "retry" in kinds
    assert "error" in kinds
    # Reasoning is hidden unless asked for.
    assert "thinking" not in kinds

    assert [entry.timestamp for entry in entries] == sorted(
        entry.timestamp for entry in entries
    )


def test_timeline_show_thinking_adds_reasoning(simple_log: Path):
    entries = extract_timeline(load_log(simple_log), "demo", show_thinking=True)
    thinking = [e for e in entries if e.event_type.value == "thinking"]
    assert len(thinking) == 1
    assert thinking[0].output == "thinking hard"


def test_timeline_marks_subagent_start(subagent_pair, sessions_root: Path):
    parent_id, child_id = subagent_pair
    parent = load_log(sessions_root / "--work-demo--" / parent_id / "session.jsonl.zstd")

    entries = extract_timeline(parent, "demo", subagent_labels={child_id: "Crawl a source"})
    starts = [e for e in entries if e.event_type.value == "subagent_start"]
    assert len(starts) == 1
    assert starts[0].agent_id == child_id
    assert starts[0].agent_name == "Crawl a source"


# ==================== Search ====================


def test_search_finds_user_assistant_and_tool_text(simple_log: Path):
    log = load_log(simple_log)

    result = search_log(log, "thing", "demo")
    assert result is not None
    assert result.match_count == 1
    assert result.matches[0].role == "user"

    assert search_log(log, "file.txt", "demo").matches[0].role == "tool"
    assert search_log(log, "nothing here at all", "demo") is None


# ==================== Option parsing ====================


def test_parse_since_units():
    assert parse_since("5h") < parse_since("1h")
    assert parse_since("7d") < parse_since("1d")
    with pytest.raises(ValueError, match="Invalid --since"):
        parse_since("tomorrow")


def test_parse_include_prompts():
    assert parse_include_prompts("first:3,last:2") == (3, 2)
    assert parse_include_prompts("first:1") == (1, 0)
    with pytest.raises(ValueError):
        parse_include_prompts("first")
    with pytest.raises(ValueError):
        parse_include_prompts("first:-1")


def test_resolve_date_selector():
    assert resolve_date_selector(None, None, None) is None

    start, end = resolve_date_selector("2026-08-19", None, None)
    assert start.date().isoformat() == "2026-08-19"
    assert end.hour == 23

    start, end = resolve_date_selector(None, "2026-08-01..2026-08-05", None)
    assert (end.date() - start.date()).days == 4

    with pytest.raises(ValueError, match="invalid --date value"):
        resolve_date_selector("19-08-2026", None, None)
    with pytest.raises(ValueError, match="start must be on or before end"):
        resolve_date_selector(None, "2026-08-05..2026-08-01", None)
    with pytest.raises(ValueError, match="invalid --date-alias"):
        resolve_date_selector(None, None, "next_week")


# ==================== Empty-signal groups ====================


def test_absent_signals_return_empty_lists(simple_log: Path):
    """A session with no approvals, goals, or skills yields empty lists."""
    log = load_log(simple_log)
    assert extract_approvals(log, "demo") == []
    assert extract_goals(log, "demo") == []
    assert extract_skill_invocations(log, "demo") == []
