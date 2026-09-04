import json

from typer.testing import CliRunner

import cli_tools_shared.command_registry as command_registry
from coursecraft_cli.client import ClientError, CourseCraftClient
from coursecraft_cli.commands import fields
from coursecraft_cli.main import app


runner = CliRunner()


def test_client_rename_field_uses_field_id_and_verifies_readback(monkeypatch):
    client = CourseCraftClient.__new__(CourseCraftClient)
    client.base_id = "appCourseCraft"
    calls = []

    def run(args):
        calls.append(args)
        if args[:2] == ["fields", "list"]:
            return [
                {"id": "fldApproval", "name": "Tested and Approved", "type": "checkbox"},
                {"id": "fldName", "name": "Name", "type": "singleLineText"},
            ]
        if args[:2] == ["fields", "update"]:
            return {"id": "fldApproval", "name": "Walkthrough Test Complete", "type": "checkbox"}
        if args[:2] == ["fields", "get"]:
            return {"id": "fldApproval", "name": "Walkthrough Test Complete", "type": "checkbox"}
        raise AssertionError(args)

    monkeypatch.setattr(client, "_run_airtable_command", run)

    result = client.rename_field("Demos", "Tested and Approved", "Walkthrough Test Complete")

    assert result["name"] == "Walkthrough Test Complete"
    assert calls == [
        ["fields", "list", "Demos", "--base", "appCourseCraft"],
        [
            "fields",
            "update",
            "Demos",
            "fldApproval",
            "--base",
            "appCourseCraft",
            "--name",
            "Walkthrough Test Complete",
        ],
        ["fields", "get", "Demos", "fldApproval", "--base", "appCourseCraft"],
    ]


def test_client_rename_field_rejects_existing_destination(monkeypatch):
    client = CourseCraftClient.__new__(CourseCraftClient)
    client.base_id = "appCourseCraft"
    monkeypatch.setattr(
        client,
        "_run_airtable_command",
        lambda args: [
            {"id": "fldOld", "name": "Tested and Approved", "type": "checkbox"},
            {"id": "fldNew", "name": "Walkthrough Test Complete", "type": "checkbox"},
        ],
    )

    try:
        client.rename_field("Demos", "Tested and Approved", "Walkthrough Test Complete")
    except ClientError as exc:
        assert str(exc) == "Field 'Walkthrough Test Complete' already exists in Demos."
    else:
        raise AssertionError("Expected duplicate destination to fail")


def test_fields_rename_command(monkeypatch):
    class FakeClient:
        def rename_field(self, table, current_name, new_name):
            assert (table, current_name, new_name) == (
                "Demos",
                "Tested and Approved",
                "Walkthrough Test Complete",
            )
            return {"id": "fldApproval", "name": "Walkthrough Test Complete", "type": "checkbox"}

    monkeypatch.setattr(fields, "get_client", lambda: FakeClient())
    monkeypatch.setattr(command_registry, "_check_credentials", lambda *_: None)
    result = runner.invoke(
        app,
        ["fields", "rename", "Demos", "Tested and Approved", "Walkthrough Test Complete"],
    )

    assert result.exit_code == 0
    assert '"name": "Walkthrough Test Complete"' in result.stdout


_SCHEMA_ROWS = [
    {"id": "fldName", "name": "Name", "type": "singleLineText"},
    {"id": "fldCount", "name": "Clip Count", "type": "count"},
    {"id": "fldStatus", "name": "Status", "type": "formula"},
    {"id": "fldTotal", "name": "Total Minutes", "type": "rollup"},
]


def test_client_list_fields_issues_schema_read_and_projects_rows(monkeypatch):
    client = CourseCraftClient.__new__(CourseCraftClient)
    client.base_id = "appCourseCraft"
    calls = []

    def run(args):
        calls.append(args)
        return [
            {"id": "fldName", "name": "Name", "type": "singleLineText", "options": {"x": 1}},
            {"id": "fldTotal", "name": "Total Minutes", "type": "rollup", "description": "d"},
        ]

    monkeypatch.setattr(client, "_run_airtable_command", run)

    result = client.list_fields("Demos")

    assert calls == [["fields", "list", "Demos", "--base", "appCourseCraft"]]
    assert result == [
        {"id": "fldName", "name": "Name", "type": "singleLineText"},
        {"id": "fldTotal", "name": "Total Minutes", "type": "rollup"},
    ]


def test_client_list_fields_rejects_non_list_response(monkeypatch):
    client = CourseCraftClient.__new__(CourseCraftClient)
    client.base_id = "appCourseCraft"
    monkeypatch.setattr(client, "_run_airtable_command", lambda args: {"error": "nope"})

    try:
        client.list_fields("Demos")
    except ClientError as exc:
        assert str(exc).startswith("Unexpected field-list response for table Demos")
    else:
        raise AssertionError("Expected a non-list schema response to fail")


def test_client_list_fields_rejects_row_without_type(monkeypatch):
    client = CourseCraftClient.__new__(CourseCraftClient)
    client.base_id = "appCourseCraft"
    monkeypatch.setattr(
        client,
        "_run_airtable_command",
        lambda args: [{"id": "fldName", "name": "Name"}],
    )

    try:
        client.list_fields("Demos")
    except ClientError as exc:
        assert "missing string type" in str(exc)
    else:
        raise AssertionError("Expected a schema row without type to fail")


def _install_fake_list_client(monkeypatch, rows_or_error):
    class FakeClient:
        def list_fields(self, table):
            assert table == "Demos"
            if isinstance(rows_or_error, Exception):
                raise rows_or_error
            return rows_or_error

    monkeypatch.setattr(fields, "get_client", lambda: FakeClient())
    monkeypatch.setattr(command_registry, "_check_credentials", lambda *_: None)


def test_fields_schema_command_prints_every_field(monkeypatch):
    _install_fake_list_client(monkeypatch, _SCHEMA_ROWS)

    result = runner.invoke(app, ["fields", "schema", "--table", "Demos"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == _SCHEMA_ROWS


def test_fields_schema_command_filters_by_type(monkeypatch):
    _install_fake_list_client(monkeypatch, _SCHEMA_ROWS)

    result = runner.invoke(
        app, ["fields", "schema", "--table", "Demos", "--type", "rollup, formula"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {"id": "fldStatus", "name": "Status", "type": "formula"},
        {"id": "fldTotal", "name": "Total Minutes", "type": "rollup"},
    ]


def test_fields_schema_command_exits_1_on_schema_read_error(monkeypatch):
    _install_fake_list_client(monkeypatch, ClientError("airtable CLI error: boom"))

    result = runner.invoke(app, ["fields", "schema", "--table", "Demos"])

    assert result.exit_code == 1
    assert result.stdout.strip() == ""


def test_fields_schema_command_rejects_empty_type_item(monkeypatch):
    _install_fake_list_client(monkeypatch, _SCHEMA_ROWS)

    result = runner.invoke(
        app, ["fields", "schema", "--table", "Demos", "--type", "rollup,,formula"]
    )

    assert result.exit_code == 2
    assert "--type" in result.output
