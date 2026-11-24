"""Drive copy, create-folder and move build the right API calls and print the documented JSON."""
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from google_cli.commands import drive

FILE_ID = "1UdlXdUhMwkULj8rMLQRNbkrrwdFTj_z4"
FOLDER_A = "folderAAAAAAAAAA"
FOLDER_B = "folderBBBBBBBBBB"
FLAGS = {"supportsAllDrives": True}


class FakeFiles:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _call(self, method, kwargs):
        self.calls.append((method, kwargs))
        return SimpleNamespace(execute=lambda: self.responses[method])

    def copy(self, **kwargs):
        return self._call("copy", kwargs)

    def create(self, **kwargs):
        return self._call("create", kwargs)

    def get(self, **kwargs):
        return self._call("get", kwargs)

    def update(self, **kwargs):
        return self._call("update", kwargs)


def _fake(monkeypatch, responses):
    fake = FakeFiles(responses)
    client = SimpleNamespace(get_drive_service=lambda: SimpleNamespace(files=lambda: fake))
    monkeypatch.setattr(drive, "get_client", lambda **kwargs: client)
    return fake


def test_copy_with_parent(monkeypatch):
    fake = _fake(monkeypatch, {"copy": {"id": "new", "name": "Copy", "webViewLink": "https://x/new", "parents": [FOLDER_A], "extra": 1}})
    result = CliRunner().invoke(drive.app, ["copy", FILE_ID, "--name", "Copy", "--parent", FOLDER_A])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"id": "new", "name": "Copy", "url": "https://x/new", "parents": [FOLDER_A]}
    assert fake.calls == [("copy", {
        "fileId": FILE_ID, "body": {"name": "Copy", "parents": [FOLDER_A]},
        "fields": "id, name, webViewLink, parents", **FLAGS,
    })]


def test_copy_without_parent_and_from_url(monkeypatch):
    fake = _fake(monkeypatch, {"copy": {"id": "new", "name": "Copy", "webViewLink": "u", "parents": [FOLDER_A]}})
    url = f"https://docs.google.com/spreadsheets/d/{FILE_ID}/edit?gid=0#gid=0"
    result = CliRunner().invoke(drive.app, ["copy", url, "--name", "Copy"])
    assert result.exit_code == 0, result.output
    assert fake.calls[0][1]["fileId"] == FILE_ID
    assert fake.calls[0][1]["body"] == {"name": "Copy"}


def test_copy_requires_name(monkeypatch):
    _fake(monkeypatch, {})
    assert CliRunner().invoke(drive.app, ["copy", FILE_ID]).exit_code != 0


def test_create_folder(monkeypatch):
    fake = _fake(monkeypatch, {"create": {"id": "f1", "name": "Docs", "webViewLink": "https://x/f1"}})
    result = CliRunner().invoke(drive.app, ["create-folder", "--name", "Docs", "--parent", FOLDER_A])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"id": "f1", "name": "Docs", "url": "https://x/f1"}
    assert fake.calls == [("create", {
        "body": {"name": "Docs", "mimeType": "application/vnd.google-apps.folder", "parents": [FOLDER_A]},
        "fields": "id, name, webViewLink", **FLAGS,
    })]


def test_create_folder_without_parent(monkeypatch):
    fake = _fake(monkeypatch, {"create": {"id": "f1", "name": "Docs", "webViewLink": "u"}})
    result = CliRunner().invoke(drive.app, ["create-folder", "--name", "Docs"])
    assert result.exit_code == 0, result.output
    assert "parents" not in fake.calls[0][1]["body"]


def test_move_removes_all_current_parents(monkeypatch):
    fake = _fake(monkeypatch, {
        "get": {"id": FILE_ID, "parents": [FOLDER_A, "folderCCCCCCCCCC"]},
        "update": {"id": FILE_ID, "name": "Report", "parents": [FOLDER_B]},
    })
    result = CliRunner().invoke(drive.app, ["move", FILE_ID, "--to", FOLDER_B])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"id": FILE_ID, "name": "Report", "parents": [FOLDER_B]}
    assert fake.calls == [
        ("get", {"fileId": FILE_ID, "fields": "id, parents", **FLAGS}),
        ("update", {
            "fileId": FILE_ID, "addParents": FOLDER_B, "removeParents": f"{FOLDER_A},folderCCCCCCCCCC",
            "fields": "id, name, parents", **FLAGS,
        }),
    ]


def test_move_never_removes_destination_parent(monkeypatch):
    fake = _fake(monkeypatch, {
        "get": {"id": FILE_ID, "parents": [FOLDER_A, FOLDER_B]},
        "update": {"id": FILE_ID, "name": "Report", "parents": [FOLDER_B]},
    })
    result = CliRunner().invoke(drive.app, ["move", FILE_ID, "--to", FOLDER_B])
    assert result.exit_code == 0, result.output
    assert fake.calls[1][1]["removeParents"] == FOLDER_A


@pytest.mark.parametrize("value,expected", [
    (FILE_ID, FILE_ID),
    (f"https://drive.google.com/file/d/{FILE_ID}/view", FILE_ID),
    (f"https://drive.google.com/drive/folders/{FILE_ID}", FILE_ID),
    (f"https://drive.google.com/open?id={FILE_ID}", FILE_ID),
])
def test_parse_drive_id(value, expected):
    assert drive.parse_drive_id(value) == expected
