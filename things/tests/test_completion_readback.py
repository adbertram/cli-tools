"""Regression tests for AppleScript completion read-back timing."""
import things_cli.client as client_mod
from things_cli.client import ClientError, ThingsClient
from things_cli.models import Project, Task, TaskStatus


def _make_project(status: TaskStatus) -> Project:
    return Project(uuid="project-uuid", title="Project", status=status)


def _make_todo(status: TaskStatus) -> Task:
    return Task(uuid="todo-uuid", title="Todo", status=status)


def test_complete_project_waits_for_persisted_status(monkeypatch):
    """Project completion must wait until SQLite reflects the new status."""
    client = ThingsClient.__new__(ThingsClient)
    calls = []
    statuses = iter([TaskStatus.INCOMPLETE, TaskStatus.COMPLETED])

    monkeypatch.setattr(client, "_run_applescript", lambda script: None)
    monkeypatch.setattr(client_mod.time, "sleep", lambda _: None)

    def fake_get_project(uuid):
        calls.append(uuid)
        return _make_project(next(statuses))

    monkeypatch.setattr(client, "get_project", fake_get_project)

    project = client.complete_project("project-uuid")

    assert project.status == TaskStatus.COMPLETED
    assert calls == ["project-uuid", "project-uuid"]


def test_complete_todo_times_out_when_status_never_persists(monkeypatch):
    """Completion must fail clearly instead of returning a stale SQLite read."""
    client = ThingsClient.__new__(ThingsClient)
    monotonic_values = iter([0.0, 0.0, 1.0, 2.0, 6.0])

    monkeypatch.setattr(client, "_run_applescript", lambda script: None)
    monkeypatch.setattr(client, "get_todo", lambda uuid: _make_todo(TaskStatus.INCOMPLETE))
    monkeypatch.setattr(client_mod.time, "sleep", lambda _: None)
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: next(monotonic_values))

    try:
        client.complete_todo("todo-uuid")
    except ClientError as exc:
        assert "Timed out waiting for todo todo-uuid to become status 3." in str(exc)
    else:
        raise AssertionError("Expected complete_todo to raise ClientError")
