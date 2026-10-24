import json

import pytest
from typer.testing import CliRunner

from airtable_cli.client import AirtableClient
from airtable_cli.commands import records
from cli_tools_shared.exceptions import ClientError


def test_update_many_chunks_ten_and_preserves_json_types(monkeypatch):
    client = AirtableClient.__new__(AirtableClient)
    calls = []
    def request(method, endpoint, data):
        calls.append((method, endpoint, data))
        return {"records": data["records"]}
    monkeypatch.setattr(client, "_make_request", request)
    monkeypatch.setattr(records, "get_client", lambda: client)
    monkeypatch.setattr(records, "resolve_base_id", lambda value: value)
    rows = [{"id": f"rec{n}", "fields": {"Clear": "", "Checkbox": False, "Number": 2, "Text": "true", "Null": None}}
            for n in range(16)]
    result = CliRunner().invoke(records.app, ["update-many", "Tasks", json.dumps(rows), "--base", "appTest", "--typecast"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == rows
    assert [len(call[2]["records"]) for call in calls] == [10, 6]
    assert all(call[0] == "PATCH" and call[2]["typecast"] is True for call in calls)


@pytest.mark.parametrize("rows", [[{"id": "recGood", "fields": {"Name": "good"}}, {"id": "../bad", "fields": {"Name": "bad"}}],
                                  [], [{"id": "recGood", "fields": {}}], [{"id": "recGood", "fields": "bad"}]])
def test_update_many_validates_entire_input_before_any_request(monkeypatch, rows):
    client = AirtableClient.__new__(AirtableClient)
    calls = []
    monkeypatch.setattr(client, "_make_request", lambda *args, **kwargs: calls.append(args))
    with pytest.raises((ClientError, ValueError)):
        client.update_records("appTest", "Tasks", rows)
    assert calls == []
