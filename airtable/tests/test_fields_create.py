"""Tests for fields create preflight guards."""

import json

import pytest
import requests
from typer.testing import CliRunner

from airtable_cli.client import (
    AirtableClient,
    LOOKUP_CREATE_TYPE_MESSAGE,
    UNSUPPORTED_FIELD_CREATE_TYPE_MESSAGES,
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


class _Response:
    status_code = 200
    ok = True
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.parametrize("field_type", sorted(UNSUPPORTED_FIELD_CREATE_TYPE_MESSAGES))
def test_create_field_rejects_lookup_types_without_api_call(monkeypatch, field_type):
    monkeypatch.setattr(requests, "request", _no_api)

    with pytest.raises(ClientError) as excinfo:
        _client().create_field(
            base_id="appBase",
            table_id="tblSlides",
            name="Clip Slide Narration Complete",
            field_type=field_type,
            options={
                "recordLinkFieldId": "fldLink",
                "fieldIdInLinkedTable": "fldSource",
            },
        )

    message = str(excinfo.value)
    assert "Creating lookup fields is not supported at this time" in message
    assert field_type in message
    assert "rollup" in message


@pytest.mark.parametrize("field_type", sorted(UNSUPPORTED_FIELD_CREATE_TYPE_MESSAGES))
def test_fields_create_command_rejects_lookup_types_on_stderr(monkeypatch, field_type):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)
    monkeypatch.setattr(requests, "request", _no_api)

    result = runner.invoke(
        fields.app,
        [
            "create",
            "tblSlides",
            "Clip Slide Narration Complete",
            field_type,
            "--options",
            '{"recordLinkFieldId":"fldLink","fieldIdInLinkedTable":"fldSource"}',
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Creating lookup fields is not supported at this time" in result.stderr
    assert field_type in result.stderr


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


def test_lookup_create_type_message_is_actionable():
    assert "fields list" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "Airtable's web UI" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "lookup" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "Creating lookup fields is not supported at this time" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "recordLinkFieldId" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "fieldIdInLinkedTable" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "formula" in LOOKUP_CREATE_TYPE_MESSAGE
