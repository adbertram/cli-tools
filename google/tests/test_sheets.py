import json

import pytest

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

    def update(self, **kwargs):
        self.update_calls = [*getattr(self, "update_calls", []), kwargs]
        return FakeExecute({"updatedRange": kwargs["range"], "updatedRows": 1, "updatedColumns": 2, "updatedCells": 2})

    def clear(self, **kwargs):
        self.clear_calls = [*getattr(self, "clear_calls", []), kwargs]
        return FakeExecute({"spreadsheetId": kwargs["spreadsheetId"], "clearedRange": kwargs["range"]})

    def batchClear(self, **kwargs):
        self.batch_clear_calls = [*getattr(self, "batch_clear_calls", []), kwargs]
        return FakeExecute({"spreadsheetId": kwargs["spreadsheetId"], "clearedRanges": kwargs["body"]["ranges"]})


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


def test_sheets_read_formulas_requests_formula_render_option(monkeypatch):
    values_resource = _patch_sheets_client(monkeypatch)

    result = CliRunner().invoke(
        app, ["sheets", "read", "spreadsheet-id", "--range", "Tab!A1:B2", "--formulas"]
    )

    assert result.exit_code == 0
    assert values_resource.get_calls == [
        {"spreadsheetId": "spreadsheet-id", "range": "Tab!A1:B2", "valueRenderOption": "FORMULA"}
    ]


def test_sheets_clear_single_range_uses_values_clear(monkeypatch):
    values_resource = _patch_sheets_client(monkeypatch)

    result = CliRunner().invoke(app, ["sheets", "clear", "spreadsheet-id", "--range", "Tab!A2:C"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"spreadsheetId": "spreadsheet-id", "clearedRange": "Tab!A2:C"}
    assert values_resource.clear_calls == [
        {"spreadsheetId": "spreadsheet-id", "range": "Tab!A2:C", "body": {}}
    ]
    assert not hasattr(values_resource, "batch_clear_calls")


def test_sheets_clear_repeated_range_uses_batch_clear(monkeypatch):
    values_resource = _patch_sheets_client(monkeypatch)
    url = "https://docs.google.com/spreadsheets/d/spreadsheet-id/edit#gid=0"

    result = CliRunner().invoke(
        app, ["sheets", "clear", url, "--range", "Tab!A2:C", "--range", "Other!B:B"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "spreadsheetId": "spreadsheet-id", "clearedRanges": ["Tab!A2:C", "Other!B:B"]
    }
    assert values_resource.batch_clear_calls == [
        {"spreadsheetId": "spreadsheet-id", "body": {"ranges": ["Tab!A2:C", "Other!B:B"]}}
    ]
    assert not hasattr(values_resource, "clear_calls")


def test_sheets_clear_requires_range(monkeypatch):
    _patch_sheets_client(monkeypatch)
    assert CliRunner().invoke(app, ["sheets", "clear", "spreadsheet-id"]).exit_code != 0


def test_sheets_update_values_json_keeps_commas_and_semicolons(monkeypatch):
    values_resource = _patch_sheets_client(monkeypatch)
    rows = [["Intro, part 1", "Setup; install"], ["=SUM(A1:A2)", 3]]

    result = CliRunner().invoke(
        app,
        ["sheets", "update", "spreadsheet-id", "--range", "Tab!A1:B2", "--values-json", json.dumps(rows)],
    )

    assert result.exit_code == 0, result.output
    assert values_resource.update_calls == [
        {"spreadsheetId": "spreadsheet-id", "range": "Tab!A1:B2", "valueInputOption": "USER_ENTERED", "body": {"values": rows}}
    ]


def test_sheets_update_values_still_splits_on_commas_and_semicolons(monkeypatch):
    values_resource = _patch_sheets_client(monkeypatch)

    result = CliRunner().invoke(
        app, ["sheets", "update", "spreadsheet-id", "--range", "A1:B2", "--values", "a, b;c,d", "--raw"]
    )

    assert result.exit_code == 0, result.output
    assert values_resource.update_calls[0]["body"] == {"values": [["a", "b"], ["c", "d"]]}
    assert values_resource.update_calls[0]["valueInputOption"] == "RAW"


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--values", "a", "--values-json", '[["a"]]'],
        ["--values-json", "not json"],
        ["--values-json", '{"a": 1}'],
        ["--values-json", '["a"]'],
    ],
)
def test_sheets_update_rejects_bad_value_options(monkeypatch, extra):
    values_resource = _patch_sheets_client(monkeypatch)

    result = CliRunner().invoke(app, ["sheets", "update", "spreadsheet-id", "--range", "A1", *extra])

    assert result.exit_code == 1
    assert not hasattr(values_resource, "update_calls")
