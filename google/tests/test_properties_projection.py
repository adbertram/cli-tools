"""--properties must accept comma-separated and repeated values on every list command."""
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from google_cli.commands import calendar, cloud, drive, sheets
from google_cli.properties import parse_properties

FILE_ROW = {
    "id": "file_TEST",
    "name": "backup.sql",
    "mimeType": "text/plain",
    "size": "12",
    "parents": ["parent_TEST"],
    "webViewLink": "https://example.test/file",
}
PROPERTY_ARGS = [
    ["--properties", "id,name,size,parents"],
    ["--properties", "id", "--properties", "name,size", "-p", "parents"],
    ["--properties", " id , name ,size, parents "],
]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ([], None),
        ([","], None),
        (["id,name"], ["id", "name"]),
        (["id", "name,size"], ["id", "name", "size"]),
        ([" id , name "], ["id", "name"]),
    ],
)
def test_parse_properties(raw, expected):
    assert parse_properties(raw) == expected


def _files_service(monkeypatch, module):
    service = SimpleNamespace(
        files=lambda: SimpleNamespace(
            list=lambda **kwargs: SimpleNamespace(execute=lambda: {"files": [dict(FILE_ROW)]})
        )
    )
    monkeypatch.setattr(
        module,
        "get_client",
        lambda **kwargs: SimpleNamespace(get_drive_service=lambda: service, get_sheets_service=lambda: service),
    )


@pytest.mark.parametrize("extra", PROPERTY_ARGS)
@pytest.mark.parametrize("command", [["list"], ["search", "backup"]])
def test_drive_projects_requested_fields(monkeypatch, command, extra):
    _files_service(monkeypatch, drive)
    result = CliRunner().invoke(drive.app, [*command, *extra])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {"id": "file_TEST", "name": "backup.sql", "size": "12", "parents": ["parent_TEST"]}
    ]


def test_drive_table_columns_use_split_properties(monkeypatch):
    _files_service(monkeypatch, drive)
    captured = []
    monkeypatch.setattr(drive, "print_table", lambda rows, cols, headers: captured.append(cols))
    result = CliRunner().invoke(drive.app, ["search", "backup", "--table", "-p", "name,id"])
    assert result.exit_code == 0, result.output
    assert captured == [["name", "id"]]


def test_sheets_list_projects_comma_separated_properties(monkeypatch):
    _files_service(monkeypatch, sheets)
    result = CliRunner().invoke(sheets.app, ["list", "--properties", "id,name"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": "file_TEST", "name": "backup.sql"}]


def test_cloud_projects_list_projects_comma_separated_properties(monkeypatch):
    project = {"projectId": "proj_TEST", "displayName": "Proj", "state": "ACTIVE", "name": "projects/1"}
    service = SimpleNamespace(
        projects=lambda: SimpleNamespace(
            search=lambda **kwargs: SimpleNamespace(execute=lambda: {"projects": [project]})
        )
    )
    monkeypatch.setattr(
        cloud, "get_client", lambda **kwargs: SimpleNamespace(get_cloud_resource_manager_service=lambda: service)
    )
    result = CliRunner().invoke(cloud.projects_app, ["list", "--properties", "projectId,state"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"projectId": "proj_TEST", "state": "ACTIVE"}]


def test_calendar_list_projects_comma_separated_properties(monkeypatch):
    event = {"id": "evt_TEST", "summary": "Standup", "start": {"date": "2026-11-01"}, "end": {"date": "2026-11-02"}}
    service = SimpleNamespace(
        events=lambda: SimpleNamespace(list=lambda **kwargs: SimpleNamespace(execute=lambda: {"items": [event]}))
    )
    monkeypatch.setattr(
        calendar, "get_client", lambda **kwargs: SimpleNamespace(get_calendar_service=lambda: service)
    )
    result = CliRunner().invoke(calendar.app, ["list", "--properties", "id,summary"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": "evt_TEST", "summary": "Standup"}]
