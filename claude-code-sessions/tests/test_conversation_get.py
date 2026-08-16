"""Regression tests for exact conversation detail lookup."""
import json

from typer.testing import CliRunner

from claude_code_sessions_cli.client import ClaudeCodeSessionsClient
from claude_code_sessions_cli.commands import conversations as conversations_cmd


SESSION_ID = "c34e0971-2e9e-45d1-b264-e3c513e1dd54"
runner = CliRunner()


def _make_client(tmp_path):
    claude_dir = tmp_path / ".claude"
    projects_dir = claude_dir / "projects"
    projects_dir.mkdir(parents=True)
    client = ClaudeCodeSessionsClient.__new__(ClaudeCodeSessionsClient)
    client.claude_dir = claude_dir
    client.projects_dir = projects_dir
    client.todos_dir = claude_dir / "todos"
    return client, projects_dir


def _write_conversations(project_dir, count):
    project_dir.mkdir(parents=True)
    entries = []
    for index in range(count):
        user_uuid = f"user-{index + 1}"
        timestamp_prefix = f"2026-07-28T10:{index // 60:02d}:{index % 60:02d}"
        entries.append(
            {
                "type": "user",
                "uuid": user_uuid,
                "parentUuid": None,
                "timestamp": f"{timestamp_prefix}.000Z",
                "message": {"content": f"Question {index + 1}"},
            }
        )
        entries.append(
            {
                "type": "assistant",
                "uuid": f"assistant-{index + 1}",
                "parentUuid": user_uuid,
                "timestamp": f"{timestamp_prefix}.500Z",
                "message": {
                    "content": [
                        {"type": "text", "text": f"Answer {index + 1}"}
                    ],
                    "usage": {"input_tokens": 5, "output_tokens": 3},
                },
            }
        )
    session_file = project_dir / f"{SESSION_ID}.jsonl"
    session_file.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )


def test_get_conversation_finds_id_hidden_by_default_list_limit(tmp_path):
    client, projects_dir = _make_client(tmp_path)
    project_dir = projects_dir / "-Users-adam-Dropbox-GitRepos-TestProject"
    _write_conversations(project_dir, count=112)

    listed = client.list_conversations("TestProject", session_id=SESSION_ID)
    conversation = client.get_conversation("TestProject", SESSION_ID, 1)

    assert len(listed) == 100
    assert all(item.conversation_id != 1 for item in listed)
    assert conversation is not None
    assert conversation.conversation_id == 1
    assert conversation.message_count == 2
    assert conversation.messages == [
        {
            "type": "user",
            "timestamp": "2026-07-28T10:00:00.000Z",
            "content": "Question 1",
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-28T10:00:00.500Z",
            "content": "Answer 1",
        },
    ]


def test_conversations_get_prints_metadata_and_message_content(
    tmp_path,
    monkeypatch,
):
    client, projects_dir = _make_client(tmp_path)
    project_dir = projects_dir / "-Users-adam-Dropbox-GitRepos-TestProject"
    _write_conversations(project_dir, count=2)
    monkeypatch.setattr(conversations_cmd, "get_client", lambda: client)

    result = runner.invoke(
        conversations_cmd.app,
        ["get", f"{SESSION_ID}:2", "--project", "TestProject"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["conversation_id"] == 2
    assert [message["content"] for message in payload["messages"]] == [
        "Question 2",
        "Answer 2",
    ]
