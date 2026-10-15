"""Unit tests for the Vues CLI client.

Vues gates all authenticated data behind a Google/Apple account that does not
yet exist for this user, so these tests exercise the client against fixtures
built from the verified API contract (base URL, error envelope, confirmed
routes) and from the Supabase session formats the browser can hold. They cover
transport, session parsing/refresh, OpenAPI endpoint resolution, submission
dedupe and TikTok URL parsing.
"""

import base64
import json
import time

import pytest

from cli_tools_shared.exceptions import ClientError, CredentialError
from vues_cli import client as client_module
from vues_cli.client import VuesClient, tiktok_post, video_id, _as_list
from vues_cli.config import SUPABASE_URL


class FakeConfig:
    def __init__(self, store=None):
        self.base_url = "https://api.evrgreen.ai"
        self._store = dict(store or {})

    def _get(self, name):
        return self._store.get(name)

    def _set(self, name, value):
        self._store[name] = value


class FakeResponse:
    def __init__(self, status_code, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def fresh_client(tokens=None):
    store = {
        "SUPABASE_ACCESS_TOKEN": "access-1",
        "SUPABASE_REFRESH_TOKEN": "refresh-1",
        "SUPABASE_EXPIRES_AT": str(int(time.time()) + 3600),
    }
    if tokens is not None:
        store = tokens
    return VuesClient(config=FakeConfig(store))


OPENAPI_FIXTURE = {
    "openapi": "3.1.0",
    "paths": {
        "/api/v1/users/me": {"get": {"tags": ["users"]}},
        "/api/v1/organizations": {"get": {"tags": ["organizations"]}},
        "/api/v1/campaigns": {"get": {"tags": ["campaigns"]}},
        "/api/v1/campaigns/{campaign_id}": {"get": {"tags": ["campaigns"]}},
        "/api/v1/campaigns/{campaign_id}/join": {"post": {"tags": ["campaigns"], "operationId": "join_campaign"}},
        "/api/v1/social-accounts": {"get": {"tags": ["social-accounts"]}},
        "/api/v1/social-accounts/{account_id}": {"get": {"tags": ["social-accounts"]}},
        "/api/v1/submissions": {"get": {"tags": ["submissions"]}, "post": {"tags": ["submissions"]}},
        "/api/v1/submissions/{submission_id}": {"get": {"tags": ["submissions"]}},
        "/api/v1/earnings": {"get": {"tags": ["earnings"]}},
    },
}


# ==================== Supabase session parsing ====================

def test_parse_session_v2_direct():
    key = "sb-ref-auth-token"
    items = [{"key": key, "value": json.dumps(
        {"access_token": "a", "refresh_token": "r", "expires_at": 1800000000})}]
    session = VuesClient.parse_supabase_session(items, key)
    assert session == {"access_token": "a", "refresh_token": "r", "expires_at": "1800000000"}


def test_parse_session_v1_current_session():
    key = "sb-ref-auth-token"
    items = [{"key": key, "value": json.dumps(
        {"currentSession": {"access_token": "a", "refresh_token": "r", "expires_at": 1800000000},
         "expiresAt": 1800000000})}]
    session = VuesClient.parse_supabase_session(items, key)
    assert session["access_token"] == "a" and session["refresh_token"] == "r"


def test_parse_session_base64_chunked():
    key = "sb-ref-auth-token"
    raw = json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 1800000000})
    encoded = "base64-" + base64.b64encode(raw.encode()).decode().rstrip("=")
    half = len(encoded) // 2
    items = [{"key": key + ".0", "value": encoded[:half]},
             {"key": key + ".1", "value": encoded[half:]}]
    session = VuesClient.parse_supabase_session(items, key)
    assert session["access_token"] == "a" and session["refresh_token"] == "r"


def test_parse_session_missing_raises():
    with pytest.raises(CredentialError):
        VuesClient.parse_supabase_session([], "sb-ref-auth-token")


def test_parse_session_without_tokens_raises():
    key = "sb-ref-auth-token"
    items = [{"key": key, "value": json.dumps({"user": {"id": "x"}})}]
    with pytest.raises(CredentialError):
        VuesClient.parse_supabase_session(items, key)


# ==================== Session / refresh ====================

def test_access_token_uses_valid_cached_token():
    client = fresh_client()
    assert client._access_token() == "access-1"


def test_access_token_without_refresh_raises():
    client = fresh_client({"SUPABASE_ACCESS_TOKEN": "", "SUPABASE_REFRESH_TOKEN": "", "SUPABASE_EXPIRES_AT": ""})
    with pytest.raises(CredentialError):
        client._access_token()


def test_expired_refreshes_over_http(monkeypatch):
    client = fresh_client({"SUPABASE_ACCESS_TOKEN": "old", "SUPABASE_REFRESH_TOKEN": "refresh-1",
                           "SUPABASE_EXPIRES_AT": str(int(time.time()) - 10)})
    calls = {}

    def fake_post(url, params=None, headers=None, json=None, timeout=None):
        calls["url"] = url
        calls["grant"] = params
        calls["refresh_token"] = json["refresh_token"]
        return FakeResponse(200, {"access_token": "new", "refresh_token": "refresh-2", "expires_in": 3600})

    monkeypatch.setattr(client_module.requests, "post", fake_post)
    assert client._access_token() == "new"
    assert calls["url"] == f"{SUPABASE_URL}/auth/v1/token"
    assert calls["grant"] == {"grant_type": "refresh_token"}
    assert client.config._get("SUPABASE_REFRESH_TOKEN") == "refresh-2"


def test_refresh_failure_raises(monkeypatch):
    client = fresh_client({"SUPABASE_ACCESS_TOKEN": "", "SUPABASE_REFRESH_TOKEN": "refresh-1",
                           "SUPABASE_EXPIRES_AT": ""})
    monkeypatch.setattr(client_module.requests, "post",
                        lambda *a, **k: FakeResponse(400, {"error": "invalid"}))
    with pytest.raises(CredentialError):
        client._access_token()


# ==================== Transport ====================

def test_api_parses_error_envelope(monkeypatch):
    client = fresh_client()
    monkeypatch.setattr(client, "_access_token", lambda: "access-1")
    monkeypatch.setattr(client_module.requests, "request",
                        lambda *a, **k: FakeResponse(404, {"status": "error", "code": 404,
                                                           "message": "Campaign not found"}))
    with pytest.raises(ClientError) as exc:
        client._api("GET", "/campaigns/x")
    assert "Campaign not found" in str(exc.value)


def test_api_refreshes_once_on_401(monkeypatch):
    client = fresh_client()
    responses = [FakeResponse(401, {"status": "error", "code": 401, "message": "Not authenticated"}),
                 FakeResponse(200, {"id": "u1"})]
    monkeypatch.setattr(client_module.requests, "request", lambda *a, **k: responses.pop(0))
    refreshed = {"n": 0}

    def fake_refresh(_token):
        refreshed["n"] += 1
        return "access-2"

    monkeypatch.setattr(client, "_refresh", fake_refresh)
    assert client._api("GET", "/users/me") == {"id": "u1"}
    assert refreshed["n"] == 1


def test_get_retries_on_500(monkeypatch):
    client = VuesClient(config=FakeConfig(), max_retries=2, base_delay=0, max_delay=0, jitter=0)
    monkeypatch.setattr(client, "_access_token", lambda: "access-1")
    seq = [FakeResponse(500, {"status": "error"}), FakeResponse(200, {"ok": True})]
    monkeypatch.setattr(client_module.requests, "request", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(client_module.time, "sleep", lambda *_: None)
    assert client._api("GET", "/campaigns") == {"ok": True}


# ==================== OpenAPI resolution ====================

@pytest.fixture
def resolving_client(monkeypatch):
    client = fresh_client()
    monkeypatch.setattr(client, "_openapi", lambda: OPENAPI_FIXTURE)
    return client


def test_resolve_submissions(resolving_client):
    assert resolving_client.resolve("submissions", "list") == "/submissions"
    assert resolving_client.resolve("submissions", "get") == "/submissions/{submission_id}"
    assert resolving_client.resolve("submissions", "create") == "/submissions"


def test_resolve_social_and_earnings(resolving_client):
    assert resolving_client.resolve("social_accounts", "list") == "/social-accounts"
    assert resolving_client.resolve("earnings", "list") == "/earnings"


def test_resolve_join(resolving_client):
    assert resolving_client.resolve("join", "create") == "/campaigns/{campaign_id}/join"


def test_resolve_missing_raises(monkeypatch):
    client = fresh_client()
    monkeypatch.setattr(client, "_openapi", lambda: {"paths": {}})
    with pytest.raises(ClientError):
        client.resolve("submissions", "list")


# ==================== Reads ====================

def test_account_unwraps(monkeypatch):
    client = fresh_client()
    monkeypatch.setattr(client, "_api", lambda *a, **k: {"data": {"id": "u1", "email": "x@y.z"}})
    assert client.account()["email"] == "x@y.z"


def test_list_campaigns_limits(monkeypatch):
    client = fresh_client()
    monkeypatch.setattr(client, "_api", lambda *a, **k: {"data": [{"id": "1"}, {"id": "2"}, {"id": "3"}]})
    assert [c["id"] for c in client.list_campaigns(2)] == ["1", "2"]


def test_as_list_variants():
    assert _as_list([{"id": "1"}]) == [{"id": "1"}]
    assert _as_list({"data": [{"id": "1"}]}) == [{"id": "1"}]
    with pytest.raises(ClientError):
        _as_list({"nope": 1})


# ==================== Submissions ====================

def test_create_submission_dedupes(monkeypatch, resolving_client):
    existing = {"id": "s1", "campaignId": "c1", "post_url": "https://www.tiktok.com/@ata_clipper/video/123"}
    monkeypatch.setattr(resolving_client, "submissions", lambda campaign_id=None, limit=None: [existing])
    result = resolving_client.create_submission("c1", "https://www.tiktok.com/@ata_clipper/video/123", dry_run=False)
    assert result["status"] == "existing" and result["submission"] == existing


def test_create_submission_dry_run(monkeypatch, resolving_client):
    monkeypatch.setattr(resolving_client, "submissions", lambda campaign_id=None, limit=None: [])
    result = resolving_client.create_submission("c1", "https://www.tiktok.com/@ata_clipper/video/123", dry_run=True)
    assert result["status"] == "dry_run"
    assert result["request"]["url"].endswith("/api/v1/submissions")
    assert result["request"]["body"]["campaign_id"] == "c1"


# ==================== TikTok URL helpers ====================

def test_tiktok_post_canonicalizes():
    canonical, user, vid = tiktok_post("https://www.tiktok.com/@ATA_Clipper/video/7999/")
    assert canonical == "https://www.tiktok.com/@ata_clipper/video/7999"
    assert user == "ata_clipper" and vid == "7999"


def test_tiktok_post_rejects_bad_url():
    with pytest.raises(ClientError):
        tiktok_post("https://example.com/video/1")


def test_video_id():
    assert video_id("https://www.tiktok.com/@u/video/55") == "55"
    assert video_id(None) is None
