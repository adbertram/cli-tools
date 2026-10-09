from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from google_cli.commands import drive
from google_cli.filter_translator import (
    UnsupportedDriveFilterError,
    translate_drive_filters,
)

FOLDER_ID = "1GHCqvrwUVEnGsEgpe5JOYMhQwiRzBTGT"


class FakeFilesResource:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.list_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return SimpleNamespace(execute=lambda: {"files": self.rows})


def _patch_drive_service(monkeypatch, rows=None):
    files = FakeFilesResource(rows)
    service = SimpleNamespace(files=lambda: files)
    monkeypatch.setattr(
        drive,
        "get_client",
        lambda **kwargs: SimpleNamespace(get_drive_service=lambda: service),
    )
    return files


def test_drive_list_folder_sends_parents_clause(monkeypatch):
    files = _patch_drive_service(monkeypatch)
    result = CliRunner().invoke(drive.app, ["list", "--folder", FOLDER_ID])
    assert result.exit_code == 0, result.output
    assert [call["q"] for call in files.list_calls] == [f"'{FOLDER_ID}' in parents"]


def test_drive_list_folder_short_flag_sends_parents_clause(monkeypatch):
    files = _patch_drive_service(monkeypatch)
    result = CliRunner().invoke(drive.app, ["list", "-F", FOLDER_ID])
    assert result.exit_code == 0, result.output
    assert [call["q"] for call in files.list_calls] == [f"'{FOLDER_ID}' in parents"]


def test_drive_list_folder_combines_with_filter(monkeypatch):
    files = _patch_drive_service(monkeypatch)
    result = CliRunner().invoke(
        drive.app,
        ["list", "--folder", FOLDER_ID, "--filter", "mimeType:eq:video/mp4"],
    )
    assert result.exit_code == 0, result.output
    query = files.list_calls[0]["q"]
    assert query == f"('{FOLDER_ID}' in parents) and (mimeType='video/mp4')"


@pytest.mark.parametrize("invalid", ["short", "a" * 9, "abc/def", "bad id!", ""])
def test_drive_list_invalid_folder_is_refused_without_api_call(monkeypatch, invalid):
    files = _patch_drive_service(monkeypatch)
    result = CliRunner().invoke(drive.app, ["list", "--folder", invalid])
    assert result.exit_code != 0
    assert files.list_calls == []
    assert "--folder" in result.output
    assert "not a valid Google Drive folder ID" in result.output


def test_filter_parents_eq_matches_folder_option(monkeypatch):
    assert translate_drive_filters([f"parents:eq:{FOLDER_ID}"]) == f"'{FOLDER_ID}' in parents"

    files = _patch_drive_service(monkeypatch)
    result = CliRunner().invoke(drive.app, ["list", "--filter", f"parents:eq:{FOLDER_ID}"])
    assert result.exit_code == 0, result.output
    assert [call["q"] for call in files.list_calls] == [f"'{FOLDER_ID}' in parents"]


def test_unsupported_filter_field_raises_instead_of_being_dropped():
    with pytest.raises(UnsupportedDriveFilterError) as excinfo:
        translate_drive_filters(["modifiedTime:gt:2024-01-01"])
    assert "modifiedTime" in str(excinfo.value)


def test_unsupported_filter_field_is_refused_without_api_call(monkeypatch):
    files = _patch_drive_service(monkeypatch)
    result = CliRunner().invoke(
        drive.app, ["list", "--filter", "modifiedTime:gt:2024-01-01"]
    )
    assert result.exit_code != 0
    assert files.list_calls == []
    assert "modifiedTime" in result.output


@pytest.mark.parametrize(
    "filter_value,expected",
    [
        ("name:eq:report", "name='report'"),
        ("name:ne:report", "name!='report'"),
        ("name:like:%report%", "name contains 'report'"),
        ("type:eq:application/pdf", "mimeType='application/pdf'"),
        ("folder:eq:ABC123", "'ABC123' in parents"),
        ("parent:eq:ABC123", "'ABC123' in parents"),
        ("trashed:eq:false", "trashed=false"),
    ],
)
def test_supported_drive_fields_still_translate(filter_value, expected):
    assert translate_drive_filters([filter_value]) == expected


def test_multiple_filters_are_joined_with_and():
    assert (
        translate_drive_filters(["name:eq:report", "trashed:eq:false"])
        == "name='report' and trashed=false"
    )
