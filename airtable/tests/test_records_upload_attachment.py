import base64

import pytest
from typer.testing import CliRunner

from airtable_cli.commands import records
from airtable_cli import client as client_module
from cli_tools_shared.exceptions import ClientError


runner = CliRunner()


class FakeUploadClient:
    def __init__(self):
        self.calls = []

    def upload_attachment(self, base_id, record_id, field_name, file_path, content_type=None):
        self.calls.append(
            {
                "base_id": base_id,
                "record_id": record_id,
                "field_name": field_name,
                "file_path": file_path,
                "content_type": content_type,
            }
        )
        return {"id": record_id, "fields": {field_name: [{"id": "att1", "filename": "x.png"}]}}


def test_upload_attachment_command_wires_arguments(monkeypatch, tmp_path):
    img = tmp_path / "preview.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    fake = FakeUploadClient()
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(records, "get_client", lambda: fake)

    result = runner.invoke(
        records.app,
        ["upload-attachment", "recXYZ", "Image", str(img), "--base", "appBase"],
    )

    assert result.exit_code == 0, result.stdout
    assert fake.calls == [
        {
            "base_id": "appBase",
            "record_id": "recXYZ",
            "field_name": "Image",
            "file_path": str(img),
            "content_type": None,
        }
    ]


def test_upload_attachment_command_passes_content_type(monkeypatch, tmp_path):
    blob = tmp_path / "file.bin"
    blob.write_bytes(b"abc")

    fake = FakeUploadClient()
    monkeypatch.setattr(records, "resolve_base_id", lambda base_id: "appBase")
    monkeypatch.setattr(records, "get_client", lambda: fake)

    result = runner.invoke(
        records.app,
        [
            "upload-attachment",
            "recXYZ",
            "Image",
            str(blob),
            "--base",
            "appBase",
            "--content-type",
            "image/png",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert fake.calls[0]["content_type"] == "image/png"


# ----- client.upload_attachment unit behavior -----


def _make_client_without_init(monkeypatch):
    """Build an AirtableClient instance without touching real config/auth."""
    client = client_module.AirtableClient.__new__(client_module.AirtableClient)
    client.headers = {"Authorization": "Bearer pat_fake"}
    return client


def test_client_upload_attachment_missing_file(monkeypatch):
    client = _make_client_without_init(monkeypatch)
    with pytest.raises(ClientError, match="Attachment file not found"):
        client.upload_attachment("appBase", "recX", "Image", "/no/such/file.png")


def test_client_upload_attachment_rejects_oversize(monkeypatch, tmp_path):
    client = _make_client_without_init(monkeypatch)
    # Force a tiny cap so a small file trips the size guard deterministically.
    monkeypatch.setattr(client_module.AirtableClient, "UPLOAD_MAX_BASE64_BYTES", 4)
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" * 4)  # >4 base64 bytes once encoded

    with pytest.raises(ClientError, match="exceeds Airtable's"):
        client.upload_attachment("appBase", "recX", "Image", str(big))


def test_client_upload_attachment_unknown_content_type(monkeypatch, tmp_path):
    client = _make_client_without_init(monkeypatch)
    unknown = tmp_path / "file.unknownext"
    unknown.write_bytes(b"data")

    with pytest.raises(ClientError, match="Could not determine content type"):
        client.upload_attachment("appBase", "recX", "Image", str(unknown))


def test_client_upload_attachment_posts_to_content_host(monkeypatch, tmp_path):
    client = _make_client_without_init(monkeypatch)
    img = tmp_path / "preview.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    captured = {}

    class FakeResponse:
        ok = True
        status_code = 200

        def json(self):
            return {"id": "recX", "fields": {"Image": [{"id": "att1"}]}}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(client_module.requests, "post", fake_post)

    result = client.upload_attachment("appBase", "recX", "Image", str(img))

    assert result == {"id": "recX", "fields": {"Image": [{"id": "att1"}]}}
    assert captured["url"] == "https://content.airtable.com/v0/appBase/recX/Image/uploadAttachment"
    assert captured["headers"]["Authorization"] == "Bearer pat_fake"
    body = captured["json"]
    assert body["contentType"] == "image/png"
    assert body["filename"] == "preview.png"
    # File bytes are base64-encoded with no data: prefix.
    assert body["file"] == base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
