"""Every Drive file read must reach files that live in Shared Drives."""
from types import SimpleNamespace

import googleapiclient.http
import pytest
from typer.testing import CliRunner

from google_cli.commands import docs, drive, sheets

FILE_ID = "1UdlXdUhMwkULj8rMLQRNbkrrwdFTj_z4"
GET_FLAGS = {"supportsAllDrives": True}
LIST_FLAGS = {"supportsAllDrives": True, "includeItemsFromAllDrives": True, "corpora": "allDrives"}


class FakeFiles:
    def __init__(self):
        self.calls = []

    def _record(self, method, kwargs):
        self.calls.append((method, kwargs))
        return SimpleNamespace(execute=lambda: {"files": [], "id": FILE_ID, "name": "report"})

    def list(self, **kwargs):
        return self._record("list", kwargs)

    def get(self, **kwargs):
        return self._record("get", kwargs)

    def get_media(self, **kwargs):
        return self._record("get_media", kwargs)

    def export_media(self, **kwargs):
        return self._record("export_media", kwargs)


class FakeDownloader:
    def __init__(self, fh, request):
        pass

    def next_chunk(self):
        return None, True


@pytest.fixture
def files(monkeypatch, tmp_path):
    fake = FakeFiles()
    client = SimpleNamespace(get_drive_service=lambda: SimpleNamespace(files=lambda: fake))
    for module in (drive, docs, sheets):
        monkeypatch.setattr(module, "get_client", lambda **kwargs: client)
    monkeypatch.setattr(googleapiclient.http, "MediaIoBaseDownload", FakeDownloader)
    monkeypatch.chdir(tmp_path)
    return fake


@pytest.mark.parametrize(
    "app,args",
    [
        (drive.app, ["list", "--folder", FILE_ID]),
        (drive.app, ["search", "report"]),
        (docs.app, ["list"]),
        (sheets.app, ["list"]),
    ],
)
def test_list_calls_include_all_drives(files, app, args):
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert [m for m, _ in files.calls] == ["list"]
    assert files.calls[0][1].items() >= LIST_FLAGS.items()


def test_drive_get_supports_all_drives(files):
    result = CliRunner().invoke(drive.app, ["get", FILE_ID])
    assert result.exit_code == 0, result.output
    assert [m for m, _ in files.calls] == ["get"]
    assert files.calls[0][1].items() >= GET_FLAGS.items()


def test_drive_download_supports_all_drives(files, tmp_path):
    result = CliRunner().invoke(drive.app, ["download", FILE_ID, "--output", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert [m for m, _ in files.calls] == ["get", "get_media"]
    assert all(kwargs.items() >= GET_FLAGS.items() for _, kwargs in files.calls)


def test_docs_export_name_lookup_supports_all_drives(files):
    result = CliRunner().invoke(docs.app, ["export", FILE_ID, "--format", "pdf"])
    assert result.exit_code == 0, result.output
    assert [m for m, _ in files.calls] == ["export_media", "get"]
    # files.export accepts only fileId and mimeType; it reaches Shared Drive files without flags.
    assert set(files.calls[0][1]) == {"fileId", "mimeType"}
    assert files.calls[1][1].items() >= GET_FLAGS.items()
