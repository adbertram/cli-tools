import json

from typer.testing import CliRunner

from google_cli.commands import cloud as cloud_commands
from google_cli.main import app


class FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeProjectsResource:
    def __init__(self, search_payload, get_payload):
        self.search_payload = search_payload
        self.get_payload = get_payload
        self.search_calls = []
        self.get_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return FakeExecute(self.search_payload)

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeExecute(self.get_payload)


class FakeCloudResourceManagerService:
    def __init__(self, projects_resource):
        self.projects_resource = projects_resource

    def projects(self):
        return self.projects_resource


class FakeClient:
    def __init__(self, service):
        self.service = service

    def get_cloud_resource_manager_service(self):
        return self.service


def test_cloud_projects_list_outputs_canonical_id(monkeypatch):
    projects_resource = FakeProjectsResource(
        {
            "projects": [
                {
                    "name": "projects/153584548092",
                    "projectId": "claude-code-481518",
                    "displayName": "Claude Code",
                    "state": "ACTIVE",
                }
            ]
        },
        {},
    )
    monkeypatch.setattr(
        cloud_commands,
        "get_client",
        lambda profile=None: FakeClient(FakeCloudResourceManagerService(projects_resource)),
    )

    result = CliRunner().invoke(app, ["cloud", "projects", "list", "--limit", "1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "name": "projects/153584548092",
            "projectId": "claude-code-481518",
            "displayName": "Claude Code",
            "state": "ACTIVE",
            "id": "claude-code-481518",
        }
    ]
    assert projects_resource.search_calls == [{}]


def test_cloud_projects_get_outputs_canonical_id(monkeypatch):
    projects_resource = FakeProjectsResource(
        {},
        {
            "name": "projects/153584548092",
            "projectId": "claude-code-481518",
            "displayName": "Claude Code",
            "state": "ACTIVE",
        },
    )
    monkeypatch.setattr(
        cloud_commands,
        "get_client",
        lambda profile=None: FakeClient(FakeCloudResourceManagerService(projects_resource)),
    )

    result = CliRunner().invoke(app, ["cloud", "projects", "get", "claude-code-481518"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "name": "projects/153584548092",
        "projectId": "claude-code-481518",
        "displayName": "Claude Code",
        "state": "ACTIVE",
        "id": "claude-code-481518",
    }
    assert projects_resource.get_calls == [{"name": "projects/claude-code-481518"}]
