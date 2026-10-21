import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from codex_sessions_cli.client import CodexSessionsClient
from codex_sessions_cli.main import app
from codex_sessions_cli.models import TimelineEventType
from codex_sessions_cli.parsers import extract_user_prompts


SESSION_ID = "019dc111-1111-7111-8111-111111111111"


def _meta(cwd: str) -> dict:
    return {
        "timestamp": "2026-04-21T15:00:00.000Z",
        "type": "session_meta",
        "payload": {
            "id": SESSION_ID,
            "timestamp": "2026-04-21T15:00:00.000Z",
            "cwd": cwd,
        },
    }


def _turn(cwd: str) -> dict:
    return {
        "timestamp": "2026-04-21T15:00:01.000Z",
        "type": "turn_context",
        "payload": {
            "turn_id": "turn-1",
            "cwd": cwd,
            "model": "gpt-5.4",
        },
    }


def _write_rollout(codex_home: Path, cwd: str, records: list[dict]) -> Path:
    session_dir = codex_home / "sessions" / "2026" / "04" / "21"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"rollout-2026-04-21T10-00-00-{SESSION_ID}.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


def _message(timestamp: str, role: str, text: str, phase=None) -> dict:
    content_type = "input_text" if role == "user" else "output_text"
    payload = {
        "type": "message",
        "role": role,
        "content": [{"type": content_type, "text": text}],
    }
    if phase:
        payload["phase"] = phase
    return {"timestamp": timestamp, "type": "response_item", "payload": payload}


def _item_completed(timestamp: str, item: dict) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "item_completed", "item": item},
    }


class TranscriptNormalizationTests(unittest.TestCase):
    def test_old_function_and_new_custom_recordings_match_in_public_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            common = [
                _meta(cwd),
                _turn(cwd),
                _message("2026-04-21T15:00:02.000Z", "user", "run it"),
            ]
            old_records = common + [
                {
                    "timestamp": "2026-04-21T15:00:03.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "printf ok"}),
                        "call_id": "call-1",
                    },
                },
                {
                    "timestamp": "2026-04-21T15:00:04.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": json.dumps({"stdout": "ok"}),
                    },
                },
                _message("2026-04-21T15:00:05.000Z", "assistant", "Done"),
            ]
            path = _write_rollout(codex_home, cwd, old_records)
            old_client = CodexSessionsClient(codex_home=codex_home)
            old_summary = old_client.list_sessions()[0].model_dump(mode="json")
            old_conversation = old_client.list_conversations()[0].model_dump(mode="json")
            old_detail = old_client.get_session(SESSION_ID)
            old_messages = [event.model_dump(mode="json") for event in old_detail.messages]
            old_calls = [call.model_dump(mode="json") for call in old_client.list_tool_calls()]
            old_timeline = [event.model_dump(mode="json") for event in old_client.get_timeline(SESSION_ID)]

            new_records = common + [
                {
                    "timestamp": "2026-04-21T15:00:03.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "id": "ctc-1",
                        "status": "completed",
                        "name": "exec_command",
                        "input": {"cmd": "printf ok"},
                        "call_id": "call-1",
                    },
                },
                {
                    "timestamp": "2026-04-21T15:00:04.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "id": "ctco-1",
                        "call_id": "call-1",
                        "output": {"stdout": "ok"},
                    },
                },
                _message("2026-04-21T15:00:05.000Z", "assistant", "Done"),
            ]
            path.write_text("\n".join(json.dumps(record) for record in new_records) + "\n")
            new_client = CodexSessionsClient(codex_home=codex_home)
            new_summary = new_client.list_sessions()[0].model_dump(mode="json")
            new_conversation = new_client.list_conversations()[0].model_dump(mode="json")
            new_detail = new_client.get_session(SESSION_ID)
            new_messages = [event.model_dump(mode="json") for event in new_detail.messages]
            new_calls = [call.model_dump(mode="json") for call in new_client.list_tool_calls()]
            new_timeline = [event.model_dump(mode="json") for event in new_client.get_timeline(SESSION_ID)]

            self.assertEqual(old_summary, new_summary)
            self.assertEqual(old_conversation, new_conversation)
            self.assertEqual(old_messages, new_messages)
            self.assertEqual(old_calls, new_calls)
            self.assertEqual(old_timeline, new_timeline)
            self.assertEqual(new_calls[0]["arguments"], {"cmd": "printf ok"})
            self.assertEqual(new_calls[0]["output"], {"stdout": "ok"})

    def test_output_without_call_id_is_a_standalone_timeline_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            _write_rollout(
                codex_home,
                cwd,
                [
                    _meta(cwd),
                    _turn(cwd),
                    {
                        "timestamp": "2026-04-21T15:00:02.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "id": "fco-standalone",
                            "name": "create_thread",
                            "output": "delegated",
                        },
                    },
                ],
            )
            client = CodexSessionsClient(codex_home=codex_home)

            detail = client.get_session(SESSION_ID)
            timeline = client.get_timeline(SESSION_ID)
            result = next(event for event in timeline if event.id == "fco-standalone")

            self.assertEqual(client.list_tool_calls(), [])
            self.assertEqual(detail.tool_calls, [])
            self.assertEqual(result.event_type, TimelineEventType.TOOL_RESULT)
            self.assertEqual(result.name, "create_thread")
            self.assertEqual(result.output, "delegated")

    def test_tool_search_name_comes_from_the_payload_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            _write_rollout(
                codex_home,
                cwd,
                [
                    _meta(cwd),
                    _turn(cwd),
                    {
                        "timestamp": "2026-04-21T15:00:02.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "tool_search_call",
                            "call_id": "search-1",
                            "arguments": {"query": "calendar"},
                            "execution": "client",
                        },
                    },
                    {
                        "timestamp": "2026-04-21T15:00:03.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "tool_search_output",
                            "call_id": "search-1",
                            "output": {"tools": [{"name": "calendar"}]},
                        },
                    },
                ],
            )
            client = CodexSessionsClient(codex_home=codex_home)

            call = client.get_tool_call("search-1")
            timeline = client.get_timeline(SESSION_ID)
            call_event = next(
                event for event in timeline if event.event_type == TimelineEventType.TOOL_CALL
            )

            self.assertEqual(call.name, "tool_search")
            self.assertEqual(call.arguments, {"query": "calendar", "execution": "client"})
            self.assertEqual(call.output, {"tools": [{"name": "calendar"}]})
            self.assertEqual(call_event.input, {"query": "calendar", "execution": "client"})
            self.assertEqual(
                [event.name for event in timeline if event.event_type.value in {"tool_call", "tool_result"}],
                ["tool_search", "tool_search"],
            )

    def test_prompt_and_skill_views_skip_injected_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            rollout_path = _write_rollout(
                codex_home,
                cwd,
                [
                    _meta(cwd),
                    _turn(cwd),
                    _item_completed(
                        "2026-04-21T15:00:02.000Z",
                        {
                            "type": "UserMessage",
                            "id": "agents-item",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "# AGENTS.md instructions for /tmp/project $agents-skill",
                                }
                            ],
                        },
                    ),
                    _message(
                        "2026-04-21T15:00:03.000Z",
                        "user",
                        "<environment_context>cwd=$env-skill</environment_context>",
                    ),
                    _message(
                        "2026-04-21T15:00:04.000Z",
                        "user",
                        "$visible-skill run the task",
                    ),
                ],
            )
            client = CodexSessionsClient(codex_home=codex_home)

            prompts = extract_user_prompts(
                rollout_path,
                first_n=5,
                last_n=5,
                max_chars=400,
                clean=False,
            )
            skills = client.list_skills()

            self.assertEqual(
                prompts,
                {
                    "first_user_prompts": ["$visible-skill run the task"],
                    "last_user_prompts": ["$visible-skill run the task"],
                },
            )
            self.assertEqual([skill.name for skill in skills], ["visible-skill"])

            runner = CliRunner()
            with patch.dict(
                "os.environ",
                {
                    "CODEX_HOME": str(codex_home),
                    "CODEX_SESSIONS_CODEX_HOME": "",
                    "CODEX_SESSIONS_CODEX_PROFILE": "",
                },
                clear=False,
            ):
                result = runner.invoke(
                    app,
                    [
                        "sessions",
                        "list",
                        "--filter",
                        f"id:eq:{SESSION_ID}",
                        "--include-prompts",
                        "first:5,last:5",
                        "--properties",
                        "id,first_user_prompts,last_user_prompts",
                    ],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(
                json.loads(result.output),
                [
                    {
                        "id": SESSION_ID,
                        "first_user_prompts": ["$visible-skill run the task"],
                        "last_user_prompts": ["$visible-skill run the task"],
                    }
                ],
            )

    def test_session_search_skips_injected_user_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            _write_rollout(
                codex_home,
                cwd,
                [
                    _meta(cwd),
                    _turn(cwd),
                    _item_completed(
                        "2026-04-21T15:00:02.000Z",
                        {
                            "type": "UserMessage",
                            "id": "agents-item",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "# AGENTS.md instructions for /tmp/project injected_agents_needle",
                                }
                            ],
                        },
                    ),
                    _message(
                        "2026-04-21T15:00:03.000Z",
                        "user",
                        "<environment_context>injected_env_needle</environment_context>",
                    ),
                    _message(
                        "2026-04-21T15:00:04.000Z",
                        "user",
                        "real_prompt_needle",
                    ),
                    _message(
                        "2026-04-21T15:00:05.000Z",
                        "assistant",
                        "assistant_needle",
                    ),
                    {
                        "timestamp": "2026-04-21T15:00:06.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call",
                            "call_id": "tool-search-text",
                            "name": "exec",
                            "input": "tool_input_needle",
                        },
                    },
                    {
                        "timestamp": "2026-04-21T15:00:07.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "call_id": "tool-search-text",
                            "output": "tool_output_needle",
                        },
                    },
                ],
            )

            runner = CliRunner()
            with patch.dict(
                "os.environ",
                {
                    "CODEX_HOME": str(codex_home),
                    "CODEX_SESSIONS_CODEX_HOME": "",
                    "CODEX_SESSIONS_CODEX_PROFILE": "",
                },
                clear=False,
            ):
                def search(query: str):
                    result = runner.invoke(
                        app,
                        [
                            "sessions",
                            "search",
                            query,
                            "--limit",
                            "10",
                            "--properties",
                            "id",
                        ],
                    )
                    self.assertEqual(result.exit_code, 0, result.output)
                    return json.loads(result.output)

                self.assertEqual(search("injected_agents_needle"), [])
                self.assertEqual(search("injected_env_needle"), [])
                for query in (
                    "real_prompt_needle",
                    "assistant_needle",
                    "tool_input_needle",
                    "tool_output_needle",
                ):
                    self.assertEqual(search(query), [{"id": SESSION_ID}])

    def test_call_status_precedes_output_status_and_marks_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            _write_rollout(
                codex_home,
                cwd,
                [
                    _meta(cwd),
                    _turn(cwd),
                    {
                        "timestamp": "2026-04-21T15:00:02.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "call_id": "function-failed",
                            "name": "exec_command",
                            "arguments": {"cmd": "false"},
                            "status": "failed",
                        },
                    },
                    {
                        "timestamp": "2026-04-21T15:00:03.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "function-failed",
                            "output": "failed",
                        },
                    },
                    {
                        "timestamp": "2026-04-21T15:00:04.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call",
                            "call_id": "custom-failed",
                            "name": "exec",
                            "input": "throw new Error()",
                            "status": "failed",
                        },
                    },
                    {
                        "timestamp": "2026-04-21T15:00:05.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "call_id": "custom-failed",
                            "output": "failed",
                            "status": "completed",
                        },
                    },
                    {
                        "timestamp": "2026-04-21T15:00:06.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "tool_search_call",
                            "call_id": "search-failed",
                            "arguments": {"query": "calendar"},
                            "execution": "client",
                            "status": "failed",
                        },
                    },
                    {
                        "timestamp": "2026-04-21T15:00:07.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "tool_search_output",
                            "call_id": "search-failed",
                            "output": None,
                            "status": "completed",
                        },
                    },
                ],
            )
            client = CodexSessionsClient(codex_home=codex_home)

            calls = client.list_tool_calls()
            timeline = client.get_timeline(SESSION_ID)
            call_events = [
                event for event in timeline if event.event_type == TimelineEventType.TOOL_CALL
            ]

            self.assertEqual([call.status for call in calls], ["failed", "failed", "failed"])
            self.assertEqual([event.status for event in call_events], ["failed", "failed", "failed"])
            self.assertTrue(client.list_sessions()[0].has_errors)

    def test_item_completed_messages_fill_gaps_and_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            _write_rollout(
                codex_home,
                cwd,
                [
                    _meta(cwd),
                    _turn(cwd),
                    _message("2026-04-21T15:00:02.000Z", "user", "real request"),
                    _item_completed(
                        "2026-04-21T15:00:02.000Z",
                        {
                            "type": "UserMessage",
                            "id": "user-item",
                            "content": [{"type": "text", "text": "real request"}],
                        },
                    ),
                    _item_completed(
                        "2026-04-21T15:00:03.000Z",
                        {
                            "type": "AgentMessage",
                            "id": "agent-item",
                            "phase": "commentary",
                            "content": [{"type": "Text", "text": "first update"}],
                        },
                    ),
                ],
            )
            client = CodexSessionsClient(codex_home=codex_home)

            session = client.list_sessions()[0]
            conversation = client.list_conversations()[0]
            detail = client.get_session(SESSION_ID)

            self.assertEqual(session.message_count, 2)
            self.assertEqual([(event.role, event.text) for event in detail.messages], [
                ("user", "real request"),
                ("assistant", "first update"),
            ])
            self.assertEqual(conversation.message_count, 2)
            self.assertEqual(conversation.summary, "real request")

    def test_conversation_summary_skips_agents_context_and_uses_assistant_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "Project")
            _write_rollout(
                codex_home,
                cwd,
                [
                    _meta(cwd),
                    _turn(cwd),
                    _message(
                        "2026-04-21T15:00:02.000Z",
                        "user",
                        "# AGENTS.md instructions for /tmp/project\n\n<INSTRUCTIONS>rule</INSTRUCTIONS>",
                    ),
                    _message(
                        "2026-04-21T15:00:03.000Z",
                        "assistant",
                        "I’m tracing the current flow.",
                        "commentary",
                    ),
                ],
            )
            client = CodexSessionsClient(codex_home=codex_home)

            conversation = client.list_conversations()[0]

            self.assertEqual(conversation.summary, "I’m tracing the current flow.")

    def test_target_shape_has_65_calls_and_working_session_and_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            cwd = str(Path(tmp) / "CourseCraft")
            records = [
                _meta(cwd),
                _turn(cwd),
                _message(
                    "2026-04-21T15:00:02.000Z",
                    "user",
                    "# AGENTS.md instructions for /tmp/CourseCraft\n\n<INSTRUCTIONS>rules</INSTRUCTIONS>",
                ),
                _message("2026-04-21T15:00:03.000Z", "assistant", "Update one"),
                _message("2026-04-21T15:00:04.000Z", "assistant", "Update two"),
                _message("2026-04-21T15:00:05.000Z", "assistant", "Update three"),
            ]
            for index in range(65):
                call_id = f"call-{index}"
                minute = 1 + index // 60
                second = index % 60
                records.extend(
                    [
                        {
                            "timestamp": f"2026-04-21T15:{minute:02d}:{second:02d}.000Z",
                            "type": "response_item",
                            "payload": {
                                "type": "custom_tool_call",
                                "id": f"ctc-{index}",
                                "status": "completed",
                                "call_id": call_id,
                                "name": "exec",
                                "input": f"raw input {index}",
                            },
                        },
                        {
                            "timestamp": f"2026-04-21T15:{minute:02d}:{second:02d}.500Z",
                            "type": "response_item",
                            "payload": {
                                "type": "custom_tool_call_output",
                                "id": f"ctco-{index}",
                                "call_id": call_id,
                                "output": {"index": index},
                            },
                        },
                    ]
                )
            records.append(
                {
                    "timestamp": "2026-04-21T15:02:30.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "id": "fco-standalone",
                        "name": "create_thread",
                        "output": "delegated",
                    },
                }
            )
            records.append(
                _item_completed(
                    "2026-04-21T15:02:31.000Z",
                    {
                        "type": "CommandExecution",
                        "id": "exec-item-only",
                        "status": "completed",
                        "aggregated_output": "ignored by the generic timeline",
                    },
                )
            )
            _write_rollout(codex_home, cwd, records)
            client = CodexSessionsClient(codex_home=codex_home)

            session = client.list_sessions()[0]
            conversation = client.list_conversations()[0]
            detail = client.get_session(SESSION_ID)
            timeline = client.get_timeline(SESSION_ID)

            self.assertEqual(session.message_count, 4)
            self.assertEqual(session.tool_call_count, 65)
            self.assertFalse(session.has_subagents)
            self.assertEqual(conversation.message_count, 4)
            self.assertEqual(conversation.tool_call_count, 65)
            self.assertEqual(conversation.summary, "Update one")
            self.assertEqual(len(detail.tool_calls), 65)
            self.assertEqual(
                sum(event.event_type == TimelineEventType.TOOL_CALL for event in timeline),
                65,
            )
            self.assertEqual(
                sum(
                    event.event_type == TimelineEventType.TOOL_RESULT
                    and event.id == "fco-standalone"
                    for event in timeline
                ),
                1,
            )
            self.assertFalse(
                any(event.name == "item_completed" for event in timeline)
            )

            runner = CliRunner()
            with patch.dict(
                "os.environ",
                {
                    "CODEX_HOME": str(codex_home),
                    "CODEX_SESSIONS_CODEX_HOME": "",
                    "CODEX_SESSIONS_CODEX_PROFILE": "",
                },
                clear=False,
            ):
                session_result = runner.invoke(
                    app,
                    [
                        "sessions",
                        "get",
                        SESSION_ID,
                        "--properties",
                        "id,message_count,tool_call_count",
                    ],
                )
                timeline_result = runner.invoke(
                    app,
                    [
                        "timeline",
                        "consolidated",
                        "--session-id",
                        SESSION_ID,
                        "--properties",
                        "event_type,name",
                    ],
                )
                todos_result = runner.invoke(
                    app,
                    ["todos", "list", "--session-id", SESSION_ID],
                )

            self.assertEqual(session_result.exit_code, 0, session_result.output)
            self.assertEqual(
                json.loads(session_result.output),
                {"id": SESSION_ID, "message_count": 4, "tool_call_count": 65},
            )
            self.assertEqual(timeline_result.exit_code, 0, timeline_result.output)
            self.assertGreater(len(json.loads(timeline_result.output)), 130)
            self.assertEqual(todos_result.exit_code, 0, todos_result.output)
            self.assertEqual(json.loads(todos_result.output), [])


if __name__ == "__main__":
    unittest.main()
