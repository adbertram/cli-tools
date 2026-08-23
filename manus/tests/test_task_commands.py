import json

import pytest
import typer
from typer.testing import CliRunner

from manus_cli.commands import task as task_commands
from manus_cli.commands import usage as usage_commands
from manus_cli.main import app


class FakeClient:
    def __init__(self):
        self.calls = []

    def create_task(self, **kwargs):
        self.calls.append(("create_task", kwargs))
        return {"task_id": "task-1", "ok": True}

    def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        return {"task_id": kwargs["task_id"], "ok": True}

    def update_task(self, **kwargs):
        self.calls.append(("update_task", kwargs))
        return {"task_id": kwargs["task_id"], "task_title": kwargs.get("title")}

    def available_credits(self):
        self.calls.append(("available_credits", {}))
        return {"total_credits": 25}


def test_task_help_shows_v2_commands_and_compat_continue_alias(monkeypatch):
    result = CliRunner().invoke(task_commands.app, ["--help"])

    assert result.exit_code == 0
    assert "create" in result.stdout
    assert "send" in result.stdout
    assert "messages" in result.stdout
    assert "update" in result.stdout
    assert "stop" in result.stdout
    assert "delete" in result.stdout
    assert "confirm" in result.stdout
    assert "continue" in result.stdout


def test_task_list_help_exposes_required_cli_flags(monkeypatch):
    result = CliRunner().invoke(task_commands.app, ["list", "--help"])

    assert result.exit_code == 0
    assert "--limit" in result.stdout
    assert "--filter" in result.stdout
    assert "--properties" in result.stdout


def test_task_create_builds_v2_message_payload(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(task_commands, "get_client", lambda: fake_client)

    result = CliRunner().invoke(
        task_commands.app,
        [
            "create",
            "Build a summary",
            "--no-wait",
            "--agent-profile",
            "manus-1.6-max",
            "--share-visibility",
            "team",
            "--connector",
            "slack",
            "--enable-skill",
            "skill-1",
            "--force-skill",
            "skill-2",
            "--content-part",
            '{"type":"file","file_url":"https://example.com/report.txt"}',
            "--structured-output-schema",
            '{"type":"object","properties":{},"required":[],"additionalProperties":false}',
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"task_id": "task-1", "ok": True}
    assert fake_client.calls == [
        (
            "create_task",
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "Build a summary"},
                        {"type": "file", "file_url": "https://example.com/report.txt"},
                    ],
                    "connectors": ["slack"],
                    "enable_skills": ["skill-1"],
                    "force_skills": ["skill-2"],
                },
                "agent_profile": "manus-1.6-max",
                "project_id": None,
                "locale": None,
                "interactive_mode": False,
                "hide_in_task_list": False,
                "share_visibility": "team",
                "title": None,
                "structured_output_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        )
    ]


def test_task_continue_alias_uses_v2_send_message(monkeypatch, capsys):
    fake_client = FakeClient()
    monkeypatch.setattr(task_commands, "get_client", lambda: fake_client)

    task_commands._send_task_message(
        task_id="task-9",
        prompt="Follow up",
        prompt_file=None,
        content_part=None,
        agent_profile=None,
        wait=False,
        timeout=900.0,
        poll=2.0,
        connector=None,
        enable_skill=None,
        force_skill=None,
        structured_output_schema=None,
        structured_output_schema_file=None,
        quiet=False,
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"task_id": "task-9", "ok": True}
    assert fake_client.calls == [
        (
            "send_message",
            {
                "task_id": "task-9",
                "message": {"content": "Follow up"},
                "agent_profile": None,
                "structured_output_schema": None,
            },
        )
    ]


def test_task_update_requires_a_mutation_option(monkeypatch, capsys):
    monkeypatch.setattr(task_commands, "get_client", lambda: FakeClient())

    with pytest.raises(typer.Exit) as exc_info:
        task_commands.task_update("task-1", None, None, False, False)

    assert exc_info.value is not None
    captured = capsys.readouterr()
    assert "Provide at least one update option" in captured.err


def test_main_help_includes_task_group(monkeypatch):
    from cli_tools_shared import command_registry

    monkeypatch.setattr(command_registry, "_check_credentials", lambda config, cred_types, cli_name: None)

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "task" in result.stdout
    assert "auth" in result.stdout
    assert "usage" in result.stdout
    assert "cache" in result.stdout


def test_usage_available_credits_outputs_balance(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(usage_commands, "get_client", lambda: fake_client)

    result = CliRunner().invoke(app, ["usage", "available-credits"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"total_credits": 25}
    assert fake_client.calls == [("available_credits", {})]
