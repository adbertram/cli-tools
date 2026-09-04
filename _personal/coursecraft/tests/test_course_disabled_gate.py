import pytest
from typer.testing import CliRunner

from coursecraft_cli import client as client_module
from coursecraft_cli.client import ClientError, CourseCraftClient
from coursecraft_cli.commands import courses


runner = CliRunner()


def _client() -> CourseCraftClient:
    client = CourseCraftClient.__new__(CourseCraftClient)
    client.base_id = "appTEST"
    # __init__ is bypassed above, so every instance attribute the write path
    # relies on must be installed here. _field_metadata_cache backs
    # _field_storage_metadata, which create_record/update_record call on every
    # write; pre-warming it keeps these fixtures from having to answer a
    # `fields list` command they are not about.
    client._field_metadata_cache = {"Courses": _COURSES_FIELD_METADATA}
    return client


# The Courses fields these fixtures write, with their exact Airtable storage
# types. artifact_versions._canonicalize_storage_value branches on the type, so
# these are the real types, not placeholders. None of them is one of the five
# richText fields documented in client.py.
_COURSES_FIELD_METADATA = {
    "Name": {"name": "Name", "type": "singleLineText"},
    "Disabled": {"name": "Disabled", "type": "checkbox"},
    "Disabled Notes": {"name": "Disabled Notes", "type": "multilineText"},
}


class _ReachedTheWrite(Exception):
    """Raised by the stubbed Airtable call to prove execution got past the gate.

    These fixtures are about the GATE, not about a full write round trip. Letting
    the stubbed airtable command raise this sentinel proves the two things the
    gate now owes: it reported the disabled course, and it did not stop the
    mutation from proceeding to its write.
    """


def _stub_write(monkeypatch, client):
    def reached(*_args, **_kwargs):
        raise _ReachedTheWrite

    monkeypatch.setattr(client, "_run_airtable_command", reached)


def _assert_disabled_reminder(capsys, expected: str) -> None:
    """The disabled-course gate reports and continues; it no longer refuses.

    Commit 3792e077 ("convert workflow gates to non-blocking reminders") moved
    enforcement of a disabled course out of this CLI and into the owning
    artifact's requirements.md/checks.json and the reviewer. The gate must still
    DETECT the disabled course and say so on stderr -- that is what these tests
    guard. Only the consequence changed, from raising to reminding.
    """
    stderr = capsys.readouterr().err
    assert "⚠ REMINDER" in stderr
    assert "[course.disabled]" in stderr
    assert expected in stderr


def test_update_record_rejects_disabled_course(monkeypatch, capsys):
    client = _client()
    monkeypatch.setattr(
        client,
        "get_record",
        lambda table, record_id: {
            "id": record_id,
            "fields": {
                "Name": "Disabled Course",
                "Disabled": True,
                "Disabled Notes": "Course is archived.",
            },
        },
    )

    _stub_write(monkeypatch, client)

    with pytest.raises(_ReachedTheWrite):
        client.update_record("Courses", "recCourse", {"Name": "New Name"})
    _assert_disabled_reminder(capsys, "Course is disabled")


def test_update_record_allows_disable_write_before_course_is_disabled(monkeypatch):
    client = _client()
    calls = []

    get_calls = []

    def fake_get(table, record_id):
        get_calls.append((table, record_id))
        if len(get_calls) == 1:
            return {"id": record_id, "fields": {"Name": "Active Course"}}
        return {
            "id": record_id,
            "fields": {"Name": "Active Course", "Disabled": True, "Disabled Notes": "Moved to archive."},
        }

    def fake_run(args):
        calls.append(args)
        return {"id": "recCourse", "fields": {}}

    monkeypatch.setattr(client, "get_record", fake_get)
    monkeypatch.setattr(client, "_run_airtable_command", fake_run)

    result = client.update_record(
        "Courses",
        "recCourse",
        {"Disabled": True, "Disabled Notes": "Moved to archive."},
    )

    assert result["id"] == "recCourse"
    assert calls == [
        [
            "records",
            "update",
            "Courses",
            "recCourse",
            "--base",
            "appTEST",
            "--typecast",
            "Disabled=true",
            "Disabled Notes=Moved to archive.",
        ]
    ]


def test_child_update_rejects_when_parent_course_is_disabled(monkeypatch, capsys):
    client = _client()

    records = {
        ("Slides", "recSlide"): {"id": "recSlide", "fields": {"Clip Record ID": "recClip"}},
        ("Clips", "recClip"): {"id": "recClip", "fields": {"Module Record ID": "recModule"}},
        ("Modules", "recModule"): {"id": "recModule", "fields": {"Course Record ID": "recCourse"}},
        ("Courses", "recCourse"): {
            "id": "recCourse",
            "fields": {
                "Name": "Disabled Course",
                "Disabled": True,
                "Disabled Notes": "Paused by Adam.",
            },
        },
    }
    monkeypatch.setattr(client, "get_record", lambda table, record_id: records[(table, record_id)])

    _stub_write(monkeypatch, client)

    with pytest.raises(_ReachedTheWrite):
        client.update_record("Slides", "recSlide", {"Script": "New script"})
    _assert_disabled_reminder(capsys, "Paused by Adam")


def test_create_record_rejects_child_under_disabled_course(monkeypatch, capsys):
    client = _client()

    records = {
        ("Clips", "recClip"): {"id": "recClip", "fields": {"Module Record ID": "recModule"}},
        ("Modules", "recModule"): {"id": "recModule", "fields": {"Course Record ID": "recCourse"}},
        ("Courses", "recCourse"): {
            "id": "recCourse",
            "fields": {"Name": "Disabled Course", "Disabled": True},
        },
    }
    monkeypatch.setattr(client, "get_record", lambda table, record_id: records[(table, record_id)])

    _stub_write(monkeypatch, client)

    with pytest.raises(_ReachedTheWrite):
        client.create_record("Slides", {"Clip Record ID": "recClip", "Name": "Blocked Slide"})
    _assert_disabled_reminder(capsys, "Course is disabled")


def test_delete_record_rejects_disabled_course(monkeypatch, capsys):
    client = _client()
    monkeypatch.setattr(
        client,
        "get_record",
        lambda table, record_id: {"id": record_id, "fields": {"Name": "Disabled Course", "Disabled": True}},
    )

    # The shared Airtable runner owns the subprocess boundary, so the sentinel
    # goes on subprocess.run.
    def reached(*_args, **_kwargs):
        raise _ReachedTheWrite

    monkeypatch.setattr(client_module.subprocess, "run", reached)

    with pytest.raises(ClientError, match="Error deleting record"):
        client.delete_record("Courses", "recCourse")
    _assert_disabled_reminder(capsys, "Course is disabled")


class FakeCourseDisableClient:
    def __init__(self):
        self.updated_fields = None

    def resolve_course_id(self, course):
        assert course == "openai-codex-advanced-features"
        return "recCourse"

    def get_record(self, table_name, record_id):
        assert table_name == "Courses"
        assert record_id == "recCourse"
        return {
            "id": record_id,
            "fields": {
                "Name": "OpenAI Codex Advanced Features",
                "Course ID": "openai-codex-advanced-features",
            },
        }

    def update_record(self, table_name, record_id, fields):
        assert table_name == "Courses"
        assert record_id == "recCourse"
        self.updated_fields = fields


def test_courses_disable_requires_why(monkeypatch):
    fake_client = FakeCourseDisableClient()
    monkeypatch.setattr(courses, "get_client", lambda: fake_client)

    result = runner.invoke(courses.app, ["disable", "openai-codex-advanced-features"])

    assert result.exit_code == 2
    assert "Missing option" in result.output
    assert "--why" in result.output
    assert fake_client.updated_fields is None


def test_courses_disable_writes_disabled_fields(monkeypatch):
    fake_client = FakeCourseDisableClient()
    monkeypatch.setattr(courses, "get_client", lambda: fake_client)

    result = runner.invoke(
        courses.app,
        ["disable", "openai-codex-advanced-features", "--why", "Course is archived."],
    )

    assert result.exit_code == 0
    assert fake_client.updated_fields == {
        "Disabled": True,
        "Disabled Notes": "Course is archived.",
    }
    assert "recCourse" in result.output
