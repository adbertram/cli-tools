"""Regression tests for AppleScript completion read-back timing."""
import sqlite3

import things_cli.client as client_mod
from things_cli.client import AppleScriptTimeoutError, ClientError, ThingsClient
from things_cli.models import Project, StartType, Task, TaskStatus


def _make_project(status: TaskStatus, **overrides) -> Project:
    data = {"uuid": "project-uuid", "title": "Project", "status": status}
    data.update(overrides)
    return Project(**data)


def _make_todo(status: TaskStatus, **overrides) -> Task:
    data = {"uuid": "todo-uuid", "title": "Todo", "status": status}
    data.update(overrides)
    return Task(**data)


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


def test_complete_todo_timeout_returns_success_when_readback_completed(monkeypatch):
    """If osascript times out after committing completion, return the durable state."""
    client = ThingsClient.__new__(ThingsClient)

    monkeypatch.setattr(client, "_resolve_todo_completion_uuid", lambda uuid: uuid)
    monkeypatch.setattr(
        client,
        "_run_applescript",
        lambda script: (_ for _ in ()).throw(AppleScriptTimeoutError("timeout")),
    )
    monkeypatch.setattr(client, "get_todo", lambda uuid: _make_todo(TaskStatus.COMPLETED))

    todo = client.complete_todo("todo-uuid")

    assert todo.status == TaskStatus.COMPLETED


def test_uncomplete_todo_timeout_reports_readback_status(monkeypatch):
    """If uncomplete times out without committing, report the durable status."""
    client = ThingsClient.__new__(ThingsClient)

    monkeypatch.setattr(
        client,
        "_run_applescript",
        lambda script: (_ for _ in ()).throw(AppleScriptTimeoutError("timeout")),
    )
    monkeypatch.setattr(client, "get_todo", lambda uuid: _make_todo(TaskStatus.COMPLETED))

    try:
        client.uncomplete_todo("todo-uuid")
    except ClientError as exc:
        assert "Read-back after the timeout shows todo todo-uuid is still status 3" in str(exc)
    else:
        raise AssertionError("Expected uncomplete_todo to raise ClientError")


def test_update_todo_timeout_reports_partial_status_change(monkeypatch):
    """Update timeouts must include before/after state instead of a generic timeout."""
    client = ThingsClient.__new__(ThingsClient)
    states = iter([
        _make_todo(TaskStatus.INCOMPLETE, title="Old title"),
        _make_todo(TaskStatus.COMPLETED, title="Old title"),
    ])

    monkeypatch.setattr(client, "get_todo", lambda uuid: next(states))
    monkeypatch.setattr(
        client,
        "_run_applescript",
        lambda script: (_ for _ in ()).throw(AppleScriptTimeoutError("timeout")),
    )

    try:
        client.update_todo("todo-uuid", title="New title")
    except ClientError as exc:
        message = str(exc)
        assert "Read-back after the timeout shows partial durable changes" in message
        assert "status: <TaskStatus.INCOMPLETE: 0> -> <TaskStatus.COMPLETED: 3>" in message
        assert "Unexpected status change detected" in message
    else:
        raise AssertionError("Expected update_todo to raise ClientError")


def test_create_project_timeout_returns_unique_durable_match(monkeypatch):
    """Project create timeouts must not force duplicate-prone blind retries."""
    client = ThingsClient.__new__(ThingsClient)
    recovered = _make_project(
        TaskStatus.INCOMPLETE,
        uuid="created-project-uuid",
        title="Created project",
        notes="notes",
        area_uuid="area-uuid",
    )

    monkeypatch.setattr(
        client,
        "_run_applescript",
        lambda script: (_ for _ in ()).throw(AppleScriptTimeoutError("timeout")),
    )
    monkeypatch.setattr(
        client,
        "list_projects",
        lambda area=None, status=None, limit=None: [recovered],
    )

    project = client.create_project("Created project", notes="notes", area="area-uuid")

    assert project.uuid == "created-project-uuid"


def test_create_project_timeout_reports_ambiguous_readback(monkeypatch):
    """Multiple read-back matches are unsafe; report them instead of retrying."""
    client = ThingsClient.__new__(ThingsClient)
    matches = [
        _make_project(TaskStatus.INCOMPLETE, uuid="project-1", title="Created project", notes="notes"),
        _make_project(TaskStatus.INCOMPLETE, uuid="project-2", title="Created project", notes="notes"),
    ]

    monkeypatch.setattr(
        client,
        "_run_applescript",
        lambda script: (_ for _ in ()).throw(AppleScriptTimeoutError("timeout")),
    )
    monkeypatch.setattr(
        client,
        "list_projects",
        lambda area=None, status=None, limit=None: matches,
    )

    try:
        client.create_project("Created project", notes="notes")
    except ClientError as exc:
        message = str(exc)
        assert "multiple matching projects" in message
        assert "do not blindly retry create" in message
    else:
        raise AssertionError("Expected create_project to raise ClientError")


def test_create_project_someday_timeout_reports_partial_create(monkeypatch):
    """If create commits but Someday move is unverified, surface the existing UUID."""
    client = ThingsClient.__new__(ThingsClient)
    recovered = _make_project(
        TaskStatus.INCOMPLETE,
        uuid="created-project-uuid",
        title="Created project",
        notes="notes",
        start=StartType.ANYTIME,
    )

    monkeypatch.setattr(
        client,
        "_run_applescript",
        lambda script: (_ for _ in ()).throw(AppleScriptTimeoutError("timeout")),
    )
    monkeypatch.setattr(
        client,
        "list_projects",
        lambda area=None, status=None, limit=None: [recovered],
    )

    try:
        client.create_project("Created project", notes="notes", when="someday")
    except ClientError as exc:
        message = str(exc)
        assert "created-project-uuid" in message
        assert "not moved to Someday" in message
        assert "Do not retry create" in message
    else:
        raise AssertionError("Expected create_project to raise ClientError")


def test_database_glob_timeout_reports_full_disk_access_python(monkeypatch):
    """Protected Things container discovery must fail fast with the CLI Python path."""
    client = ThingsClient.__new__(ThingsClient)

    class FakeQueue:
        def empty(self):
            return True

    class FakeProcess:
        def start(self):
            pass

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return True

        def terminate(self):
            pass

    class FakeContext:
        def Queue(self):
            return FakeQueue()

        def Process(self, target, args):
            return FakeProcess()

    monkeypatch.setattr(client_mod.mp, "get_context", lambda name: FakeContext())
    monkeypatch.setattr(client_mod.sys, "executable", "/tmp/things-cli-python")

    try:
        client._glob_database_with_timeout("/protected/ThingsData-*", timeout=0.01)
    except ClientError as exc:
        message = str(exc)
        assert "Timed out while accessing the Things database container" in message
        assert "Full Disk Access" in message
        assert "/tmp/things-cli-python" in message
    else:
        raise AssertionError("Expected _glob_database_with_timeout to raise ClientError")


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
