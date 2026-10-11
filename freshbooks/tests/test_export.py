"""Archive invariants: no silent truncation, exact source bytes, GET-only reads."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from freshbooks_cli.exporter import Exporter, safe_id

class Client:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []
    def _make_request(self, method, endpoint, **kwargs):
        assert method == "GET"
        self.calls.append((endpoint, kwargs))
        return SimpleNamespace(content=next(self.pages))

def page(rows, total, pages=1):
    return json.dumps({"response": {"result": {"items": rows, "total": total, "pages": pages}}}).encode()

def test_pages_preserve_raw_bytes_and_decimal(tmp_path):
    first = b'{"response":{"result":{"items":[{"id":1,"amount":"123.4500","rate":0.1234567890123456789}],"total":2,"pages":2}}}'
    archive = Exporter(Client([first, page([{"id": 2}], 2, 2)]), tmp_path / "export")
    records = archive.collection("items", "/items", "items")
    assert len(records) == 2
    assert (archive.root / "items/pages/default-00001.json").read_bytes() == first
    saved = json.loads((archive.root / "items/records.json").read_text())
    assert saved[0]["amount"] == "123.4500"
    assert saved[0]["rate"] == "0.1234567890123456789"
    assert archive.manifest["resources"][0]["status"] == "exported"
    assert archive.root.stat().st_mode & 0o777 == 0o700
    assert (archive.root / "items/records.json").stat().st_mode & 0o777 == 0o600

@pytest.mark.parametrize("pages", [
    [page([{"id": 1}], 2)],
    [b'{"response":{"result":{"items":[]}}}'],
    [page([{"id": 1}], 2, 2), page([{"id": 1}], 2, 2)],
    [page([], 5, 2)],
    [b'{"response":{"result":{"total":0,"pages":1}}}'],
])
def test_incomplete_collections_are_reported(tmp_path, pages):
    archive = Exporter(Client(pages), tmp_path / "export")
    archive.collection("items", "/items", "items")
    assert archive.manifest["resources"][0]["status"] == "partial"
    assert archive.manifest["resources"][0]["failures"]

def test_refuses_existing_destination(tmp_path):
    with pytest.raises(FileExistsError):
        Exporter(Client([]), tmp_path)

@pytest.mark.parametrize("value", ["../x", "a/b", "", "x.y"])
def test_ids_cannot_escape_export(value):
    with pytest.raises(Exception):
        safe_id(value)

def test_resume_reuses_only_matching_request_contract(tmp_path):
    output = tmp_path / "export"
    archive = Exporter(Client([page([{"id": 1}], 1)]), output)
    archive.collection("items", "/items", "items")
    cached = Exporter(Client([]), output, resume=True)
    cached.collection("items", "/items", "items")
    assert cached.client.calls == []
    changed = Exporter(Client([page([{"id": 2}], 1)]), output, resume=True)
    assert changed.collection("items", "/different-items", "items")[0]["id"] == 2
    assert len(changed.client.calls) == 1


def test_resume_rejects_modified_archive(tmp_path):
    output = tmp_path / "export"
    archive = Exporter(Client([page([], 0)]), output)
    archive.collection("items", "/items", "items")
    (output / "items/records.json").write_text('[] changed')
    with pytest.raises(Exception, match="checksum mismatch"):
        Exporter(Client([]), output, resume=True)


def test_team_pagination_shape(tmp_path):
    raw = json.dumps({"response": [{"uuid": "abc-123"}], "meta": {"page": 1, "per_page": 100, "total": 1}}).encode()
    archive = Exporter(Client([raw]), tmp_path / "export")
    assert archive.collection("team", "/team", "response") == [{"uuid": "abc-123"}]
    assert archive.manifest["resources"][0]["status"] == "exported"


def test_overlapping_visibility_variants_are_not_complete(tmp_path):
    raw = page([{"id": 1}], 1)
    archive = Exporter(Client([raw, raw]), tmp_path / "export")
    archive.collection("items", "/items", "items", variants=[("active", []), ("deleted", [])])
    assert archive.manifest["resources"][0]["status"] == "partial"

@pytest.mark.parametrize("declared,expected", [("text/html", 1), ("application/pdf", 0)])
def test_html_attachment_only_archived_when_declared(tmp_path, monkeypatch, declared, expected):
    client = SimpleNamespace(account_id="original")
    archive = Exporter(client, tmp_path / "export")
    response = SimpleNamespace(content=b'<html>original attachment</html>', headers={"Content-Type": "text/html"}, raise_for_status=lambda: None)
    monkeypatch.setattr("freshbooks_cli.exporter.requests.get", lambda *args, **kwargs: response)
    archive.binaries("account", [], [{"id": 1, "attachment": {"jwt": "signed", "media_type": declared}}], [])
    assert archive.manifest["resources"][0]["attachment_count"] == expected
    assert client.account_id == "original"
    assert bool(list(archive.root.rglob('*.html'))) == bool(expected)
