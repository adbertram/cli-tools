"""Tests for resolving and downloading Microsoft Graph sharing URLs."""

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli_tools_shared.config import get_profiles_base_dir, get_runtime_profile_resolution
from onedrive_cli.client import ClientError, OneDriveClient, encode_share_url
from onedrive_cli.main import app


SHARE_URL = (
    "https://progresssoftware.sharepoint.com/:w:/s/GDPTeam/"
    "IQChe04_cZzdRbOgAZVC8TRHAQvlCge4URBc_BYQKVTPoQw"
    "?email=adbertram%40gmail.com&e=kLc3dA"
)


class FakeResponse:
    def __init__(self, chunks):
        self._chunks = chunks

    def iter_content(self, chunk_size):
        assert chunk_size == 8192
        return iter(self._chunks)


def test_encode_share_url_uses_unpadded_base64url():
    expected = "u!" + base64.urlsafe_b64encode(SHARE_URL.encode("utf-8")).decode("ascii").rstrip("=")

    share_id = encode_share_url(SHARE_URL)

    assert share_id == expected
    assert "=" not in share_id


def test_resolve_shared_item_requests_drive_item_metadata(monkeypatch):
    client = OneDriveClient(max_retries=0)
    calls = []
    metadata = {"id": "item-1", "name": "shared.docx", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}}

    def fake_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return metadata

    monkeypatch.setattr(client, "_make_request", fake_request)

    item = client.resolve_shared_item(SHARE_URL)

    share_id = encode_share_url(SHARE_URL)
    assert calls == [("GET", f"/shares/{share_id}/driveItem", {})]
    assert item.id == "item-1"
    assert item.name == "shared.docx"


def test_download_shared_item_resolves_metadata_then_streams_binary(monkeypatch, tmp_path):
    client = OneDriveClient(max_retries=0)
    calls = []
    metadata = {"id": "item-1", "name": "shared.docx", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}}

    def fake_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint.endswith("/driveItem"):
            return metadata
        return FakeResponse([b"PK\x03\x04", b"document-bytes"])

    monkeypatch.setattr(client, "_make_request", fake_request)
    destination = tmp_path / "nested" / "shared.docx"

    result = client.download_shared_item(SHARE_URL, str(destination))

    share_id = encode_share_url(SHARE_URL)
    assert calls == [
        ("GET", f"/shares/{share_id}/driveItem", {}),
        ("GET", f"/shares/{share_id}/driveItem/content", {"stream": True}),
    ]
    assert Path(result) == destination
    assert destination.read_bytes() == b"PK\x03\x04document-bytes"


def test_graph_api_errors_include_status_and_message(monkeypatch):
    client = OneDriveClient(max_retries=0)

    class ErrorResponse:
        ok = False
        status_code = 403
        text = '{"error":{"message":"Access denied"}}'
        headers = {}

        @staticmethod
        def json():
            return {"error": {"message": "Access denied"}}

    monkeypatch.setattr(client, "_get_headers", lambda: {})
    monkeypatch.setattr("onedrive_cli.client.requests.request", lambda **kwargs: ErrorResponse())

    with pytest.raises(ClientError, match=r"API request failed \(403\): Access denied"):
        client.resolve_shared_item(SHARE_URL)


def test_graph_redirect_without_location_raises_clean_error_not_json_crash(monkeypatch):
    """A 3xx response requests could not auto-follow (empty body, no Location
    header) must not surface a raw json.JSONDecodeError.

    ``requests.Response.ok`` is True for any status under 400, including
    redirects, so this case previously fell through to the success branch's
    unconditional ``.json()`` call on an empty body and crashed with
    "Expecting value: line 1 column 1 (char 0)".
    """
    client = OneDriveClient(max_retries=0)

    class RedirectResponse:
        ok = True
        status_code = 308
        text = ""
        content = b""
        headers = {}

        @staticmethod
        def json():
            raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr(client, "_get_headers", lambda: {})
    monkeypatch.setattr("onedrive_cli.client.requests.request", lambda **kwargs: RedirectResponse())

    with pytest.raises(ClientError, match=r"API request failed \(308\): empty response body"):
        client.resolve_shared_item(SHARE_URL)


def test_graph_2xx_with_non_json_body_raises_clean_error(monkeypatch):
    """A 2xx response with a non-JSON/unparseable body must raise ClientError,
    not propagate the underlying JSONDecodeError."""
    client = OneDriveClient(max_retries=0)

    class BadJsonResponse:
        ok = True
        status_code = 200
        text = "not json"
        content = b"not json"
        headers = {}

        @staticmethod
        def json():
            raise json.JSONDecodeError("Expecting value", "not json", 0)

    monkeypatch.setattr(client, "_get_headers", lambda: {})
    monkeypatch.setattr("onedrive_cli.client.requests.request", lambda **kwargs: BadJsonResponse())

    with pytest.raises(ClientError, match=r"could not be parsed as JSON"):
        client.resolve_shared_item(SHARE_URL)


def test_download_shared_item_does_not_create_file_when_graph_returns_error(monkeypatch, tmp_path):
    client = OneDriveClient(max_retries=0)
    destination = tmp_path / "shared.docx"

    def fail_request(method, endpoint, **kwargs):
        raise ClientError("API request failed (403): Access denied")

    monkeypatch.setattr(client, "_make_request", fail_request)

    with pytest.raises(ClientError, match=r"API request failed \(403\): Access denied"):
        client.download_shared_item(SHARE_URL, str(destination))

    assert not destination.exists()


def test_shares_download_routes_explicit_profile_and_outputs_result(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    profile_name = "progress_psdxautomation_msal_device_code_auth"
    profile_env = get_profiles_base_dir("onedrive") / profile_name / ".env"
    profile_env.parent.mkdir(parents=True, exist_ok=True)
    profile_env.write_text("ACTIVE=true\nAUTH_METHOD=msal_device_code\n")

    from cli_tools_shared import command_registry
    from onedrive_cli import config as onedrive_config
    from onedrive_cli.commands import shares

    onedrive_config._config = None
    monkeypatch.setattr(command_registry, "_check_credentials", lambda *args, **kwargs: None)

    captured = {}

    class FakeClient:
        def download_shared_item(self, share_url, local_path):
            captured["share_url"] = share_url
            captured["local_path"] = local_path
            captured["runtime_profile"] = get_runtime_profile_resolution()[0]
            Path(local_path).write_bytes(b"PK\x03\x04fake-docx")
            return local_path

    monkeypatch.setattr(shares, "get_client", lambda: FakeClient())
    destination = tmp_path / "download.docx"

    result = CliRunner().invoke(
        app,
        ["shares", "download", SHARE_URL, str(destination), "--profile", profile_name],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "share_url": SHARE_URL,
        "local_path": str(destination),
        "runtime_profile": profile_name,
    }
    assert json.loads(result.stdout) == {"path": str(destination), "success": True}
    assert destination.read_bytes() == b"PK\x03\x04fake-docx"
