import json

from claude_code_sessions_cli.parsers import extract_subagents_from_session


def _write_lines(path, entries):
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def _spawn_entry(tool_name, tool_input, timestamp, tool_id="toolu_1"):
    return {
        "type": "assistant",
        "uuid": "assistant-1",
        "timestamp": timestamp,
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input,
                }
            ],
        },
    }


def test_legacy_task_call_uses_entry_timestamp(tmp_path):
    # Regression: the entry timestamp was referenced but never assigned,
    # raising UnboundLocalError for any session containing a Task tool call.
    session_path = tmp_path / "session-legacy.jsonl"
    _write_lines(
        session_path,
        [
            _spawn_entry(
                "Task",
                {
                    "subagent_type": "Explore",
                    "description": "Explore the repo",
                    "prompt": "Find the config loader",
                },
                timestamp="2026-07-21T10:00:00.000Z",
            ),
        ],
    )

    subagents = extract_subagents_from_session(session_path, "TestProject")

    assert len(subagents) == 1
    record = subagents[0]
    assert record["timestamp"] == "2026-07-21T10:00:00.000Z"
    assert record["type"] == "Explore"
    assert record["name"] is None


def test_agent_call_recognized_with_name(tmp_path):
    # "Agent" is the current tool name for subagent invocations; it carries
    # a "name" input that legacy "Task" calls do not.
    session_path = tmp_path / "session-agent.jsonl"
    _write_lines(
        session_path,
        [
            _spawn_entry(
                "Agent",
                {
                    "subagent_type": "demo-expert",
                    "name": "demo60-action-summary",
                    "description": "Remediate demo 60 Action Summary",
                    "prompt": "Build task: complete the run proof",
                    "run_in_background": True,
                },
                timestamp="2026-07-21T22:54:43.228Z",
            ),
        ],
    )

    subagents = extract_subagents_from_session(session_path, "TestProject")

    assert len(subagents) == 1
    record = subagents[0]
    assert record["timestamp"] == "2026-07-21T22:54:43.228Z"
    assert record["type"] == "demo-expert"
    assert record["name"] == "demo60-action-summary"
    assert record["description"] == "Remediate demo 60 Action Summary"


def test_agent_call_matches_subagent_file_stats(tmp_path):
    prompt = "Build task: complete the run proof"
    session_path = tmp_path / "session-match.jsonl"
    _write_lines(
        session_path,
        [
            _spawn_entry(
                "Agent",
                {
                    "subagent_type": "demo-expert",
                    "name": "demo60-action-summary",
                    "description": "Remediate demo 60 Action Summary",
                    "prompt": prompt,
                },
                timestamp="2026-07-21T22:54:43.228Z",
            ),
        ],
    )

    subagents_dir = tmp_path / "session-match" / "subagents"
    subagents_dir.mkdir(parents=True)
    _write_lines(
        subagents_dir / "agent-abc123.jsonl",
        [
            {
                "type": "user",
                "uuid": "sub-user-1",
                "timestamp": "2026-07-21T22:54:43.231Z",
                "message": {"content": [{"type": "text", "text": prompt}]},
            },
            {
                "type": "assistant",
                "uuid": "sub-assistant-1",
                "timestamp": "2026-07-21T22:54:50.000Z",
                "message": {
                    "content": [{"type": "text", "text": "Working on it"}],
                    "usage": {"input_tokens": 12, "output_tokens": 3},
                },
            },
        ],
    )

    subagents = extract_subagents_from_session(session_path, "TestProject")

    assert len(subagents) == 1
    record = subagents[0]
    assert record["agent_id"] == "abc123"
    assert record["message_count"] == 2
    assert record["total_output_tokens"] == 3
