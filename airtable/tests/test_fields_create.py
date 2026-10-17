"""Tests for fields create preflight guards."""

import copy
import json
from pathlib import Path

import pytest
import requests
from typer.testing import CliRunner

from airtable_cli.client import (
    AirtableClient,
    CHECKBOX_DEFAULT_OPTIONS,
    FIELD_CREATE_PERMANENCE_NOTE,
    LOOKUP_CREATE_TYPE_MESSAGE,
    UNSUPPORTED_FIELD_CREATE_TYPE_MESSAGES,
    checkbox_create_options,
)
from airtable_cli.commands import fields
from cli_tools_shared.exceptions import ClientError


runner = CliRunner()


def _client() -> AirtableClient:
    client = AirtableClient.__new__(AirtableClient)
    client.base_url = "https://api.airtable.test/v0"
    client.headers = {"Authorization": "Bearer test"}
    return client


def _no_api(**kwargs):
    raise AssertionError("create_field must not call the API for unsupported lookup field types")


LOOKUP_OPTIONS = {
    "recordLinkFieldId": "fldLink",
    "fieldIdInLinkedTable": "fldSource",
}
ROLLUP_OPTIONS = dict(LOOKUP_OPTIONS, formula="COUNTA(values)")


class _Response:
    status_code = 200
    ok = True
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_guard_blocks_only_the_lookup_spelling():
    assert sorted(UNSUPPORTED_FIELD_CREATE_TYPE_MESSAGES) == ["lookup"]


def test_create_field_rejects_lookup_spelling_without_api_call(monkeypatch):
    monkeypatch.setattr(requests, "request", _no_api)

    with pytest.raises(ClientError) as excinfo:
        _client().create_field(
            base_id="appBase",
            table_id="tblSlides",
            name="Clip Slide Narration Complete",
            field_type="lookup",
            options=dict(LOOKUP_OPTIONS),
        )

    message = str(excinfo.value)
    assert "Creating lookup fields is not supported at this time" in message
    assert "multipleLookupValues" in message


def test_fields_create_command_rejects_lookup_spelling_on_stderr(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)
    monkeypatch.setattr(requests, "request", _no_api)

    result = runner.invoke(
        fields.app,
        [
            "create",
            "tblSlides",
            "Clip Slide Narration Complete",
            "lookup",
            "--options",
            json.dumps(LOOKUP_OPTIONS),
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Creating lookup fields is not supported at this time" in result.stderr
    assert "multipleLookupValues" in result.stderr


@pytest.mark.parametrize(
    "field_type,options",
    [
        ("multipleLookupValues", LOOKUP_OPTIONS),
        ("rollup", ROLLUP_OPTIONS),
    ],
)
def test_create_field_sends_lookup_and_rollup_to_the_api(monkeypatch, field_type, options):
    """multipleLookupValues and rollup must reach POST .../fields, not a guard."""
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "GET":
            return _Response({"tables": [{"id": "tblSlides", "name": "Slides"}]})
        if kwargs["method"] == "POST":
            assert kwargs["url"] == (
                "https://api.airtable.test/v0/meta/bases/appBase/tables/tblSlides/fields"
            )
            assert kwargs["json"] == {
                "name": "Module Status",
                "type": field_type,
                "options": options,
            }
            return _Response({
                "id": "fldCreated",
                "name": "Module Status",
                "type": field_type,
                "options": dict(options, isValid=True),
            })
        raise AssertionError(f"unexpected request method: {kwargs['method']}")

    monkeypatch.setattr(requests, "request", fake_request)

    result = _client().create_field(
        base_id="appBase",
        table_id="tblSlides",
        name="Module Status",
        field_type=field_type,
        options=dict(options),
    )

    assert [call["method"] for call in calls] == ["GET", "POST"]
    assert result["id"] == "fldCreated"
    assert result["options"]["isValid"] is True


@pytest.mark.parametrize(
    "field_type,options",
    [
        ("multipleLookupValues", LOOKUP_OPTIONS),
        ("rollup", ROLLUP_OPTIONS),
    ],
)
def test_fields_create_command_creates_lookup_and_rollup(monkeypatch, field_type, options):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)

    def fake_request(**kwargs):
        if kwargs["method"] == "GET":
            return _Response({"tables": [{"id": "tblSlides", "name": "Slides"}]})
        if kwargs["method"] == "POST":
            assert kwargs["json"]["type"] == field_type
            assert kwargs["json"]["options"] == options
            return _Response({
                "id": "fldCreated",
                "name": "Module Status",
                "type": field_type,
            })
        raise AssertionError(f"unexpected request method: {kwargs['method']}")

    monkeypatch.setattr(requests, "request", fake_request)

    result = runner.invoke(
        fields.app,
        [
            "create",
            "Slides",
            "Module Status",
            field_type,
            "--options",
            json.dumps(options),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["id"] == "fldCreated"
    assert "Field created with ID: fldCreated" in result.stderr


def test_fields_create_warns_that_a_created_field_cannot_be_deleted(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)

    def fake_request(**kwargs):
        if kwargs["method"] == "GET":
            return _Response({"tables": [{"id": "tblSlides", "name": "Slides"}]})
        return _Response({"id": "fldCreated", "name": "Module Status", "type": "singleLineText"})

    monkeypatch.setattr(requests, "request", fake_request)

    result = runner.invoke(fields.app, ["create", "Slides", "Module Status", "singleLineText"])

    assert result.exit_code == 0
    assert FIELD_CREATE_PERMANENCE_NOTE in result.stderr


def test_fields_create_command_resolves_table_name_before_api_create(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "GET":
            assert kwargs["url"] == "https://api.airtable.test/v0/meta/bases/appBase/tables"
            return _Response({"tables": [{"id": "tblCourses", "name": "Courses"}]})
        if kwargs["method"] == "POST":
            assert kwargs["url"] == "https://api.airtable.test/v0/meta/bases/appBase/tables/tblCourses/fields"
            assert kwargs["json"] == {"name": "Feedback Sheet ID", "type": "singleLineText"}
            return _Response({
                "id": "fldFeedbackSheetId",
                "name": "Feedback Sheet ID",
                "type": "singleLineText",
            })
        raise AssertionError(f"unexpected request method: {kwargs['method']}")

    monkeypatch.setattr(requests, "request", fake_request)

    result = runner.invoke(
        fields.app,
        ["create", "Courses", "Feedback Sheet ID", "singleLineText"],
    )

    assert result.exit_code == 0
    assert [call["method"] for call in calls] == ["GET", "POST"]
    assert json.loads(result.stdout) == {
        "id": "fldFeedbackSheetId",
        "name": "Feedback Sheet ID",
        "type": "singleLineText",
    }
    assert "Field created with ID: fldFeedbackSheetId" in result.stderr


def test_lookup_create_type_message_names_the_working_type():
    assert "Creating lookup fields is not supported at this time" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "multipleLookupValues" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "recordLinkFieldId" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "fieldIdInLinkedTable" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "web UI" not in LOOKUP_CREATE_TYPE_MESSAGE


def test_field_create_permanence_note_states_the_api_facts():
    assert "no delete-field API endpoint" in FIELD_CREATE_PERMANENCE_NOTE
    assert "name and description" in FIELD_CREATE_PERMANENCE_NOTE


CHECKBOX_DEFAULTS = {"icon": "check", "color": "greenBright"}


def test_checkbox_create_options_fills_airtable_defaults():
    """A checkbox create is completed with Airtable's own icon and color."""
    assert CHECKBOX_DEFAULT_OPTIONS == CHECKBOX_DEFAULTS
    assert checkbox_create_options(None) == CHECKBOX_DEFAULTS
    assert checkbox_create_options({}) == CHECKBOX_DEFAULTS
    assert checkbox_create_options({"icon": "star"}) == {"icon": "star", "color": "greenBright"}
    assert checkbox_create_options({"color": "red"}) == {"icon": "check", "color": "red"}
    assert checkbox_create_options({"icon": "star", "color": "red"}) == {"icon": "star", "color": "red"}


def test_checkbox_create_options_does_not_mutate_caller_payload():
    caller_options = {"icon": "star"}

    completed = checkbox_create_options(caller_options)

    assert caller_options == {"icon": "star"}
    assert CHECKBOX_DEFAULT_OPTIONS == CHECKBOX_DEFAULTS
    assert completed is not caller_options


@pytest.mark.parametrize(
    "options",
    [None, {}, {"icon": "star"}, {"color": "red"}],
)
def test_create_field_never_sends_an_incomplete_checkbox(monkeypatch, options):
    """Options absent, empty, or partial all reach the API with both keys."""
    posts = []

    def fake_request(**kwargs):
        if kwargs["method"] == "GET":
            return _Response({"tables": [{"id": "tblDemos", "name": "Demos"}]})
        posts.append(kwargs["json"])
        return _Response({"id": "fldDone", "name": "Done", "type": "checkbox"})

    monkeypatch.setattr(requests, "request", fake_request)

    _client().create_field(
        base_id="appBase",
        table_id="Demos",
        name="Done",
        field_type="checkbox",
        options=copy.deepcopy(options),
    )

    assert len(posts) == 1
    sent = posts[0]
    assert sent["type"] == "checkbox"
    assert set(sent["options"]) == {"icon", "color"}
    assert all(sent["options"][key] for key in ("icon", "color"))
    assert sent["options"] == {**CHECKBOX_DEFAULTS, **(options or {})}


@pytest.mark.parametrize("options", [None, {}, {"icon": "star"}])
def test_fields_create_command_creates_a_bare_checkbox(monkeypatch, options):
    """The report's failing invocation now creates the field."""
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)
    posts = []

    def fake_request(**kwargs):
        if kwargs["method"] == "GET":
            return _Response({"tables": [{"id": "tblDemos", "name": "Demos"}]})
        posts.append(kwargs["json"])
        return _Response({
            "id": "fldRecorded",
            "name": "Unpaced Action Video Recorded",
            "type": "checkbox",
        })

    monkeypatch.setattr(requests, "request", fake_request)

    description = "Marks that the first, unpaced action-video take has been recorded."
    argv = [
        "create",
        "Demos",
        "Unpaced Action Video Recorded",
        "checkbox",
        "--description",
        description,
    ]
    if options is not None:
        argv += ["--options", json.dumps(options)]

    result = runner.invoke(fields.app, argv)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["id"] == "fldRecorded"
    assert posts[0]["description"] == description
    assert posts[0]["options"] == {**CHECKBOX_DEFAULTS, **(options or {})}


@pytest.mark.parametrize("field_type", ["singleLineText", "multilineText"])
def test_non_checkbox_create_invents_no_options(monkeypatch, field_type):
    """Only checkbox creation fills defaults; other types forward nothing extra."""
    posts = []

    def fake_request(**kwargs):
        if kwargs["method"] == "GET":
            return _Response({"tables": [{"id": "tblDemos", "name": "Demos"}]})
        posts.append(kwargs["json"])
        return _Response({"id": "fldNotes", "name": "Notes", "type": field_type})

    monkeypatch.setattr(requests, "request", fake_request)

    _client().create_field(
        base_id="appBase",
        table_id="Demos",
        name="Notes",
        field_type=field_type,
    )

    assert posts == [{"name": "Notes", "type": field_type}]


def test_checkbox_guidance_documents_the_working_values():
    """README and the repo-owned skill both show the explicit checkbox options."""
    tool_root = Path(__file__).resolve().parents[1]
    readme = (tool_root / "README.md").read_text(encoding="utf-8")
    assert '"icon":"check","color":"greenBright"' in readme

    skill = tool_root.parent / "_repo" / "skills" / "airtable-cli" / "SKILL.md"
    if skill.is_file():
        assert '"icon":"check","color":"greenBright"' in skill.read_text(encoding="utf-8")
