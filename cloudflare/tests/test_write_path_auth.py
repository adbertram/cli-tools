"""Regression tests for the authenticated Cloudflare write path.

Background: `cloudflare zones list` and `cloudflare dns records list` succeeded
while `cloudflare dns records delete` failed with a bare
`Error: API request failed (403): Authentication error`. Two causes were
possible:

1. The client sent a different auth header on writes than on reads.
2. The stored credential was a scoped API token carrying only Read permission
   groups, so Cloudflare rejected every write.

Cause 1 was disproven and cause 2 was proven against the live API. These tests
lock in both halves:

* Writes must carry the exact same `Authorization: Bearer` header as reads, so
  the header shape can never silently diverge by HTTP method again.
* A 403 on a write must surface an actionable scope message naming the required
  Cloudflare permission group and the secret-manager rotation command, never the
  bare "Authentication error" that sent diagnosis down the wrong path.
"""
import pytest

from cloudflare_cli import client as client_module
from cloudflare_cli.client import (
    API_TOKEN_SECRET_NAME,
    CloudflareClient,
    build_forbidden_error,
    required_permission_group,
)
from cli_tools_shared.exceptions import ClientError


ZONE_ID = "1bb82acebb2c9cc1e8c334e599db915d"
RECORD_ID = "1a71255e97798f0476aef6b083218871"
FAKE_TOKEN = "test-token-not-a-real-credential"


class _FakeConfig:
    """Minimal stand-in for the real Config so tests need no stored credential."""

    api_key = FAKE_TOKEN
    base_url = "https://api.cloudflare.com/client/v4"

    def has_credentials(self):
        return True

    def get_missing_credentials(self):
        return []


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.ok = status_code < 400
        self.text = str(payload)

    def json(self):
        return self._payload


class _RecordingTransport:
    """Captures every outbound request and replays queued responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, json=None, params=None):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "json": json}
        )
        return self._responses.pop(0)


def _build_client(monkeypatch, responses):
    monkeypatch.setattr(client_module, "get_config", lambda: _FakeConfig())
    transport = _RecordingTransport(responses)
    monkeypatch.setattr(client_module.requests, "request", transport)
    # No retry sleeps in tests.
    return CloudflareClient(max_retries=0), transport


def _ok(result):
    return _FakeResponse(200, {"success": True, "errors": [], "result": result})


def _forbidden():
    return _FakeResponse(
        403,
        {
            "success": False,
            "errors": [{"code": 10000, "message": "Authentication error"}],
            "result": None,
        },
    )


# --------------------------------------------------------------------------
# The write path must be authenticated exactly like the read path.
# --------------------------------------------------------------------------


def test_create_dns_record_sends_bearer_auth_header(monkeypatch):
    """An authenticated write carries the Bearer token and reaches the API."""
    created = {
        "id": RECORD_ID,
        "type": "TXT",
        "name": "cli-write-probe-test.atademos.com",
        "content": "cli-write-probe",
        "ttl": 60,
        "proxied": False,
        "zone_id": ZONE_ID,
    }
    client, transport = _build_client(monkeypatch, [_ok(created)])

    record = client.create_dns_record(
        zone_id=ZONE_ID,
        record_type="TXT",
        name="cli-write-probe-test.atademos.com",
        content="cli-write-probe",
        ttl=60,
    )

    assert record.id == RECORD_ID
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(f"/zones/{ZONE_ID}/dns_records")
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert call["json"]["type"] == "TXT"


def test_delete_dns_record_sends_bearer_auth_header(monkeypatch):
    """DELETE is authenticated too - the originally failing command shape."""
    client, transport = _build_client(monkeypatch, [_ok({"id": RECORD_ID})])

    result = client.delete_dns_record(ZONE_ID, RECORD_ID)

    assert result == {"id": RECORD_ID}
    call = transport.calls[0]
    assert call["method"] == "DELETE"
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


_RECORD_RESULT = {
    "id": RECORD_ID,
    "type": "TXT",
    "name": "probe.atademos.com",
    "content": "probe",
    "ttl": 60,
    "proxied": False,
    "zone_id": ZONE_ID,
}


@pytest.mark.parametrize(
    "method_name, args, kwargs, expected_method, result",
    [
        ("list_dns_records", (ZONE_ID,), {"limit": 1}, "GET", []),
        (
            "create_dns_record",
            (ZONE_ID, "TXT", "probe.atademos.com", "probe"),
            {},
            "POST",
            _RECORD_RESULT,
        ),
        (
            "update_dns_record",
            (ZONE_ID, RECORD_ID),
            {"content": "x"},
            "PATCH",
            _RECORD_RESULT,
        ),
        ("delete_dns_record", (ZONE_ID, RECORD_ID), {}, "DELETE", {"id": RECORD_ID}),
    ],
)
def test_auth_header_is_identical_across_read_and_write_methods(
    monkeypatch, method_name, args, kwargs, expected_method, result
):
    """Header construction must not vary by HTTP method.

    This is the guard against the disproven-but-plausible hypothesis that reads
    used one auth scheme and writes another.
    """
    client, transport = _build_client(monkeypatch, [_ok(result)])

    getattr(client, method_name)(*args, **kwargs)

    call = transport.calls[0]
    assert call["method"] == expected_method
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert "X-Auth-Key" not in call["headers"]
    assert "X-Auth-Email" not in call["headers"]


# --------------------------------------------------------------------------
# A 403 on a write must explain the scope problem.
# --------------------------------------------------------------------------


def test_write_403_reports_token_scope_not_bare_authentication_error(monkeypatch):
    """The live failure mode: reproduce it and assert the message is actionable."""
    client, _ = _build_client(monkeypatch, [_forbidden()])

    with pytest.raises(ClientError) as excinfo:
        client.delete_dns_record(ZONE_ID, RECORD_ID)

    message = str(excinfo.value)
    # Still reports the raw API facts.
    assert "API request failed (403): Authentication error" in message
    # Names the operation Cloudflare refused.
    assert f"Cloudflare refused DELETE /zones/{ZONE_ID}/dns_records/{RECORD_ID}" in message
    # Names the exact permission group the token is missing.
    assert "Permission group required: Zone > DNS > Edit" in message
    # Explains why working reads are not proof the credential is fine.
    assert "missing Edit scope" in message
    # Warns that `auth test` cannot detect this.
    assert "cannot detect missing Edit scope" in message
    # Gives the exact rotation command.
    assert API_TOKEN_SECRET_NAME in message
    assert "_secret-manager/secrets.sh set" in message


def test_write_403_message_is_more_than_the_bare_api_message(monkeypatch):
    """Guard against a regression that drops the diagnosis back to one line."""
    client, _ = _build_client(monkeypatch, [_forbidden()])

    with pytest.raises(ClientError) as excinfo:
        client.create_dns_record(ZONE_ID, "TXT", "probe.atademos.com", "probe")

    message = str(excinfo.value)
    assert message.strip() != "API request failed (403): Authentication error"
    assert len(message.splitlines()) > 1


def test_non_403_failure_keeps_the_plain_message(monkeypatch):
    """Only 403 gets the scope treatment; other errors stay unchanged."""
    client, _ = _build_client(
        monkeypatch,
        [
            _FakeResponse(
                404,
                {
                    "success": False,
                    "errors": [{"code": 81044, "message": "Record not found"}],
                    "result": None,
                },
            )
        ],
    )

    with pytest.raises(ClientError) as excinfo:
        client.delete_dns_record(ZONE_ID, RECORD_ID)

    message = str(excinfo.value)
    assert message == "API request failed (404): Record not found"
    assert "Permission group required" not in message


# --------------------------------------------------------------------------
# Permission-group mapping.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, endpoint, expected",
    [
        ("GET", f"/zones/{ZONE_ID}/dns_records", "Zone > DNS > Read"),
        ("POST", f"/zones/{ZONE_ID}/dns_records", "Zone > DNS > Edit"),
        ("DELETE", f"/zones/{ZONE_ID}/dns_records/{RECORD_ID}", "Zone > DNS > Edit"),
        (
            "PATCH",
            f"/zones/{ZONE_ID}/firewall/access_rules/rules/x",
            "Zone > Firewall Services > Edit",
        ),
        ("POST", f"/zones/{ZONE_ID}/purge_cache", "Zone > Cache Purge > Purge"),
        (
            "PATCH",
            f"/zones/{ZONE_ID}/settings/security_level",
            "Zone > Zone Settings > Edit",
        ),
        ("POST", "/graphql", "Zone > Analytics > Read"),
        ("GET", "/zones", "Zone > Zone > Read"),
    ],
)
def test_required_permission_group_mapping(method, endpoint, expected):
    assert required_permission_group(method, endpoint) == expected


def test_unmapped_endpoint_still_produces_an_actionable_403_message():
    """An endpoint family with no mapping must not crash or lose the guidance."""
    assert required_permission_group("POST", "/accounts/abc/rulesets") is None

    message = build_forbidden_error(
        "POST", "/accounts/abc/rulesets", "Authentication error"
    )

    assert "Cloudflare refused POST /accounts/abc/rulesets" in message
    assert "Permission group required" not in message
    assert API_TOKEN_SECRET_NAME in message
