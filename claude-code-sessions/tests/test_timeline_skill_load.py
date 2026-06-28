import json

from claude_code_sessions_cli.commands import timeline as timeline_commands
from claude_code_sessions_cli.models import TimelineEntry, TimelineEventType
from claude_code_sessions_cli.parsers import extract_timeline_from_session


def test_timeline_names_skill_tool_calls_from_input(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "msg-1",
                "timestamp": "2026-06-25T12:00:00.000Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Skill",
                            "input": {"skill": "things-cli"},
                        }
                    ],
                    "usage": {},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")

    assert len(timeline) == 1
    assert timeline[0].event_type.value == "skill_load"
    assert timeline[0].name == "things-cli"


def test_timeline_names_command_name_user_messages_as_skill_load(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": "msg-1",
                "timestamp": "2026-06-25T12:00:00.000Z",
                "message": {
                    "content": "<command-name>/agent-tasks</command-name>",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")

    assert len(timeline) == 1
    assert timeline[0].event_type.value == "skill_load"
    assert timeline[0].name == "agent-tasks"


def test_timeline_names_mcp_tool_calls_from_raw_tool_name(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "msg-1",
                "timestamp": "2026-06-25T12:00:00.000Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "mcp__scheduled-tasks__list_scheduled_tasks",
                            "input": {},
                        }
                    ],
                    "usage": {},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")

    assert len(timeline) == 1
    assert timeline[0].event_type.value == "mcp_call"
    assert timeline[0].name == "scheduled-tasks.list_scheduled_tasks"


def test_timeline_attaches_main_model_to_user_turn(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "user-1",
                        "timestamp": "2026-06-25T12:00:00.000Z",
                        "message": {"content": "Summarize the plan"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "assistant-1",
                        "timestamp": "2026-06-25T12:00:01.000Z",
                        "message": {
                            "model": "claude-main",
                            "content": [{"type": "text", "text": "Done"}],
                            "usage": {"input_tokens": 10, "output_tokens": 2},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")
    rows_by_id = {entry.id: entry for entry in timeline}

    assert rows_by_id["user-1"].model == "claude-main"
    assert rows_by_id["user-1"].turn_id == "user-1"
    assert rows_by_id["user-1"].turn_number == 1
    assert rows_by_id["assistant-1"].model == "claude-main"
    assert rows_by_id["assistant-1"].turn_id == "user-1"
    assert rows_by_id["assistant-1"].turn_number == 1


def test_timeline_groups_assistant_work_until_next_user_request(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "user-1",
                        "timestamp": "2026-06-25T12:00:00.000Z",
                        "message": {"content": "First request"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "assistant-1",
                        "timestamp": "2026-06-25T12:00:01.000Z",
                        "message": {
                            "content": [
                                {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {}}
                            ],
                            "usage": {"input_tokens": 10, "output_tokens": 2},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "tool-result-1",
                        "timestamp": "2026-06-25T12:00:02.000Z",
                        "message": {
                            "content": [
                                {"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "assistant-2",
                        "timestamp": "2026-06-25T12:00:03.000Z",
                        "message": {
                            "content": [
                                {"type": "tool_use", "id": "tool-2", "name": "Bash", "input": {}}
                            ],
                            "usage": {"input_tokens": 11, "output_tokens": 3},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "user-2",
                        "timestamp": "2026-06-25T12:00:04.000Z",
                        "message": {"content": "Second request"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "assistant-3",
                        "timestamp": "2026-06-25T12:00:05.000Z",
                        "message": {
                            "content": [
                                {"type": "tool_use", "id": "tool-3", "name": "Read", "input": {}}
                            ],
                            "usage": {"input_tokens": 12, "output_tokens": 4},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")
    rows_by_id = {entry.id: entry for entry in timeline}

    assert rows_by_id["user-1"].turn_id == "user-1"
    assert rows_by_id["tool-1"].turn_id == "user-1"
    assert rows_by_id["tool-2"].turn_id == "user-1"
    assert rows_by_id["user-1"].turn_number == 1
    assert rows_by_id["tool-1"].turn_number == 1
    assert rows_by_id["tool-2"].turn_number == 1
    assert rows_by_id["user-2"].turn_id == "user-2"
    assert rows_by_id["tool-3"].turn_id == "user-2"
    assert rows_by_id["user-2"].turn_number == 2
    assert rows_by_id["tool-3"].turn_number == 2


def test_consolidated_timeline_table_should_include_date_when_formatting_timestamp(monkeypatch):
    class FakeClient:
        def resolve_session_id(self, identifier, project=None):
            return identifier

        def get_timeline(self, **kwargs):
            return [
                TimelineEntry(
                    id="entry-1",
                    session_id="session-123",
                    timestamp="2026-06-25T12:00:00.000Z",
                    event_type=TimelineEventType.SKILL_LOAD,
                    name="agent-tasks",
                    model="claude-test",
                    status="invoked",
                    turn_id="assistant-msg-1",
                    turn_number=12,
                    turn_cost=3456,
                )
            ]

    captured = {}

    def capture_table(data, columns, headers, max_columns=6, **kwargs):
        captured["data"] = data
        captured["columns"] = columns
        captured["headers"] = headers

    monkeypatch.setattr(timeline_commands, "get_client", lambda: FakeClient())
    monkeypatch.setattr(timeline_commands, "print_table", capture_table)

    timeline_commands.consolidated_timeline(
        session_id="session-123",
        session_name=None,
        project="TestProject",
        table=True,
        wide=False,
        limit=500,
        show_agent_tools=True,
        show_thinking=False,
        filter=None,
    )

    assert captured["data"][0]["time"] == "0625-0700"
    assert captured["data"][0]["turn_number_fmt"] == "12"
    assert captured["data"][0]["model"] == "claude-test"
    assert captured["data"][0]["turn_cost_fmt"] == "3,456"
    assert captured["headers"][:8] == ["Date/Time", "Turn", "Model", "Type", "Agent", "Name", "Status", "Cost"]


def test_timeline_formats_subagent_start_type_as_agent_invocation():
    assert timeline_commands.format_event_type(TimelineEventType.SUBAGENT_START) == "agent_invocation"


def test_timeline_formats_subagent_tool_type_as_tool():
    assert timeline_commands.format_event_type(TimelineEventType.SUBAGENT_TOOL) == "tool"


def test_timeline_includes_nested_calls_for_parallel_subagents(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "user-1",
                        "timestamp": "2026-06-25T11:59:59.000Z",
                        "message": {"content": "Inspect parser with parallel subagents"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "main-msg-1",
                        "timestamp": "2026-06-25T12:00:00.000Z",
                        "message": {
                            "model": "claude-main",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "task-1",
                                    "name": "Task",
                                    "input": {
                                        "subagent_type": "explorer",
                                        "description": "inspect parser",
                                        "prompt": "Inspect parser behavior",
                                    },
                                },
                                {
                                    "type": "tool_use",
                                    "id": "task-2",
                                    "name": "Task",
                                    "input": {
                                        "subagent_type": "worker",
                                        "description": "patch parser",
                                        "prompt": "Patch parser behavior",
                                    },
                                },
                            ],
                            "usage": {},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subagents_dir = tmp_path / "session-123" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-alpha.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "alpha-prompt",
                        "timestamp": "2026-06-25T12:00:01.000Z",
                        "message": {"content": "Inspect parser behavior"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "alpha-tools",
                        "timestamp": "2026-06-25T12:00:02.000Z",
                        "message": {
                            "model": "claude-alpha",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "alpha-skill",
                                    "name": "Skill",
                                    "input": {"skill": "agent-tasks"},
                                },
                                {
                                    "type": "tool_use",
                                    "id": "alpha-bash",
                                    "name": "Bash",
                                    "input": {"command": "pwd"},
                                },
                            ],
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (subagents_dir / "agent-beta.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "beta-prompt",
                        "timestamp": "2026-06-25T12:00:01.000Z",
                        "message": {"content": [{"type": "text", "text": "Patch parser behavior"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "beta-tools",
                        "timestamp": "2026-06-25T12:00:03.000Z",
                        "message": {
                            "model": "claude-beta",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "beta-mcp",
                                    "name": "mcp__scheduled-tasks__list_scheduled_tasks",
                                    "input": {},
                                }
                            ],
                            "usage": {},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")
    rows_by_id = {entry.id: entry for entry in timeline}

    assert rows_by_id["task-1"].event_type.value == "subagent_start"
    assert rows_by_id["task-2"].event_type.value == "subagent_start"
    assert rows_by_id["task-1"].model == "claude-main"
    assert rows_by_id["task-2"].model == "claude-main"
    assert rows_by_id["task-1"].turn_number == 1
    assert rows_by_id["task-2"].turn_number == 1
    assert rows_by_id["task-1"].turn_id == "user-1"
    assert rows_by_id["alpha-skill"].event_type.value == "skill_load"
    assert rows_by_id["alpha-skill"].name == "agent-tasks"
    assert rows_by_id["alpha-skill"].model == "claude-alpha"
    assert rows_by_id["alpha-skill"].agent_id == "alpha"
    assert rows_by_id["alpha-skill"].agent_name == "explorer"
    assert rows_by_id["alpha-skill"].turn_number == 1
    assert rows_by_id["alpha-skill"].turn_id == "user-1"
    assert rows_by_id["alpha-skill"].turn_cost == 15
    assert rows_by_id["alpha-bash"].event_type.value == "subagent_tool"
    assert rows_by_id["alpha-bash"].name == "Bash"
    assert rows_by_id["alpha-bash"].model == "claude-alpha"
    assert rows_by_id["alpha-bash"].agent_id == "alpha"
    assert rows_by_id["alpha-bash"].turn_number == 1
    assert rows_by_id["alpha-bash"].turn_id == "user-1"
    assert rows_by_id["alpha-bash"].turn_cost is None
    assert rows_by_id["beta-mcp"].event_type.value == "mcp_call"
    assert rows_by_id["beta-mcp"].name == "scheduled-tasks.list_scheduled_tasks"
    assert rows_by_id["beta-mcp"].model == "claude-beta"
    assert rows_by_id["beta-mcp"].agent_id == "beta"
    assert rows_by_id["beta-mcp"].agent_name == "worker"
    assert rows_by_id["beta-mcp"].turn_number == 1
    assert rows_by_id["beta-mcp"].turn_id == "user-1"


def test_timeline_treats_agent_tool_as_subagent_start_and_names_nested_tools(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "user-1",
                        "timestamp": "2026-06-25T11:59:59.000Z",
                        "message": {"content": "Inspect Agent parser behavior"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "main-msg-1",
                        "timestamp": "2026-06-25T12:00:00.000Z",
                        "message": {
                            "model": "claude-main",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "agent-launch",
                                    "name": "Agent",
                                    "input": {
                                        "subagent_type": "cli-tool-expert",
                                        "description": "inspect parser",
                                        "prompt": "Inspect Agent parser behavior",
                                        "run_in_background": True,
                                    },
                                },
                            ],
                            "usage": {},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subagents_dir = tmp_path / "session-123" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-alpha.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "alpha-prompt",
                        "timestamp": "2026-06-25T12:00:01.000Z",
                        "message": {"content": "Inspect Agent parser behavior"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "alpha-tools",
                        "timestamp": "2026-06-25T12:00:02.000Z",
                        "message": {
                            "model": "claude-alpha",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "alpha-read",
                                    "name": "Read",
                                    "input": {"file_path": "parsers.py"},
                                }
                            ],
                            "usage": {},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")
    rows_by_id = {entry.id: entry for entry in timeline}

    assert rows_by_id["agent-launch"].event_type.value == "subagent_start"
    assert rows_by_id["agent-launch"].name == "cli-tool-expert"
    assert rows_by_id["agent-launch"].model == "claude-main"
    assert rows_by_id["agent-launch"].agent_name == "cli-tool-expert"
    assert rows_by_id["agent-launch"].turn_id == "user-1"
    assert rows_by_id["alpha-read"].event_type.value == "subagent_tool"
    assert rows_by_id["alpha-read"].model == "claude-alpha"
    assert rows_by_id["alpha-read"].agent_id == "alpha"
    assert rows_by_id["alpha-read"].agent_name == "cli-tool-expert"
    assert rows_by_id["alpha-read"].turn_id == "user-1"


def test_timeline_adds_start_row_for_unmatched_subagent_file(tmp_path):
    session_path = tmp_path / "session-123.jsonl"
    session_path.write_text("", encoding="utf-8")
    subagents_dir = tmp_path / "session-123" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-orphan.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "orphan-prompt",
                        "timestamp": "2026-06-25T12:00:01.000Z",
                        "message": {"content": "Inspect orphan parser behavior"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "orphan-tools",
                        "timestamp": "2026-06-25T12:00:02.000Z",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "orphan-read",
                                    "name": "Read",
                                    "input": {"file_path": "parsers.py"},
                                }
                            ],
                            "usage": {},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = extract_timeline_from_session(session_path, "TestProject")
    rows_by_id = {entry.id: entry for entry in timeline}

    assert rows_by_id["agent-orphan"].event_type.value == "subagent_start"
    assert rows_by_id["agent-orphan"].name == "orphan"
    assert rows_by_id["agent-orphan"].agent_name == "orphan"
    assert rows_by_id["orphan-read"].event_type.value == "subagent_tool"
    assert rows_by_id["orphan-read"].agent_id == "orphan"
    assert rows_by_id["orphan-read"].agent_name == "orphan"
