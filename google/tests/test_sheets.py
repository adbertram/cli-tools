import json

from typer.testing import CliRunner

from google_cli.commands import sheets as sheets_commands
from google_cli.main import app


class FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeValuesResource:
    def __init__(self, payload):
        self.payload = payload
        self.get_calls = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return FakeExecute(self.payload)


class FakeSpreadsheetsResource:
    def __init__(self, values_resource):
        self.values_resource = values_resource

    def values(self):
        return self.values_resource


class FakeSheetsService:
    def __init__(self, values_resource):
        self.values_resource = values_resource

    def spreadsheets(self):
        return FakeSpreadsheetsResource(self.values_resource)


class FakeClient:
    def __init__(self, service):
        self.service = service

    def get_sheets_service(self):
        return self.service


def _patch_sheets_client(monkeypatch):
    values_resource = FakeValuesResource(
        {"values": [["Header 1", "Header 2"], ["Value 1", "Value 2"]]}
    )
    service = FakeSheetsService(values_resource)
    monkeypatch.setattr(
        sheets_commands, "get_client", lambda profile=None: FakeClient(service)
    )
    return values_resource


def test_sheets_read_defaults_to_unqualified_a1_range(monkeypatch):
    values_resource = _patch_sheets_client(monkeypatch)

    result = CliRunner().invoke(app, ["sheets", "read", "spreadsheet-id"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [["Header 1", "Header 2"], ["Value 1", "Value 2"]]
    assert values_resource.get_calls == [
        {"spreadsheetId": "spreadsheet-id", "range": "A:Z"}
    ]


def test_sheets_read_keeps_explicit_range(monkeypatch):
    values_resource = _patch_sheets_client(monkeypatch)

    result = CliRunner().invoke(
        app, ["sheets", "read", "spreadsheet-id", "--range", "A1:D10"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [["Header 1", "Header 2"], ["Value 1", "Value 2"]]
    assert values_resource.get_calls == [
        {"spreadsheetId": "spreadsheet-id", "range": "A1:D10"}
    ]
