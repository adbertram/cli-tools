"""Deterministic tests for Cloudflare R2 commands."""
from __future__ import annotations

import hashlib
import json
import threading
import time

from botocore.exceptions import ClientError as BotoClientError
from typer.testing import CliRunner

import requests

from cloudflare_cli.client import (
    CloudflareClient,
    R2_ENABLEMENT_MESSAGE,
    required_permission_group,
)
from cloudflare_cli.commands import r2 as r2_module


ACCOUNT_ID = "aa11bb33cc55dd77ee99ff0012345678"


class FakeClient:
    base_url = "https://api.cloudflare.com/client/v4"
    headers = {"Authorization": "Bearer redacted", "Content-Type": "application/json"}
    max_retries = 3

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def default_account_id(self):
        return ACCOUNT_ID

    def resolve_account_id(self, account):
        return ACCOUNT_ID

    def _make_request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        return self.responses.pop(0)

    def _get_retry_after(self, response):
        value = response.headers.get("Retry-After")
        return float(value) if value is not None else None

    def _calculate_retry_delay(self, attempt, retry_after=None):
        return retry_after if retry_after is not None else 2 ** attempt

    def _is_retryable(self, response, exception):
        # Delegate to the real predicate so the R2 object path and the shared
        # client cannot drift on what counts as a transient failure.
        return CloudflareClient._is_retryable(self, response, exception)


class FakeResponse:
    def __init__(self, payload=None, headers=None, content=b"", text=""):
        self.ok = True
        self.status_code = 200
        self._payload = payload or {"success": True, "result": {}}
        self.headers = headers or {}
        self.text = text
        self._content = content
        self.closed = False

    def json(self):
        return self._payload

    def close(self):
        self.closed = True

    def iter_content(self, size):
        yield self._content


def invoke(monkeypatch, client, args):
    monkeypatch.setattr(r2_module, "get_client", lambda: client)
    return CliRunner().invoke(r2_module.app, args)


def test_bucket_list_uses_r2_api_and_outputs_array(monkeypatch):
    client = FakeClient([{"result": {"buckets": [{"name": "media"}]}}])
    result = invoke(monkeypatch, client, ["buckets", "list", "--limit", "25"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"name": "media"}]
    assert client.calls == [(
        "GET",
        f"/accounts/{ACCOUNT_ID}/r2/buckets",
        {"params": {"per_page": 25}, "headers": {}},
    )]


def test_r2_permissions_are_actionable():
    endpoint = f"/accounts/{ACCOUNT_ID}/r2/buckets"
    assert required_permission_group("GET", endpoint) == "Account > Workers R2 Storage > Read"
    assert required_permission_group("PUT", endpoint) == "Account > Workers R2 Storage > Write"


def test_object_response_preserves_r2_enablement_guidance():
    endpoint = f"/accounts/{ACCOUNT_ID}/r2/buckets/media/objects/key"
    response = FakeResponse(
        {"success": False, "errors": [{"message": R2_ENABLEMENT_MESSAGE}]}
    )
    response.ok = False
    response.status_code = 403

    error = r2_module._response_error(response, "GET", endpoint)

    message = str(error)
    assert f"API request failed (403): {R2_ENABLEMENT_MESSAGE}" in message
    assert "Dashboard > Storage & databases > R2 > Overview" in message
    assert "Complete the R2 subscription checkout" in message
    assert "Permission group required" not in message
    assert "cloudflare-api-key" not in message


def test_object_response_identifies_cloudflare_html_challenge_without_auth_advice():
    endpoint = (
        f"/accounts/{ACCOUNT_ID}/r2/buckets/media/objects/"
        "wp-content/uploads/x..png"
    )
    response = FakeResponse(
        headers={"Content-Type": "text/html; charset=UTF-8"},
        text=(
            "<!DOCTYPE html><html><head>"
            "<title>Attention Required! | Cloudflare</title>"
            "</head><body><h1>Sorry, you have been blocked</h1></body></html>"
        ),
    )
    response.ok = False
    response.status_code = 403

    error = r2_module._response_error(response, "PUT", endpoint)

    message = str(error)
    assert "Cloudflare blocked the R2 REST object path before R2 processed it" in message
    assert "object key contains '..'" in message
    assert "percent-encoding the dots does not bypass the edge rule" in message
    assert "not an API-token permission failure" in message
    assert "Permission group required" not in message
    assert "cloudflare-api-key" not in message
    assert "<!DOCTYPE html>" not in message


def test_object_json_403_remains_a_fail_fast_permission_error():
    endpoint = f"/accounts/{ACCOUNT_ID}/r2/buckets/media/objects/key.png"
    response = FakeResponse(
        {"success": False, "errors": [{"message": "Authentication error"}]}
    )
    response.ok = False
    response.status_code = 403

    error = r2_module._response_error(response, "PUT", endpoint)

    message = str(error)
    assert "API request failed (403): Authentication error" in message
    assert "Permission group required: Account > Workers R2 Storage > Write" in message
    assert "Cloudflare blocked the R2 REST object path" not in message


def test_bucket_create_uses_documented_body(monkeypatch):
    client = FakeClient([{"result": {"name": "media"}}])
    result = invoke(
        monkeypatch,
        client,
        ["buckets", "create", "media", "--location", "enam", "--storage-class", "Standard"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"name": "media"}
    assert client.calls[0][2]["data"] == {
        "name": "media",
        "storageClass": "Standard",
        "locationHint": "enam",
    }


def test_put_preserves_slashes_and_sets_content_type(monkeypatch, tmp_path):
    source = tmp_path / "image.jpg"
    source.write_bytes(b"jpeg-bytes")
    client = FakeClient([])
    response = FakeResponse({"success": True, "result": {"key": "wp-content/uploads/image.jpg"}})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs, kwargs["data"].read()))
        return response

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    result = invoke(
        monkeypatch,
        client,
        ["objects", "put", "media", "wp-content/uploads/image.jpg", "--file", str(source), "--content-type", "image/jpeg"],
    )
    assert result.exit_code == 0, result.output
    assert calls[0][0] == "PUT"
    assert calls[0][1].endswith(f"/accounts/{ACCOUNT_ID}/r2/buckets/media/objects/wp-content/uploads/image.jpg")
    assert calls[0][2]["headers"]["Content-Type"] == "image/jpeg"
    assert calls[0][3] == b"jpeg-bytes"


def test_put_retries_429_honors_retry_after_and_rewinds_body(monkeypatch, tmp_path):
    source = tmp_path / "image.jpg"
    source.write_bytes(b"jpeg-bytes")
    client = FakeClient([])
    rate_limited = FakeResponse(
        {"errors": [{"message": "Please wait and consider throttling your request speed"}]},
        headers={"Retry-After": "7"},
    )
    rate_limited.ok = False
    rate_limited.status_code = 429
    responses = [rate_limited, FakeResponse({"success": True, "result": {"key": "image.jpg"}})]
    uploaded_bodies = []
    delays = []

    def fake_request(method, url, **kwargs):
        uploaded_bodies.append(kwargs["data"].read())
        return responses.pop(0)

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", delays.append)

    result = invoke(
        monkeypatch,
        client,
        ["objects", "put", "media", "image.jpg", "--file", str(source)],
    )

    assert result.exit_code == 0, result.output
    assert uploaded_bodies == [b"jpeg-bytes", b"jpeg-bytes"]
    assert delays == [7.0]
    assert rate_limited.closed is True


# Verbatim text of the requests.exceptions.SSLError raised on 2026-08-25 when a
# concurrent `uv tool install` rebuilt this tool's site-packages and unlinked
# certifi's cacert.pem while a sync worker was opening it for a new TLS
# connection. urllib3 converts that OSError into SSLError (util/ssl_.py:
# `except OSError as e: raise SSLError(e) from e`).
CERTIFI_RACE_SSL_ERROR = (
    "HTTPSConnectionPool(host='api.cloudflare.com', port=443): Max retries "
    "exceeded with url: /client/v4/accounts/"
    f"{ACCOUNT_ID}/r2/buckets/media/objects/wp-content/uploads/image.jpg "
    "(Caused by SSLError(FileNotFoundError(2, 'No such file or directory')))"
)


def test_put_retries_transient_ssl_error_and_rewinds_body(monkeypatch, tmp_path):
    source = tmp_path / "image.jpg"
    source.write_bytes(b"jpeg-bytes")
    client = FakeClient([])
    uploaded_bodies = []
    delays = []
    attempts = 0

    def fake_request(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        uploaded_bodies.append(kwargs["data"].read())
        if attempts == 1:
            raise requests.exceptions.SSLError(CERTIFI_RACE_SSL_ERROR)
        return FakeResponse({"success": True, "result": {"key": "image.jpg"}})

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", delays.append)

    result = invoke(
        monkeypatch,
        client,
        ["objects", "put", "media", "image.jpg", "--file", str(source)],
    )

    assert result.exit_code == 0, result.output
    assert attempts == 2
    # The body must be re-seeked, not truncated to empty, on the retry.
    assert uploaded_bodies == [b"jpeg-bytes", b"jpeg-bytes"]
    assert delays == [1]
    assert "Transient transport failure on PUT" in result.stderr


def test_get_retries_transient_ssl_error(monkeypatch):
    client = FakeClient([])
    delays = []
    attempts = 0

    def fake_request(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.exceptions.SSLError(CERTIFI_RACE_SSL_ERROR)
        return FakeResponse(headers={"Content-Length": "11", "ETag": '"abc123"'})

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", delays.append)

    result = invoke(monkeypatch, client, ["objects", "head", "media", "image.jpg"])

    assert result.exit_code == 0, result.output
    assert attempts == 2
    assert json.loads(result.stdout)["etag"] == "abc123"


def test_sync_exhausts_transient_ssl_retries_with_object_key(monkeypatch, tmp_path):
    source = tmp_path / "image.jpg"
    source.write_bytes(b"jpeg-bytes")
    client = FakeClient([{"result": [], "result_info": {"is_truncated": False}}])
    attempts = 0

    def fake_request(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        raise requests.exceptions.SSLError(CERTIFI_RACE_SSL_ERROR)

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", lambda _delay: None)

    result = invoke(monkeypatch, client, ["objects", "sync", "media", str(tmp_path)])

    assert result.exit_code == 1
    assert attempts == 4
    assert "Failed to upload R2 object wp-content/uploads/image.jpg" in result.stderr
    assert "No such file or directory" in result.stderr
    assert result.stdout == ""


def test_object_request_does_not_retry_non_transient_transport_error(
    monkeypatch, tmp_path
):
    """A malformed-request exception is permanent; retrying only hides it."""
    source = tmp_path / "image.jpg"
    source.write_bytes(b"jpeg-bytes")
    client = FakeClient([{"result": [], "result_info": {"is_truncated": False}}])
    attempts = 0
    delays = []

    def fake_request(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        raise requests.exceptions.InvalidURL("bad url")

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", delays.append)

    result = invoke(monkeypatch, client, ["objects", "sync", "media", str(tmp_path)])

    assert result.exit_code == 1
    assert attempts == 1
    assert delays == []
    assert "Failed to upload R2 object wp-content/uploads/image.jpg" in result.stderr


def test_get_still_fails_fast_on_server_error_status(monkeypatch):
    """Transport-exception retries must not turn GET into a status-retrying call."""
    client = FakeClient([])
    attempts = 0
    delays = []

    def fake_request(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        response = FakeResponse({"errors": [{"message": "server error"}]})
        response.ok = False
        response.status_code = 500
        return response

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", delays.append)

    result = invoke(monkeypatch, client, ["objects", "head", "media", "image.jpg"])

    assert result.exit_code == 1
    assert attempts == 1
    assert delays == []
    assert "API request failed (500): server error" in result.stderr


class FakeS3Client:
    def __init__(self, head_response=None, put_error=None, head_error=None):
        self.put_calls = []
        self.head_calls = []
        self._head_response = head_response or {}
        self._put_error = put_error
        self._head_error = head_error

    def put_object(self, **kwargs):
        if self._put_error is not None:
            raise self._put_error
        body = kwargs.pop("Body")
        self.put_calls.append({**kwargs, "Body": body.read()})
        return {}

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        if self._head_error is not None:
            raise self._head_error
        return self._head_response


def test_put_s3_uploads_via_boto3_with_r2_endpoint_and_secret_keys(monkeypatch, tmp_path):
    source = tmp_path / "Running-repadmin-with-no-parameters..png"
    source.write_bytes(b"png-bytes")
    client = FakeClient([])
    fake_s3 = FakeS3Client()
    boto3_calls = []

    def fake_boto3_client(service, **kwargs):
        boto3_calls.append((service, kwargs))
        return fake_s3

    secrets = {
        "cloudflare-r2-access-key-id": "AKIAFAKE",
        "cloudflare-r2-secret-access-key": "fake-secret",
    }
    monkeypatch.setattr(r2_module.boto3, "client", fake_boto3_client)
    monkeypatch.setattr(r2_module, "read_cli_tool_secret", lambda name: secrets[name])

    result = invoke(
        monkeypatch,
        client,
        [
            "objects",
            "put-s3",
            "media",
            "wp-content/uploads/2021/08/Running-repadmin-with-no-parameters..png",
            "--file",
            str(source),
        ],
    )

    assert result.exit_code == 0, result.output
    assert boto3_calls == [(
        "s3",
        {
            "endpoint_url": f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            "aws_access_key_id": "AKIAFAKE",
            "aws_secret_access_key": "fake-secret",
            "region_name": "auto",
        },
    )]
    assert fake_s3.put_calls == [{
        "Bucket": "media",
        "Key": "wp-content/uploads/2021/08/Running-repadmin-with-no-parameters..png",
        "ContentType": "image/png",
        "Body": b"png-bytes",
    }]
    payload = json.loads(result.stdout)
    assert payload["key"] == "wp-content/uploads/2021/08/Running-repadmin-with-no-parameters..png"
    assert payload["size"] == len(b"png-bytes")


def test_put_s3_missing_secret_raises_actionable_error(monkeypatch, tmp_path):
    source = tmp_path / "file..png"
    source.write_bytes(b"x")
    client = FakeClient([])
    monkeypatch.setattr(r2_module, "read_cli_tool_secret", lambda name: None)

    result = invoke(
        monkeypatch,
        client,
        ["objects", "put-s3", "media", "wp-content/uploads/file..png", "--file", str(source)],
    )

    assert result.exit_code == 1
    assert "cloudflare-r2-access-key-id" in result.stderr
    assert "_secret-manager/secrets.sh set cloudflare-r2-access-key-id" in result.stderr


def test_put_s3_wraps_boto_client_error(monkeypatch, tmp_path):
    source = tmp_path / "file..png"
    source.write_bytes(b"x")
    client = FakeClient([])
    fake_s3 = FakeS3Client(
        put_error=BotoClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "PutObject")
    )
    monkeypatch.setattr(r2_module.boto3, "client", lambda *args, **kwargs: fake_s3)
    monkeypatch.setattr(
        r2_module,
        "read_cli_tool_secret",
        lambda name: "AKIAFAKE" if "access-key-id" in name else "fake-secret",
    )

    result = invoke(
        monkeypatch,
        client,
        ["objects", "put-s3", "media", "wp-content/uploads/file..png", "--file", str(source)],
    )

    assert result.exit_code == 1
    assert "S3 upload failed for R2 object wp-content/uploads/file..png" in result.stderr


def test_head_s3_reports_size_and_etag(monkeypatch):
    client = FakeClient([])
    fake_s3 = FakeS3Client(head_response={
        "ContentLength": 9,
        "ETag": '"abc123"',
        "ContentType": "image/png",
    })
    monkeypatch.setattr(r2_module.boto3, "client", lambda *args, **kwargs: fake_s3)
    monkeypatch.setattr(
        r2_module,
        "read_cli_tool_secret",
        lambda name: "AKIAFAKE" if "access-key-id" in name else "fake-secret",
    )

    result = invoke(
        monkeypatch,
        client,
        ["objects", "head-s3", "media", "wp-content/uploads/2021/08/Running-repadmin-with-no-parameters..png"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "key": "wp-content/uploads/2021/08/Running-repadmin-with-no-parameters..png",
        "size": 9,
        "etag": "abc123",
        "content_type": "image/png",
        "last_modified": None,
    }
    assert fake_s3.head_calls == [{
        "Bucket": "media",
        "Key": "wp-content/uploads/2021/08/Running-repadmin-with-no-parameters..png",
    }]


def test_head_streams_get_and_reports_headers(monkeypatch):
    client = FakeClient([])
    response = FakeResponse(headers={
        "Content-Length": "11",
        "Content-Type": "image/jpeg",
        "ETag": '"abc123"',
        "Last-Modified": "Tue, 25 Aug 2026 12:00:00 GMT",
    })
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    result = invoke(monkeypatch, client, ["objects", "head", "media", "wp-content/uploads/image.jpg"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["etag"] == "abc123"
    assert calls[0][0] == "GET"
    assert calls[0][2]["stream"] is True
    assert response.closed is True


def test_get_downloads_object_to_requested_file(monkeypatch, tmp_path):
    client = FakeClient([])
    response = FakeResponse(content=b"downloaded")
    monkeypatch.setattr(r2_module.requests, "request", lambda *args, **kwargs: response)
    output = tmp_path / "nested" / "image.jpg"
    result = invoke(
        monkeypatch,
        client,
        ["objects", "get", "media", "wp-content/uploads/image.jpg", "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == b"downloaded"
    assert json.loads(result.stdout)["size"] == 10


def test_sync_skips_md5_verified_object_and_uploads_missing(monkeypatch, tmp_path):
    first = tmp_path / "2026" / "01" / "same.jpg"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"same")
    second = tmp_path / "2026" / "02" / "new.png"
    second.parent.mkdir(parents=True)
    second.write_bytes(b"new")
    digest = hashlib.md5(b"same", usedforsecurity=False).hexdigest()
    client = FakeClient([{
        "result": [{
            "key": "wp-content/uploads/2026/01/same.jpg",
            "size": 4,
            "etag": digest,
        }],
        "result_info": {"is_truncated": False},
    }])
    uploads = []

    def fake_request(method, url, **kwargs):
        uploads.append((method, url, kwargs["data"].read()))
        return FakeResponse({"success": True, "result": {"key": "uploaded"}})

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    result = invoke(monkeypatch, client, ["objects", "sync", "media", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["uploaded"] == 1
    assert payload["skipped_verified"] == 1
    assert payload["skipped_rest_edge_blocked"] == 0
    assert payload["rest_edge_blocked_keys"] == []
    assert payload["total"] == 2
    assert uploads[0][1].endswith("/objects/wp-content/uploads/2026/02/new.png")


def test_sync_uploads_files_concurrently_with_exact_totals(monkeypatch, tmp_path):
    monkeypatch.setattr(r2_module, "SYNC_WORKERS", 3)
    for index in range(8):
        (tmp_path / f"file-{index}.txt").write_text(str(index))
    client = FakeClient([{
        "result": [],
        "result_info": {"is_truncated": False},
    }])
    lock = threading.Lock()
    active = 0
    max_active = 0
    content_types = []

    def fake_request(method, url, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            content_types.append(kwargs["headers"]["Content-Type"])
        time.sleep(0.02)
        kwargs["data"].read()
        with lock:
            active -= 1
        return FakeResponse()

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    result = invoke(monkeypatch, client, ["objects", "sync", "media", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "bucket": "media",
        "directory": str(tmp_path),
        "prefix": "wp-content/uploads/",
        "uploaded": 8,
        "skipped_verified": 0,
        "skipped_rest_edge_blocked": 0,
        "rest_edge_blocked_keys": [],
        "total": 8,
    }
    assert 1 < max_active <= 3
    assert content_types == ["text/plain"] * 8


def test_sync_exhausts_5xx_retries_with_object_key(monkeypatch, tmp_path):
    source = tmp_path / "broken.txt"
    source.write_text("broken")
    client = FakeClient([{
        "result": [],
        "result_info": {"is_truncated": False},
    }])

    attempts = 0

    def fake_request(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        response = FakeResponse({"errors": [{"message": "upload rejected"}]})
        response.ok = False
        response.status_code = 500
        return response

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", lambda _delay: None)
    result = invoke(monkeypatch, client, ["objects", "sync", "media", str(tmp_path)])

    assert result.exit_code == 1
    assert "Failed to upload R2 object wp-content/uploads/broken.txt" in result.stderr
    assert "API request failed after 4 attempts (500): upload rejected" in result.stderr
    assert attempts == 4
    assert result.stdout == ""


def test_sync_does_not_retry_permanent_4xx(monkeypatch, tmp_path):
    source = tmp_path / "rejected.txt"
    source.write_text("rejected")
    client = FakeClient([{
        "result": [],
        "result_info": {"is_truncated": False},
    }])
    attempts = 0
    delays = []

    def fake_request(method, url, **kwargs):
        nonlocal attempts
        attempts += 1
        response = FakeResponse({"errors": [{"message": "invalid object metadata"}]})
        response.ok = False
        response.status_code = 400
        return response

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    monkeypatch.setattr(r2_module.time, "sleep", delays.append)

    result = invoke(monkeypatch, client, ["objects", "sync", "media", str(tmp_path)])

    assert result.exit_code == 1
    assert "Failed to upload R2 object wp-content/uploads/rejected.txt" in result.stderr
    assert "API request failed (400): invalid object metadata" in result.stderr
    assert attempts == 1
    assert delays == []


def test_sync_fails_before_listing_or_uploading_for_rest_edge_blocked_key(
    monkeypatch, tmp_path
):
    blocked = tmp_path / "2020" / "06" / "report..png"
    blocked.parent.mkdir(parents=True)
    blocked.write_bytes(b"blocked")
    client = FakeClient([])
    requests = []

    monkeypatch.setattr(
        r2_module.requests,
        "request",
        lambda *args, **kwargs: requests.append((args, kwargs)),
    )
    result = invoke(monkeypatch, client, ["objects", "sync", "media", str(tmp_path)])

    assert result.exit_code == 1
    assert "cannot address 1 object key(s) containing '..'" in result.stderr
    assert "No uploads were attempted" in result.stderr
    assert "--skip-rest-edge-blocked" in result.stderr
    assert "wp-content/uploads/2020/06/report..png" in result.stderr
    assert client.calls == []
    assert requests == []


def test_sync_opt_in_skips_rest_edge_blocked_keys_and_reports_them(
    monkeypatch, tmp_path
):
    blocked = tmp_path / "2020" / "06" / "report..png"
    blocked.parent.mkdir(parents=True)
    blocked.write_bytes(b"blocked")
    safe = tmp_path / "2020" / "06" / "report.png"
    safe.write_bytes(b"safe")
    client = FakeClient([{
        "result": [],
        "result_info": {"is_truncated": False},
    }])
    uploads = []

    def fake_request(method, url, **kwargs):
        uploads.append((method, url, kwargs["data"].read()))
        return FakeResponse()

    monkeypatch.setattr(r2_module.requests, "request", fake_request)
    result = invoke(
        monkeypatch,
        client,
        [
            "objects",
            "sync",
            "media",
            str(tmp_path),
            "--skip-rest-edge-blocked",
        ],
    )

    assert result.exit_code == 0, result.output
    assert uploads == [(
        "PUT",
        (
            "https://api.cloudflare.com/client/v4/accounts/"
            f"{ACCOUNT_ID}/r2/buckets/media/objects/"
            "wp-content/uploads/2020/06/report.png"
        ),
        b"safe",
    )]
    assert json.loads(result.stdout) == {
        "bucket": "media",
        "directory": str(tmp_path),
        "prefix": "wp-content/uploads/",
        "uploaded": 1,
        "skipped_verified": 0,
        "skipped_rest_edge_blocked": 1,
        "rest_edge_blocked_keys": [
            "wp-content/uploads/2020/06/report..png"
        ],
        "total": 2,
    }


def test_object_list_follows_cursor(monkeypatch):
    client = FakeClient([
        {"result": [{"key": "one"}], "result_info": {"is_truncated": True, "cursor": "next"}},
        {"result": [{"key": "two"}], "result_info": {"is_truncated": False}},
    ])
    result = invoke(monkeypatch, client, ["objects", "list", "media", "--prefix", "wp-content/uploads/"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"key": "one"}, {"key": "two"}]
    assert client.calls[1][2]["params"]["cursor"] == "next"
