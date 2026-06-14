"""Tests for the fields update select-choices guard.

Airtable's update-field endpoint rejects any select-field ``choices`` payload
with HTTP 422 (verified live against the real Meta API, including a no-op resend
of the current choices). The client must fail fast with an actionable message
and must not forward the doomed request.
"""

import pytest
import requests
from typer.testing import CliRunner

from airtable_cli.client import AirtableClient, SELECT_CHOICES_UPDATE_MESSAGE
from airtable_cli.commands import fields
from cli_tools_shared.exceptions import ClientError


runner = CliRunner()


def _client() -> AirtableClient:
    client = AirtableClient.__new__(AirtableClient)
    client.base_url = "https://api.airtable.test/v0"
    client.headers = {"Authorization": "Bearer test"}
    return client


class _Response:
    status_code = 200
    ok = True
    headers: dict = {}

    def json(self):
        return {"id": "fldVersion", "type": "formula"}


def _no_api(**kwargs):
    raise AssertionError("update_field must not call the API for a choices edit")


def test_update_field_rejects_select_choices_without_api_call(monkeypatch):
    monkeypatch.setattr(requests, "request", _no_api)

    with pytest.raises(ClientError) as excinfo:
        _client().update_field(
            base_id="appBase",
            table_id="tblSlides",
            field_id="fldVersion",
            options={"choices": [{"id": "selA", "name": "v1", "color": "blueLight2"}]},
        )

    message = str(excinfo.value)
    assert "cannot modify a select field's choices" in message
    assert "records update" in message
    assert "--typecast" in message


def test_update_field_allows_non_choices_options(monkeypatch):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(requests, "request", fake_request)

    result = _client().update_field(
        base_id="appBase",
        table_id="tblSlides",
        field_id="fldVersion",
        options={"formula": "{Hours} * {Rate}"},
    )

    assert result == {"id": "fldVersion", "type": "formula"}
    assert captured["method"] == "PATCH"
    assert captured["json"] == {"options": {"formula": "{Hours} * {Rate}"}}


def test_fields_update_command_rejects_choices_on_stderr(monkeypatch):
    monkeypatch.setattr(fields, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(fields, "get_client", _client)
    monkeypatch.setattr(requests, "request", _no_api)

    result = runner.invoke(
        fields.app,
        [
            "update",
            "tblSlides",
            "fldVersion",
            "--options",
            '{"choices":[{"id":"selA","name":"v1"}]}',
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "cannot modify a select field's choices" in result.stderr


def test_select_choices_message_is_actionable():
    # The message must name both workarounds so users are never left at a dead end.
    assert "records update" in SELECT_CHOICES_UPDATE_MESSAGE
    assert "--typecast" in SELECT_CHOICES_UPDATE_MESSAGE
    assert "web UI" in SELECT_CHOICES_UPDATE_MESSAGE
