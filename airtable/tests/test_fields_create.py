"""Tests for fields create preflight guards."""

import pytest
import requests
from typer.testing import CliRunner

from airtable_cli.client import AirtableClient, LOOKUP_CREATE_TYPE_MESSAGE
from airtable_cli.commands import fields
from cli_tools_shared.exceptions import ClientError


runner = CliRunner()


def _client() -> AirtableClient:
    client = AirtableClient.__new__(AirtableClient)
    client.base_url = "https://api.airtable.test/v0"
    client.headers = {"Authorization": "Bearer test"}
    return client


def _no_api(**kwargs):
    raise AssertionError("create_field must not call the API for multipleLookupValues")


def test_create_field_rejects_lookup_read_type_without_api_call(monkeypatch):
    monkeypatch.setattr(requests, "request", _no_api)

    with pytest.raises(ClientError) as excinfo:
        _client().create_field(
            base_id="appBase",
            table_id="tblSlides",
            name="Clip Slide Narration Complete",
            field_type="multipleLookupValues",
            options={
                "recordLinkFieldId": "fldLink",
                "fieldIdInLinkedTable": "fldSource",
            },
        )

    message = str(excinfo.value)
    assert "UNSUPPORTED_FIELD_TYPE_FOR_CREATE" in message
    assert "multipleLookupValues" in message
    assert "rollup" in message


def test_fields_create_command_rejects_lookup_read_type_on_stderr(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)
    monkeypatch.setattr(requests, "request", _no_api)

    result = runner.invoke(
        fields.app,
        [
            "create",
            "tblSlides",
            "Clip Slide Narration Complete",
            "multipleLookupValues",
            "--options",
            '{"recordLinkFieldId":"fldLink","fieldIdInLinkedTable":"fldSource"}',
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "UNSUPPORTED_FIELD_TYPE_FOR_CREATE" in result.stderr
    assert "multipleLookupValues" in result.stderr


def test_lookup_create_type_message_is_actionable():
    assert "fields list" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "Airtable's web UI" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "recordLinkFieldId" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "fieldIdInLinkedTable" in LOOKUP_CREATE_TYPE_MESSAGE
    assert "formula" in LOOKUP_CREATE_TYPE_MESSAGE
