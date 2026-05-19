import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from codex_sessions_cli.client import CodexSessionsClient
from codex_sessions_cli.main import app


SESSION_ID = "019db111-1111-7111-8111-111111111111"


def write_rollout(codex_home: Path, cwd: str, source="cli") -> Path:
    session_dir = codex_home / "sessions" / "2026" / "04" / "21"
    session_dir.mkdir(parents=True)
    rollout_path = session_dir / f"rollout-2026-04-21T10-00-00-{SESSION_ID}.jsonl"
    records = [
        {
            "timestamp": "2026-04-21T15:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": SESSION_ID,
                "timestamp": "2026-04-21T15:00:00.000Z",
                "cwd": cwd,
                "originator": "codex-tui",
                "cli_version": "0.122.0",
                "source": source,
                "model_provider": "openai",
                "git": {
                    "commit_hash": "abc123",
                    "branch": "feature/codex-sessions",
                    "repository_url": "git@example.com:repo.git",
                },
            },
        },
        {
            "timestamp": "2026-04-21T15:00:01.000Z",
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-1",
                "cwd": cwd,
                "model": "gpt-5.4",
            },
        },
        {
            "timestamp": "2026-04-21T15:00:02.000Z",
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "build the parser",
                "images": [],
                "local_images": [],
                "text_elements": [],
            },
        },
        {
            "timestamp": "2026-04-21T15:00:02.100Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "build the parser"}],
            },
        },
        {
            "timestamp": "2026-04-21T15:00:03.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "arguments": json.dumps(
                    {"agent_type": "explorer", "message": "inspect rollout schema"}
                ),
                "call_id": "call-subagent",
            },
        },
        {
            "timestamp": "2026-04-21T15:00:04.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-subagent",
                "output": json.dumps(
                    {"agent_id": "agent-1", "nickname": "schema explorer"}
                ),
            },
        },
        {
            "timestamp": "2026-04-21T15:00:05.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "rg session_meta"}),
                "call_id": "call-tool",
            },
        },
        {
            "timestamp": "2026-04-21T15:00:06.000Z",
            "type": "event_msg",
            "payload": {
                "type": "exec_command_end",
                "call_id": "call-tool",
                "command": ["rg", "session_meta"],
                "cwd": cwd,
                "stdout": "session_meta",
                "stderr": "",
                "exit_code": 0,
                "duration": {"secs": 1, "nanos": 0},
                "status": "completed",
            },
        },
        {
            "timestamp": "2026-04-21T15:00:07.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "update_plan",
                "arguments": json.dumps(
                    {"plan": [{"step": "Write parser tests", "status": "completed"}]}
                ),
                "call_id": "call-plan",
            },
        },
        {
            "timestamp": "2026-04-21T15:00:08.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Implemented."}],
                "phase": "final",
            },
        },
    ]
    rollout_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return rollout_path


def write_legacy_rollout(codex_home: Path, cwd: str) -> Path:
    session_dir = codex_home / "sessions" / "2025" / "09" / "06"
    session_dir.mkdir(parents=True)
    rollout_path = session_dir / "rollout-2025-09-06T11-30-24-legacy-session.jsonl"
    records = [
        {
            "id": "legacy-session",
            "timestamp": "2025-09-06T11:30:24.587Z",
            "instructions": None,
            "git": {"branch": "main"},
        },
        {"record_type": "state"},
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": f"<environment_context>\n  <cwd>{cwd}</cwd>\n</environment_context>",
                }
            ],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Legacy session parsed."}],
        },
    ]
    rollout_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return rollout_path


def write_malformed_rollout(codex_home: Path) -> Path:
    session_dir = codex_home / "sessions" / "2026" / "04" / "22"
    session_dir.mkdir(parents=True)
    rollout_path = session_dir / "rollout-2026-04-22T10-00-00-bad-session.jsonl"
    rollout_path.write_text("not-json\n")
    return rollout_path


def write_minimal_current_rollout(codex_home: Path, cwd: str) -> Path:
    session_dir = codex_home / "sessions" / "2026" / "04" / "23"
    session_dir.mkdir(parents=True)
    rollout_path = session_dir / "rollout-2026-04-23T10-00-00-minimal-session.jsonl"
    records = [
        {
            "timestamp": "2026-04-23T15:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": "minimal-session",
                "timestamp": "2026-04-23T15:00:00.000Z",
                "cwd": cwd,
            },
        },
        {
            "timestamp": "2026-04-23T15:00:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "minimal"}],
            },
        },
    ]
    rollout_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return rollout_path


class CodexSessionsClientTests(unittest.TestCase):
    def test_lists_project_and_session_summaries_from_rollout_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)

            client = CodexSessionsClient(codex_home=codex_home)

            projects = client.list_projects()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0].name, "Project One")
            self.assertEqual(projects[0].full_path, project_path)

            sessions = client.list_sessions(project_path=project_path)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].id, SESSION_ID)
            self.assertEqual(sessions[0].project, "Project One")
            self.assertEqual(sessions[0].message_count, 2)
            self.assertEqual(sessions[0].tool_call_count, 3)
            self.assertTrue(sessions[0].has_subagents)
            self.assertFalse(sessions[0].has_errors)
            self.assertEqual(sessions[0].git_branch, "feature/codex-sessions")

    def test_extracts_tool_calls_subagents_todos_and_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            tool_calls = client.list_tool_calls(project_path=project_path)
            self.assertEqual([call.name for call in tool_calls], ["spawn_agent", "exec_command", "update_plan"])
            self.assertEqual(tool_calls[1].status, "completed")

            subagents = client.list_subagent_activity(project_path=project_path)
            self.assertEqual(len(subagents), 1)
            self.assertEqual(subagents[0].agent_type, "explorer")
            self.assertEqual(subagents[0].name, "schema explorer")

            todos = client.list_todos(project_path=project_path)
            self.assertEqual(len(todos), 1)
            self.assertEqual(todos[0].content, "Write parser tests")
            self.assertEqual(todos[0].status, "completed")

            timeline = client.get_timeline(SESSION_ID)
            self.assertEqual(timeline[0].event_type, "session")
            self.assertIn("tool_call", [event.event_type for event in timeline])
            self.assertEqual(timeline[-1].event_type, "message")

    def test_parses_legacy_top_level_rollout_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Legacy Project")
            write_legacy_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            sessions = client.list_sessions(project_path=project_path)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].id, "legacy-session")
            self.assertEqual(sessions[0].project_path, project_path)
            self.assertEqual(sessions[0].message_count, 2)
            self.assertIsNone(sessions[0].cli_version)

    def test_preserves_structured_session_meta_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Subagent Project")
            source = {
                "subagent": {
                    "thread_spawn_id": "call-subagent",
                    "parent_role": "psu-expert",
                }
            }
            write_rollout(codex_home, project_path, source=source)
            client = CodexSessionsClient(codex_home=codex_home)

            sessions = client.list_sessions(project_path=project_path)

            self.assertEqual(sessions[0].source, source)

    def test_current_rollout_optional_session_meta_fields_are_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Minimal Project")
            write_minimal_current_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            sessions = client.list_sessions(project_path=project_path)

            self.assertEqual(sessions[0].id, "minimal-session")
            self.assertIsNone(sessions[0].source)
            self.assertIsNone(sessions[0].cli_version)
            self.assertIsNone(sessions[0].model_provider)

    def test_conversations_list_groups_records_without_per_record_rescans(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            with patch(
                "codex_sessions_cli.client.conversation_id_for_record",
                side_effect=AssertionError("conversation records must be grouped in one pass"),
            ):
                conversations = client.list_conversations(project_path=project_path)

            self.assertEqual(len(conversations), 1)
            self.assertEqual(conversations[0].id, f"{SESSION_ID}:1")
            self.assertEqual(conversations[0].summary, "build the parser")

    def test_broad_scans_skip_malformed_rollouts_and_record_load_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            malformed_path = write_malformed_rollout(codex_home)
            client = CodexSessionsClient(codex_home=codex_home)

            sessions = client.list_sessions()

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].id, SESSION_ID)
            self.assertEqual(
                client.load_errors,
                [f"{malformed_path}:1 invalid JSON: Expecting value"],
            )

    def test_broad_scans_skip_missing_rollout_paths_and_record_load_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            rollout_path = write_rollout(codex_home, project_path)
            missing_path = (
                codex_home
                / "sessions"
                / "2026"
                / "04"
                / "24"
                / "rollout-2026-04-24T10-00-00-missing-session.jsonl"
            )
            client = CodexSessionsClient(codex_home=codex_home)

            with patch(
                "codex_sessions_cli.client.iter_rollout_paths",
                return_value=[rollout_path, missing_path],
            ):
                sessions = client.list_sessions()

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].id, SESSION_ID)
            self.assertEqual(
                client.load_errors,
                [f"{missing_path}: file not found"],
            )

class CodexSessionsCliTests(unittest.TestCase):
    def test_sessions_list_outputs_json_for_matching_project_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)

            runner = CliRunner()
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}):
                result = runner.invoke(
                    app,
                    ["sessions", "list", "--project-path", project_path, "--limit", "1"],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            data = json.loads(result.output)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["id"], SESSION_ID)
            self.assertEqual(data[0]["project_path"], project_path)

    def test_timeline_consolidated_outputs_events_for_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)

            runner = CliRunner()
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}):
                result = runner.invoke(
                    app,
                    ["timeline", "consolidated", "--session-id", SESSION_ID],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            data = json.loads(result.output)
            self.assertEqual(data[0]["event_type"], "session")
            self.assertIn("tool_call", [event["event_type"] for event in data])


if __name__ == "__main__":
    unittest.main()
