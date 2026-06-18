import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from codex_sessions_cli.client import CodexSessionsClient
from codex_sessions_cli.main import app
from codex_sessions_cli.models import TimelineEventType, create_timeline_event
from codex_sessions_cli.parsers import load_rollout_index


SESSION_ID = "019db111-1111-7111-8111-111111111111"
SKILL_SESSION_ID = "019db222-2222-7222-8222-222222222222"


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


def write_partially_malformed_rollout(codex_home: Path, cwd: str) -> Path:
    session_dir = codex_home / "sessions" / "2026" / "04" / "22"
    session_dir.mkdir(parents=True)
    rollout_path = session_dir / "rollout-2026-04-22T11-00-00-partial-session.jsonl"
    records = [
        {
            "timestamp": "2026-04-22T16:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": "partial-session",
                "timestamp": "2026-04-22T16:00:00.000Z",
                "cwd": cwd,
            },
        },
        '{"timestamp": "2026-04-22T16:00:01.000Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "unterminated}',
        {
            "timestamp": "2026-04-22T16:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "valid tail"}],
            },
        },
    ]
    lines = [json.dumps(records[0]), records[1], json.dumps(records[2])]
    rollout_path.write_text("\n".join(lines) + "\n")
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


def write_skill_rollout(codex_home: Path, cwd: str) -> Path:
    session_dir = codex_home / "sessions" / "2026" / "04" / "24"
    session_dir.mkdir(parents=True)
    rollout_path = session_dir / f"rollout-2026-04-24T10-00-00-{SKILL_SESSION_ID}.jsonl"
    records = [
        {
            "timestamp": "2026-04-24T15:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": SKILL_SESSION_ID,
                "timestamp": "2026-04-24T15:00:00.000Z",
                "cwd": cwd,
            },
        },
        {
            "timestamp": "2026-04-24T15:00:01.000Z",
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "$project-manager review this",
                "images": [],
                "local_images": [],
                "text_elements": [],
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

    def test_todo_get_uses_encoded_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            write_minimal_current_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            with patch.object(
                client,
                "_load_rollouts",
                side_effect=AssertionError("todo get must load the encoded session directly"),
            ):
                todo = client.get_todo(f"{SESSION_ID}:call-plan:1")

            self.assertEqual(todo.content, "Write parser tests")

    def test_skill_get_uses_encoded_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            write_skill_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            with patch.object(
                client,
                "_load_rollouts",
                side_effect=AssertionError("skill get must load the encoded session directly"),
            ):
                skill = client.get_skill(f"{SKILL_SESSION_ID}:2:project-manager")

            self.assertEqual(skill.name, "project-manager")

    def test_subagent_activity_scan_does_not_materialize_all_tool_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            with patch.object(
                client,
                "list_tool_calls",
                side_effect=AssertionError("subagent scans must not go through list_tool_calls"),
            ):
                subagents = client.list_subagent_activity(project_path=project_path, limit=1)
                subagent = client.get_subagent_activity("call-subagent")

            self.assertEqual(len(subagents), 1)
            self.assertEqual(subagents[0].id, "call-subagent")
            self.assertEqual(subagent.id, "call-subagent")

    def test_subagent_activity_get_loads_only_rollout_containing_call_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            matching_path = write_rollout(codex_home, project_path)
            write_minimal_current_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)
            loaded_paths = []

            from codex_sessions_cli.client import load_rollout as real_load_rollout

            def record_load(path):
                loaded_paths.append(path)
                return real_load_rollout(path)

            with patch.object(
                client,
                "_load_rollout_indexes",
                side_effect=AssertionError("subagent get must not build the full rollout index"),
            ), patch("codex_sessions_cli.client.load_rollout", side_effect=record_load):
                subagent = client.get_subagent_activity("call-subagent")

            self.assertEqual(subagent.id, "call-subagent")
            self.assertEqual(loaded_paths, [matching_path])

    def test_tool_call_scan_stops_without_full_materialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            with patch.object(
                client,
                "_apply_limit",
                side_effect=AssertionError("tool call scans must stop before list materialization"),
            ):
                tool_calls = client.list_tool_calls(project_path=project_path, limit=1)
                tool_call = client.get_tool_call("call-subagent")

            self.assertEqual(len(tool_calls), 1)
            self.assertEqual(tool_calls[0].id, "call-subagent")
            self.assertEqual(tool_call.id, "call-subagent")

    def test_tool_call_get_loads_only_rollout_containing_call_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            matching_path = write_rollout(codex_home, project_path)
            write_minimal_current_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)
            loaded_paths = []

            from codex_sessions_cli.client import load_rollout as real_load_rollout

            def record_load(path):
                loaded_paths.append(path)
                return real_load_rollout(path)

            with patch("codex_sessions_cli.client.load_rollout", side_effect=record_load):
                tool_call = client.get_tool_call("call-subagent")

            self.assertEqual(tool_call.id, "call-subagent")
            self.assertEqual(loaded_paths, [matching_path])

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

    def test_rollout_index_reads_last_record_without_full_file_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            rollout_path = write_rollout(codex_home, project_path)
            content = rollout_path.read_text()
            rollout_path.write_text(content + "\n\n")

            index = load_rollout_index(rollout_path)

            self.assertEqual(index.session_id, SESSION_ID)
            self.assertEqual(index.cwd, project_path)
            self.assertEqual(index.last_activity, "2026-04-21T15:00:08.000Z")

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

    def test_indexed_scans_skip_rollouts_with_invalid_middle_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            malformed_path = write_partially_malformed_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            sessions = client.list_sessions(project_path=project_path)

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].id, SESSION_ID)
            self.assertEqual(len(client.load_errors), 1)
            self.assertIn(
                f"{malformed_path}:2 invalid JSON: Unterminated string starting at",
                client.load_errors[0],
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

    def test_session_scoped_queries_do_not_broad_scan_all_rollouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)
            client = CodexSessionsClient(codex_home=codex_home)

            with patch.object(
                client,
                "_load_rollouts",
                side_effect=AssertionError("session-scoped queries must not broad-scan all rollouts"),
            ):
                session = client.get_session(SESSION_ID)
                tool_calls = client.list_tool_calls(session_id=SESSION_ID)
                timeline = client.list_timeline(session_id=SESSION_ID)

            self.assertEqual(session.id, SESSION_ID)
            self.assertEqual([call.name for call in tool_calls], ["spawn_agent", "exec_command", "update_plan"])
            self.assertEqual(timeline[0].event_type, "message")
            self.assertEqual(timeline[-1].event_type, "session")

class CodexSessionsCliTests(unittest.TestCase):
    def test_console_script_uses_error_handling_entrypoint(self):
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"

        self.assertIn(
            'codex-sessions = "codex_sessions_cli.main:main"',
            pyproject.read_text(),
        )

    def test_auth_status_uses_shared_profiles_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)

            runner = CliRunner()
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                result = runner.invoke(app, ["auth", "status"])

            self.assertEqual(result.exit_code, 0, result.output)
            data = json.loads(result.output)
            self.assertEqual(sorted(data.keys()), ["profiles"])
            self.assertEqual(len(data["profiles"]), 1)
            profile = data["profiles"][0]
            self.assertEqual(profile["name"], "default")
            self.assertTrue(profile["authenticated"])
            self.assertIn("custom", profile["credential_types"])
            self.assertEqual(profile["credential_types"]["custom"]["api_test"], "passed")

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

    def test_timeline_list_passes_requested_limit_to_client(self):
        class FakeClient:
            def __init__(self):
                self.limit = None

            def list_timeline(self, project, project_path, session_id, since, limit):
                self.limit = limit
                return [
                    create_timeline_event(
                        {
                            "id": "event-1",
                            "time": "2026-04-21T15:00:00.000Z",
                            "session_id": SESSION_ID,
                            "event_type": TimelineEventType.SESSION,
                        }
                    )
                ]

        fake_client = FakeClient()
        runner = CliRunner()
        with patch("codex_sessions_cli.commands.timeline.get_client", return_value=fake_client):
            result = runner.invoke(app, ["timeline", "list", "--limit", "1"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(fake_client.limit, 1)

    def test_timeline_get_outputs_single_event_from_list_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)

            runner = CliRunner()
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}):
                list_result = runner.invoke(app, ["timeline", "list", "--limit", "1"])

                self.assertEqual(list_result.exit_code, 0, list_result.output)
                event_id = json.loads(list_result.output)[0]["id"]
                get_result = runner.invoke(app, ["timeline", "get", event_id])

            self.assertEqual(get_result.exit_code, 0, get_result.output)
            self.assertEqual(json.loads(get_result.output)["id"], event_id)

    def test_session_name_resolution_and_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            project_path = str(Path(tmp) / "Project One")
            write_rollout(codex_home, project_path)

            # Write session_index.jsonl
            codex_home.mkdir(parents=True, exist_ok=True)
            index_path = codex_home / "session_index.jsonl"
            index_path.write_text(json.dumps({"id": SESSION_ID, "thread_name": "Test Handoff Task"}) + "\n")

            client = CodexSessionsClient(codex_home=codex_home)
            self.assertEqual(client._resolve_session_id("Test Handoff Task"), SESSION_ID)
            self.assertEqual(client._resolve_session_id("test handoff task"), SESSION_ID)

            sessions = client.list_sessions()
            self.assertEqual(sessions[0].name, "Test Handoff Task")

            # Search by session name
            found = client.search_sessions("Handoff")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].id, SESSION_ID)


if __name__ == "__main__":
    unittest.main()
