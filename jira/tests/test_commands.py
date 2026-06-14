import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import jira_cli.config as jira_config
from jira_cli.commands import projects, tickets
from jira_cli.main import app


runner = CliRunner()

SAMPLE_ISSUE = {
    "id": "10001",
    "key": "ENG-1",
    "summary": "Broken workflow",
    "status": "To Do",
    "issue_type": "Bug",
    "project": "ENG",
    "assignee": "Al",
    "description": "First line\nSecond line",
    "self": "https://acme.atlassian.net/rest/api/3/issue/10001",
    "updated": "2026-06-02T12:00:00.000+0000",
}

SAMPLE_PROJECT = {
    "id": "10000",
    "key": "ENG",
    "name": "Engineering",
    "project_type": "software",
    "style": "classic",
    "simplified": False,
    "category": "Internal",
    "lead": "Al",
}


def test_jira_commands_should_declare_one_profile_auth_type():
    command_maps = [projects.COMMAND_CREDENTIALS, tickets.COMMAND_CREDENTIALS]

    for command_map in command_maps:
        for command_name, credentials in command_map.items():
            profile_auth_types = [
                value for value in credentials if value in jira_config.Config.PROFILE_AUTH_TYPES
            ]
            assert profile_auth_types == [jira_config.OAUTH_3LO_AUTH_TYPE], command_name
            assert "custom" in credentials


@pytest.fixture(autouse=True)
def isolated_cli_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    tool_dir = tmp_path / "cli-tools" / "jira"
    profile_dir = tool_dir / "authentication_profiles" / "default"
    profile_dir.mkdir(parents=True)
    (tool_dir / ".env").write_text("BASE_URL=https://acme.atlassian.net\n")
    (profile_dir / ".env").write_text(
        "ACTIVE=true\n"
        f"AUTH_TYPE={jira_config.OAUTH_3LO_AUTH_TYPE}\n"
        "CLIENT_ID=client-id\n"
        "CLIENT_SECRET=client-secret\n"
        "ACCESS_TOKEN=access-token\n"
        "REFRESH_TOKEN=refresh-token\n"
        "TOKEN_EXPIRES_AT=9999999999\n"
        "CLOUD_ID=cloud-id\n"
        "REDIRECT_URI=http://localhost\n"
    )
    jira_config._configs.clear()


def test_root_help_should_expose_tickets_and_projects_groups():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "tickets" in result.stdout
    assert "projects" in result.stdout


def test_tickets_list_should_emit_json_by_default(monkeypatch):
    fake_client = SimpleNamespace(
        list_tickets=lambda **_: [SAMPLE_ISSUE],
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(app, ["tickets", "list", "--profile", "default"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["key"] == "ENG-1"


def test_tickets_list_table_should_render_table(monkeypatch):
    fake_client = SimpleNamespace(
        list_tickets=lambda **_: [SAMPLE_ISSUE],
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(app, ["tickets", "list", "--table", "--profile", "default"])

    assert result.exit_code == 0
    assert "ENG-1" in result.stdout
    assert "Broken workflow" in result.stdout


def test_tickets_get_table_should_render_field_value_rows(monkeypatch):
    fake_client = SimpleNamespace(
        get_ticket=lambda issue_id: {**SAMPLE_ISSUE, "requested": issue_id},
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(app, ["tickets", "get", "ENG-1", "--table", "--profile", "default"])

    assert result.exit_code == 0
    assert "requested" in result.stdout
    assert "ENG-1" in result.stdout


def test_tickets_get_should_emit_json_object_by_default(monkeypatch):
    fake_client = SimpleNamespace(
        get_ticket=lambda issue_id: {**SAMPLE_ISSUE, "requested": issue_id},
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(app, ["tickets", "get", "ENG-1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["key"] == "ENG-1"


def test_tickets_get_should_preserve_description_in_selected_properties(monkeypatch):
    fake_client = SimpleNamespace(
        get_ticket=lambda issue_id: {**SAMPLE_ISSUE, "requested": issue_id},
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(
        app,
        ["tickets", "get", "ENG-1", "--properties", "key,summary,description,self", "--profile", "default"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "key": "ENG-1",
            "summary": "Broken workflow",
            "description": "First line\nSecond line",
            "self": "https://acme.atlassian.net/rest/api/3/issue/10001",
        }
    ]


def test_projects_list_should_emit_json_by_default(monkeypatch):
    calls = []
    fake_client = SimpleNamespace(
        list_projects=lambda **kwargs: calls.append(kwargs) or [SAMPLE_PROJECT],
    )
    monkeypatch.setattr("jira_cli.commands.projects.get_client", lambda: fake_client)

    result = runner.invoke(app, ["projects", "list", "--profile", "default"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["key"] == "ENG"
    assert calls == [{"limit": 100, "query": None}]


def test_projects_list_should_pass_query_limit_and_render_table(monkeypatch):
    calls = []
    fake_client = SimpleNamespace(
        list_projects=lambda **kwargs: calls.append(kwargs) or [SAMPLE_PROJECT],
    )
    monkeypatch.setattr("jira_cli.commands.projects.get_client", lambda: fake_client)

    result = runner.invoke(
        app,
        [
            "projects",
            "list",
            "--query",
            "Eng",
            "--limit",
            "25",
            "--table",
            "--profile",
            "default",
        ],
    )

    assert result.exit_code == 0
    assert "ENG" in result.stdout
    assert "Engineering" in result.stdout
    assert calls == [{"limit": 25, "query": "Eng"}]


def test_projects_get_table_should_render_field_value_rows(monkeypatch):
    fake_client = SimpleNamespace(
        get_project=lambda project_id: {**SAMPLE_PROJECT, "requested": project_id},
    )
    monkeypatch.setattr("jira_cli.commands.projects.get_client", lambda: fake_client)

    result = runner.invoke(app, ["projects", "get", "ENG", "--table", "--profile", "default"])

    assert result.exit_code == 0
    assert "requested" in result.stdout
    assert "ENG" in result.stdout


def test_projects_get_should_emit_json_object_by_default(monkeypatch):
    fake_client = SimpleNamespace(
        get_project=lambda project_id: {**SAMPLE_PROJECT, "requested": project_id},
    )
    monkeypatch.setattr("jira_cli.commands.projects.get_client", lambda: fake_client)

    result = runner.invoke(app, ["projects", "get", "ENG"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["key"] == "ENG"


def test_tickets_create_should_pass_required_fields(monkeypatch):
    calls = []
    fake_client = SimpleNamespace(
        create_ticket=lambda **kwargs: calls.append(kwargs) or SAMPLE_ISSUE,
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(
        app,
        [
            "tickets",
            "create",
            "--project",
            "ENG",
            "--summary",
            "Broken workflow",
            "--issue-type",
            "Bug",
            "--profile",
            "default",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["project"] == "ENG"
    assert calls[0]["summary"] == "Broken workflow"
    assert calls[0]["issue_type"] == "Bug"


def test_tickets_delete_should_pass_issue_key(monkeypatch):
    calls = []
    fake_client = SimpleNamespace(
        delete_ticket=lambda issue_id, delete_subtasks=False: calls.append(
            {"issue_id": issue_id, "delete_subtasks": delete_subtasks}
        )
        or {"key": issue_id, "deleted": True},
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(app, ["tickets", "delete", "ENG-1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"key": "ENG-1", "deleted": True}
    assert calls == [{"issue_id": "ENG-1", "delete_subtasks": False}]


def test_tickets_delete_should_pass_delete_subtasks(monkeypatch):
    calls = []
    fake_client = SimpleNamespace(
        delete_ticket=lambda issue_id, delete_subtasks=False: calls.append(
            {"issue_id": issue_id, "delete_subtasks": delete_subtasks}
        )
        or {"key": issue_id, "deleted": True},
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(app, ["tickets", "delete", "ENG-1", "--delete-subtasks"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"key": "ENG-1", "deleted": True}
    assert calls == [{"issue_id": "ENG-1", "delete_subtasks": True}]


def test_tickets_transition_should_pass_transition_id(monkeypatch):
    calls = []
    fake_client = SimpleNamespace(
        transition_ticket=lambda issue_id, transition_id, comment=None: calls.append(
            {"issue_id": issue_id, "transition_id": transition_id, "comment": comment}
        )
        or SAMPLE_ISSUE,
    )
    monkeypatch.setattr("jira_cli.commands.tickets.get_client", lambda: fake_client)

    result = runner.invoke(
        app,
        [
            "tickets",
            "transition",
            "ENG-1",
            "--transition-id",
            "31",
            "--comment",
            "Resolved",
            "--profile",
            "default",
        ],
    )

    assert result.exit_code == 0
    assert calls == [{"issue_id": "ENG-1", "transition_id": "31", "comment": "Resolved"}]
