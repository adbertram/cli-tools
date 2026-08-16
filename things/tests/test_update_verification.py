"""Regression tests for post-write verification of Things updates.

Things 3 accepts several writes that it then ignores, so a zero exit status is
not evidence that an update landed. These tests pin the verified behaviour:

- a Someday to-do can move to today, anytime, and an ISO date
- a requested field that does not persist fails loudly
- `--tags ""`, `--deadline ""`, `--area ""`, and `--when ""` clear their fields
- `when` on a repeating to-do is rejected before any write
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

import things_cli.client as client_mod
from things_cli.client import (
    ClientError,
    ThingsClient,
    UnpersistedUpdateError,
)
from things_cli.commands import projects as projects_cmd
from things_cli.commands import todos as todos_cmd
from things_cli.models import Project, StartType, Task, TaskStatus


TODAY = datetime.now().strftime("%Y-%m-%d")
TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _todo(**overrides) -> Task:
    data = {
        "uuid": "todo-uuid",
        "title": "Todo",
        "status": TaskStatus.INCOMPLETE,
        "start": StartType.SOMEDAY,
    }
    data.update(overrides)
    return Task(**data)


def _project(**overrides) -> Project:
    data = {
        "uuid": "project-uuid",
        "title": "Project",
        "status": TaskStatus.INCOMPLETE,
        "start": StartType.ANYTIME,
    }
    data.update(overrides)
    return Project(**data)


class _Recorder:
    """Capture the AppleScript and URL scheme calls an update makes."""

    def __init__(self):
        self.scripts = []
        self.url_calls = []

    def applescript(self, script, timeout=30):
        self.scripts.append(script)
        return ""

    def url_scheme(self, command, params):
        self.url_calls.append((command, params))

    @property
    def script_text(self) -> str:
        return "\n".join(self.scripts)


def _wire_todo_client(monkeypatch, states, repeating=False):
    """Build a ThingsClient whose reads return `states` in order."""
    client = ThingsClient.__new__(ThingsClient)
    recorder = _Recorder()
    queue = list(states)

    def fake_get_todo(uuid):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(client, "get_todo", fake_get_todo)
    monkeypatch.setattr(client, "_run_applescript", recorder.applescript)
    monkeypatch.setattr(client, "_run_url_scheme", recorder.url_scheme)
    monkeypatch.setattr(client, "_is_repeating", lambda uuid: repeating)
    return client, recorder


def _wire_project_client(monkeypatch, states):
    client = ThingsClient.__new__(ThingsClient)
    recorder = _Recorder()
    queue = list(states)

    def fake_get_project(uuid):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(client, "get_project", fake_get_project)
    monkeypatch.setattr(client, "_run_applescript", recorder.applescript)
    monkeypatch.setattr(client, "_run_url_scheme", recorder.url_scheme)
    monkeypatch.setattr(client, "_is_repeating", lambda uuid: False)
    return client, recorder


# ==================== Someday -> today / anytime / ISO date ====================


@pytest.mark.parametrize("start_date_before", [None, "2026-08-01"])
def test_someday_to_today_moves_to_today_list(monkeypatch, start_date_before):
    """A Someday to-do must reach Anytime + today's date, with or without a date."""
    before = _todo(start=StartType.SOMEDAY, start_date=start_date_before)
    after = _todo(start=StartType.ANYTIME, start_date=TODAY)
    client, recorder = _wire_todo_client(monkeypatch, [before, after])

    todo = client.update_todo("todo-uuid", when="today")

    assert todo.start == StartType.ANYTIME
    assert todo.start_date == TODAY
    assert 'move theToDo to list "Today"' in recorder.script_text
    assert recorder.url_calls == []


@pytest.mark.parametrize("start_date_before", [None, "2026-08-01"])
def test_someday_to_anytime_clears_date(monkeypatch, start_date_before):
    """Moving a Someday to-do to Anytime must leave start=1 with no date."""
    before = _todo(start=StartType.SOMEDAY, start_date=start_date_before)
    after = _todo(start=StartType.ANYTIME, start_date=None)
    client, recorder = _wire_todo_client(monkeypatch, [before, after])

    todo = client.update_todo("todo-uuid", when="anytime")

    assert todo.start == StartType.ANYTIME
    assert todo.start_date is None
    assert 'move theToDo to list "Anytime"' in recorder.script_text


@pytest.mark.parametrize("start_date_before", [None, "2026-08-01"])
def test_someday_to_iso_date_schedules(monkeypatch, start_date_before):
    """An ISO date must persist as the activation date.

    Things owns the bucket for a dated to-do: a future date stays start=2 and
    the row moves to Upcoming, so only start_date is asserted.
    """
    before = _todo(start=StartType.SOMEDAY, start_date=start_date_before)
    after = _todo(start=StartType.SOMEDAY, start_date="2026-09-02")
    client, recorder = _wire_todo_client(monkeypatch, [before, after])

    todo = client.update_todo("todo-uuid", when="2026-09-02")

    assert todo.start_date == "2026-09-02"
    assert 'schedule (to do id "todo-uuid") for date "September 2, 2026"' in recorder.script_text


def test_someday_to_iso_date_fails_when_date_never_persists(monkeypatch):
    """A silently ignored schedule must exit non-zero with the actual state."""
    before = _todo(start=StartType.SOMEDAY, start_date="2026-08-01")
    after = _todo(start=StartType.SOMEDAY, start_date="2026-08-01")
    client, _ = _wire_todo_client(monkeypatch, [before, after])

    with pytest.raises(UnpersistedUpdateError) as excinfo:
        client.update_todo("todo-uuid", when="2026-09-02")

    message = str(excinfo.value)
    assert "start_date: requested '2026-09-02', actual '2026-08-01'" in message
    assert "start=2" in message


def test_someday_to_today_fails_when_move_is_ignored(monkeypatch):
    """`--when today` must not report success while the to-do stays in Someday."""
    before = _todo(start=StartType.SOMEDAY)
    after = _todo(start=StartType.SOMEDAY)
    client, _ = _wire_todo_client(monkeypatch, [before, after])

    with pytest.raises(UnpersistedUpdateError) as excinfo:
        client.update_todo("todo-uuid", when="today")

    message = str(excinfo.value)
    assert "start: requested" in message
    assert f"start_date: requested '{TODAY}', actual None" in message


# ==================== Channel selection for `when` ====================


def test_tomorrow_uses_url_scheme(monkeypatch):
    """`move to list "Tomorrow"` is rejected by Things (301), so use the URL scheme."""
    client, recorder = _wire_todo_client(
        monkeypatch,
        [_todo(), _todo(start=StartType.SOMEDAY, start_date=TOMORROW)],
    )

    client.update_todo("todo-uuid", when="tomorrow")

    assert recorder.url_calls == [("update", {"id": "todo-uuid", "when": "tomorrow"})]
    assert "move theToDo" not in recorder.script_text


def test_evening_uses_url_scheme(monkeypatch):
    """`move to list "Evening"` is rejected by Things (-1728), so use the URL scheme."""
    client, recorder = _wire_todo_client(
        monkeypatch,
        [_todo(), _todo(start=StartType.ANYTIME, start_date=TODAY)],
    )

    client.update_todo("todo-uuid", when="evening")

    assert recorder.url_calls == [("update", {"id": "todo-uuid", "when": "evening"})]


def test_when_empty_uses_url_scheme_not_activation_date(monkeypatch):
    """`activation date` is read-only in Things, so the clear must use the URL scheme."""
    client, recorder = _wire_todo_client(
        monkeypatch,
        [_todo(start=StartType.SOMEDAY, start_date="2026-08-01"),
         _todo(start=StartType.ANYTIME, start_date=None)],
    )

    client.update_todo("todo-uuid", when="")

    assert recorder.url_calls == [("update", {"id": "todo-uuid", "when": ""})]
    assert "activation date" not in recorder.script_text


# ==================== Repeating to-dos ====================


def test_when_on_repeating_todo_is_rejected_before_any_write(monkeypatch):
    """Things cannot reschedule a repeating to-do through any supported channel."""
    client, recorder = _wire_todo_client(
        monkeypatch, [_todo(title="Repeating")], repeating=True
    )

    with pytest.raises(ClientError) as excinfo:
        client.update_todo("todo-uuid", when="today")

    message = str(excinfo.value)
    assert "repeating to-do" in message
    assert "Cannot move to-do (301)" in message
    assert recorder.scripts == []
    assert recorder.url_calls == []


def test_unpersisted_when_on_repeating_todo_names_the_limitation(monkeypatch):
    """A verification failure on a repeating to-do must explain why."""
    client, _ = _wire_todo_client(
        monkeypatch,
        [_todo(deadline="4001-01-01"), _todo(deadline="4001-01-01")],
        repeating=True,
    )

    with pytest.raises(UnpersistedUpdateError) as excinfo:
        client.update_todo("todo-uuid", deadline="")

    assert "repeating item" in str(excinfo.value)


# ==================== Clearing fields ====================


def test_empty_tags_clear_every_tag(monkeypatch):
    """`tags=[]` must write an empty tag-names string, not skip the write."""
    client, recorder = _wire_todo_client(
        monkeypatch, [_todo(tags=["WF"]), _todo(tags=[])]
    )

    todo = client.update_todo("todo-uuid", tags=[])

    assert todo.tags == []
    assert 'set tag names of theToDo to ""' in recorder.script_text


def test_multi_tag_todo_can_be_cleared(monkeypatch):
    client, recorder = _wire_todo_client(
        monkeypatch, [_todo(tags=["WF", "alpha", "beta"]), _todo(tags=[])]
    )

    assert client.update_todo("todo-uuid", tags=[]).tags == []
    assert 'set tag names of theToDo to ""' in recorder.script_text


def test_unpersisted_tags_clear_fails(monkeypatch):
    """Tags that survive the write must fail instead of printing success."""
    client, _ = _wire_todo_client(
        monkeypatch, [_todo(tags=["WF"]), _todo(tags=["WF"])]
    )

    with pytest.raises(UnpersistedUpdateError) as excinfo:
        client.update_todo("todo-uuid", tags=[])

    assert "tags: requested [], actual ['WF']" in str(excinfo.value)


def test_partially_applied_update_fails_and_names_the_field(monkeypatch):
    """A title that persists must not hide tags that did not."""
    client, _ = _wire_todo_client(
        monkeypatch,
        [_todo(title="Old", tags=["WF"]), _todo(title="New", tags=["WF"])],
    )

    with pytest.raises(UnpersistedUpdateError) as excinfo:
        client.update_todo("todo-uuid", title="New", tags=[])

    message = str(excinfo.value)
    assert "tags: requested [], actual ['WF']" in message
    assert "title" not in message.split("Unpersisted fields ->")[1].split(".")[0]


def test_empty_deadline_clears_through_url_scheme(monkeypatch):
    """`set due date to missing value` fails with -1700; use the URL scheme."""
    client, recorder = _wire_todo_client(
        monkeypatch, [_todo(deadline="2026-11-05"), _todo(deadline=None)]
    )

    todo = client.update_todo("todo-uuid", deadline="")

    assert todo.deadline is None
    assert recorder.url_calls == [("update", {"id": "todo-uuid", "deadline": ""})]
    assert "missing value" not in recorder.script_text


def test_empty_area_detaches_todo_through_url_scheme(monkeypatch):
    """`set area to missing value` fails with -1700; use the URL scheme."""
    client, recorder = _wire_todo_client(
        monkeypatch,
        [_todo(area_uuid="area-1"), _todo(area_uuid=None, project_uuid=None)],
    )

    todo = client.update_todo("todo-uuid", area="")

    assert todo.area_uuid is None
    assert recorder.url_calls == [("update", {"id": "todo-uuid", "list-id": ""})]


def test_empty_project_is_rejected_with_guidance(monkeypatch):
    client, recorder = _wire_todo_client(monkeypatch, [_todo(project_uuid="p1")])

    with pytest.raises(ClientError) as excinfo:
        client.update_todo("todo-uuid", project="")

    assert '--area ""' in str(excinfo.value)
    assert recorder.scripts == []


# ==================== Projects ====================


def test_project_empty_tags_clear_every_tag(monkeypatch):
    client, recorder = _wire_project_client(
        monkeypatch, [_project(tags=["WF"]), _project(tags=[])]
    )

    assert client.update_project("project-uuid", tags=[]).tags == []
    assert 'set tag names of theProject to ""' in recorder.script_text


def test_project_clears_deadline_and_area_through_url_scheme(monkeypatch):
    client, recorder = _wire_project_client(
        monkeypatch,
        [_project(deadline="2026-12-01", area_uuid="area-1"),
         _project(deadline=None, area_uuid=None)],
    )

    project = client.update_project("project-uuid", deadline="", area="")

    assert project.deadline is None
    assert project.area_uuid is None
    assert recorder.url_calls == [
        ("update-project", {"id": "project-uuid", "deadline": ""}),
        ("update-project", {"id": "project-uuid", "area-id": ""}),
    ]
    assert "missing value" not in recorder.script_text


def test_project_rejects_unsupported_when(monkeypatch):
    """`when` used to fall back to Anytime silently for any unknown value."""
    client, recorder = _wire_project_client(monkeypatch, [_project()])

    with pytest.raises(ClientError) as excinfo:
        client.update_project("project-uuid", when="today")

    assert "Use 'anytime' or 'someday'" in str(excinfo.value)
    assert recorder.scripts == []


def test_project_unpersisted_when_fails(monkeypatch):
    client, _ = _wire_project_client(
        monkeypatch,
        [_project(start=StartType.ANYTIME), _project(start=StartType.ANYTIME)],
    )

    with pytest.raises(UnpersistedUpdateError):
        client.update_project("project-uuid", when="someday")


# ==================== Command layer option parsing ====================


def _call_todos_update(monkeypatch, **kwargs):
    captured = {}

    class _FakeClient:
        def update_todo(self, **call):
            captured.update(call)
            return _todo(title="Todo")

    monkeypatch.setattr(todos_cmd, "get_client", lambda *a, **k: _FakeClient())
    options = {
        "uuid": "todo-uuid",
        "title": None,
        "notes": None,
        "when": None,
        "deadline": None,
        "tags": None,
        "project": None,
        "area": None,
    }
    options.update(kwargs)
    todos_cmd.todos_update(**options)
    return captured


def test_todos_update_empty_tags_option_requests_a_clear(monkeypatch):
    """`--tags ""` must reach the client as an empty list, not None."""
    assert _call_todos_update(monkeypatch, tags="")["tags"] == []


def test_todos_update_missing_tags_option_leaves_tags_alone(monkeypatch):
    assert _call_todos_update(monkeypatch, tags=None)["tags"] is None


def test_todos_update_tags_option_drops_blank_segments(monkeypatch):
    assert _call_todos_update(monkeypatch, tags="WF, ,alpha")["tags"] == ["WF", "alpha"]


def _call_projects_update(monkeypatch, **kwargs):
    captured = {}

    class _FakeClient:
        def update_project(self, **call):
            captured.update(call)
            return _project()

    monkeypatch.setattr(projects_cmd, "get_client", lambda *a, **k: _FakeClient())
    options = {
        "uuid": "project-uuid",
        "title": None,
        "notes": None,
        "area": None,
        "when": None,
        "deadline": None,
        "tags": None,
    }
    options.update(kwargs)
    projects_cmd.projects_update(**options)
    return captured


def test_projects_update_empty_tags_option_requests_a_clear(monkeypatch):
    assert _call_projects_update(monkeypatch, tags="")["tags"] == []


# ==================== Someday vs Upcoming reporting ====================


def test_start_label_reports_upcoming_for_a_dated_someday_row(monkeypatch):
    """Things stores a scheduled to-do as start=2 plus a date (Upcoming)."""
    assert todos_cmd.start_label(2, "2026-08-01") == "Upcoming"
    assert todos_cmd.start_label(2, None) == "Someday"
    assert todos_cmd.start_label(1, None) == "Anytime"
    assert todos_cmd.start_label(0, None) == "Inbox"


def test_format_for_table_labels_scheduled_todo_as_upcoming():
    rows = todos_cmd.format_for_table([_todo(start=StartType.SOMEDAY, start_date="2026-08-01")])
    assert rows[0]["start"] == "Upcoming"


_TMTASK_COLUMNS = (
    "uuid TEXT, title TEXT, type INTEGER, status INTEGER, start INTEGER, "
    "notes TEXT, startDate INTEGER, deadline INTEGER, trashed INTEGER, "
    "area TEXT, project TEXT, heading TEXT, creationDate REAL, "
    "userModificationDate REAL, todayIndex INTEGER, `index` INTEGER"
)


def _memory_things_db(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(f"CREATE TABLE TMTask ({_TMTASK_COLUMNS})")
    conn.execute("CREATE TABLE TMTag (uuid TEXT, title TEXT)")
    conn.execute("CREATE TABLE TMTaskTag (tasks TEXT, tags TEXT)")
    conn.execute("CREATE TABLE TMChecklistItem (uuid TEXT, title TEXT, status INTEGER, `index` INTEGER, task TEXT)")
    conn.execute("CREATE TABLE TMArea (uuid TEXT, title TEXT)")
    for row in rows:
        conn.execute(
            "INSERT INTO TMTask (uuid, title, type, status, start, startDate, trashed, todayIndex, `index`) "
            "VALUES (?, ?, 0, 0, ?, ?, 0, 0, 0)",
            (row["uuid"], row["title"], row["start"], row["startDate"]),
        )
    return conn


def test_someday_filter_excludes_scheduled_upcoming_todos(monkeypatch):
    """`--when someday` must not return a start=2 row that carries a date."""
    client = ThingsClient.__new__(ThingsClient)
    future = (2026 << 16) | (12 << 12) | (1 << 7)
    conn = _memory_things_db([
        {"uuid": "someday-1", "title": "Real Someday", "start": 2, "startDate": None},
        {"uuid": "upcoming-1", "title": "Scheduled", "start": 2, "startDate": future},
    ])
    monkeypatch.setattr(client, "_connect", lambda readonly=True: conn)

    someday = client.list_todos(when="someday")
    upcoming = client.list_todos(when="upcoming")

    assert [t.uuid for t in someday] == ["someday-1"]
    assert [t.uuid for t in upcoming] == ["upcoming-1"]
