"""Regression tests for AppleScript completion read-back timing."""
import sqlite3

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

    monkeypatch.setattr(client, "_resolve_todo_completion_uuid", lambda uuid: uuid)
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


def _client_with_db(tmp_path):
    db_path = tmp_path / "things.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE TMTask (
                uuid TEXT PRIMARY KEY,
                type INTEGER,
                status INTEGER,
                start INTEGER,
                startDate INTEGER,
                deadline INTEGER,
                trashed INTEGER,
                title TEXT,
                notes TEXT,
                area TEXT,
                project TEXT,
                heading TEXT,
                creationDate REAL,
                userModificationDate REAL,
                todayIndex INTEGER,
                `index` INTEGER,
                rt1_repeatingTemplate TEXT,
                rt1_recurrenceRule BLOB
            )
            """
        )
        conn.execute("CREATE TABLE TMArea (uuid TEXT PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE TMTag (uuid TEXT PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE TMTaskTag (tasks TEXT, tags TEXT)")
        conn.execute(
            "CREATE TABLE TMChecklistItem (uuid TEXT, title TEXT, status INTEGER, `index` INTEGER, task TEXT)"
        )

    client = ThingsClient.__new__(ThingsClient)
    client.db_path = db_path
    return client


def _insert_todo(conn, **overrides):
    data = {
        "uuid": "todo-uuid",
        "type": 0,
        "status": 0,
        "start": 1,
        "startDate": None,
        "deadline": None,
        "trashed": 0,
        "title": "Todo",
        "notes": None,
        "area": None,
        "project": None,
        "heading": None,
        "creationDate": None,
        "userModificationDate": None,
        "todayIndex": 0,
        "index": 0,
        "rt1_repeatingTemplate": None,
        "rt1_recurrenceRule": None,
    }
    data.update(overrides)
    conn.execute(
        """
        INSERT INTO TMTask (
            uuid, type, status, start, startDate, deadline, trashed, title,
            notes, area, project, heading, creationDate, userModificationDate,
            todayIndex, `index`, rt1_repeatingTemplate, rt1_recurrenceRule
        )
        VALUES (
            :uuid, :type, :status, :start, :startDate, :deadline, :trashed, :title,
            :notes, :area, :project, :heading, :creationDate, :userModificationDate,
            :todayIndex, :index, :rt1_repeatingTemplate, :rt1_recurrenceRule
        )
        """,
        data,
    )


def test_list_todos_today_uses_things_packed_dates(tmp_path):
    """Today filtering must include due and overdue Things packed dates."""
    client = _client_with_db(tmp_path)
    today_int = client._today_date_int()
    with sqlite3.connect(client.db_path) as conn:
        _insert_todo(conn, uuid="today-uuid", title="Today", startDate=today_int, index=1)
        _insert_todo(conn, uuid="overdue-uuid", title="Overdue", startDate=today_int - 128, index=2)
        _insert_todo(conn, uuid="future-uuid", title="Future", startDate=today_int + 128, index=3)
        _insert_todo(conn, uuid="inbox-uuid", title="Inbox", start=0, startDate=None, index=4)

    todos = client.list_todos(when="today", status="incomplete")

    assert [todo.uuid for todo in todos] == ["today-uuid", "overdue-uuid"]
    assert todos[0].start_date == client._date_int_to_iso(today_int)


def test_completion_resolves_recurring_backing_task_to_open_instance(tmp_path):
    """Completing a repeating backing row must target the active generated instance."""
    client = _client_with_db(tmp_path)
    today_int = client._today_date_int()
    with sqlite3.connect(client.db_path) as conn:
        _insert_todo(
            conn,
            uuid="template-uuid",
            title="Repeating task",
            start=2,
            rt1_recurrenceRule=b"rule",
        )
        _insert_todo(
            conn,
            uuid="instance-uuid",
            title="Repeating task",
            startDate=today_int,
            rt1_repeatingTemplate="template-uuid",
        )

    assert client._resolve_todo_completion_uuid("template-uuid") == "instance-uuid"
