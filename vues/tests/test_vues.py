"""Unit tests for the Vues CLI client.

These tests exercise the client against fixtures built from the verified API
contract (base URL, error envelope, routes) and from the Supabase session
formats the browser can hold. They cover transport, session parsing/refresh,
the standard browser login hooks (session capture, HTTP-only auth checks),
OpenAPI endpoint resolution, submission dedupe and TikTok URL parsing.
"""

import base64
import json
import time

import pytest

from cli_tools_shared.exceptions import ClientError, CredentialError
from vues_cli import client as client_module
from vues_cli.client import VuesClient, tiktok_post, video_id
from cli_tools_shared.auth import BrowserAutomationError
from vues_cli.browser import VuesBrowser
from vues_cli.client import SESSION_COOKIE
from vues_cli.config import SUPABASE_URL, TOKEN_FIELDS, Config


class FakeConfig:
    def __init__(self, store=None):
        self.base_url = "https://api.evrgreen.ai"
        self._store = dict(store or {})

    def _get(self, name):
        return self._store.get(name)

    def _set(self, name, value):
        self._store[name] = value

    def _clear(self, name):
        self._store.pop(name, None)

    def has_saved_session(self):
        return bool(self._store.get("SUPABASE_REFRESH_TOKEN"))


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


def ok(data):
    """The Vues success envelope (verified live 2026-10-15)."""
    return {"status": "success", "code": 200, "message": "OK", "data": data}


CAMPAIGN = {"id": "7672e5ce-uuid", "short_id": "XeccWu", "name": "Camp", "submissions_enabled": True,
            "supported_platforms": ["TIKTOK"]}
POST = "https://www.tiktok.com/@ata_clipper/video/123"


@pytest.fixture
def api(monkeypatch):
    """A client whose transport answers from ``api.routes`` and records calls."""
    client = fresh_client()
    client.routes = {}
    client.calls = []

    def fake_api(method, path, params=None, body=None):
        client.calls.append((method, path, params, body))
        handler = client.routes[(method, path)]
        return handler(params, body) if callable(handler) else handler

    monkeypatch.setattr(client, "_api", fake_api)
    monkeypatch.setattr(client_module.time, "sleep", lambda *_: None)
    return client


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
    encoded = "base64-" + base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
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


# ==================== Reads ====================

def test_account_unwraps(api):
    api.routes[("GET", "/users/me")] = ok({"id": "u1", "email": "x@y.z"})
    assert api.account()["email"] == "x@y.z"


def test_missing_data_envelope_raises(api):
    api.routes[("GET", "/users/me")] = {"status": "success"}
    with pytest.raises(ClientError, match="no data envelope"):
        api.account()


def test_list_campaigns_pages_until_total(api):
    rows = [{"id": str(i)} for i in range(150)]
    api.routes[("GET", "/clipper/campaigns")] = lambda params, body: ok(
        {"items": rows[params["offset"]:params["offset"] + params["limit"]], "total": 150,
         "offset": params["offset"], "limit": params["limit"]})
    assert len(api.list_campaigns(None)) == 150
    assert [c["id"] for c in api.list_campaigns(2)] == ["0", "1"]
    assert api.calls[-1][2] == {"offset": 0, "limit": 2}


def test_get_campaign_route(api):
    api.routes[("GET", "/clipper/campaigns/XeccWu")] = ok(CAMPAIGN)
    assert api.get_campaign("XeccWu")["id"] == "7672e5ce-uuid"


def test_join_dry_run_uses_campaign_uuid(api):
    api.routes[("GET", "/clipper/campaigns/XeccWu")] = ok(CAMPAIGN)
    result = api.join_campaign("XeccWu", dry_run=True)
    assert result["request"]["url"].endswith("/api/v1/clipper/campaigns/7672e5ce-uuid/apply")
    assert ("POST", "/clipper/campaigns/7672e5ce-uuid/apply", None, {}) not in api.calls


ORG = {"id": "org-uuid", "short_id": "3gItXm", "name": "Vues", "auto_approve_applications": True, "is_member": False}
APPLY_ROUTE = ("POST", "/organizations/org-uuid/apply")


def org_routes(api, org=ORG, members=(), applications=()):
    api.routes[("GET", "/organizations/discoverable")] = ok({"items": [org], "total": 1, "offset": 0, "limit": 100})
    api.routes[("GET", "/clipper/orgs")] = ok(list(members))
    api.routes[("GET", "/clipper/applications")] = ok(list(applications))


def test_organization_lists(api):
    org_routes(api, members=[{"id": "org-uuid"}], applications=[{"id": "a1"}, {"id": "a2"}])
    assert api.discoverable_organizations(None) == [ORG]
    assert api.member_organizations(5) == [{"id": "org-uuid"}]
    assert api.organization_applications(1) == [{"id": "a1"}]


def test_get_organization_by_id_or_short_id(api):
    org_routes(api)
    assert api.get_organization("3gItXm") == ORG == api.get_organization("org-uuid")


def test_join_organization_dry_run_sends_nothing(api):
    org_routes(api)
    result = api.join_organization("3gItXm", None, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["request"] == {"method": "POST", "body": {"message": None},
                                 "url": "https://api.evrgreen.ai/api/v1/organizations/org-uuid/apply"}
    assert not any(call[:2] == APPLY_ROUTE for call in api.calls)


def test_join_organization_auto_approve_is_joined(api):
    org_routes(api)
    api.routes[APPLY_ROUTE] = ok({"id": "app-1", "status": "approved"})
    result = api.join_organization("org-uuid", "  ", dry_run=False)
    assert result["status"] == "joined" and result["application"]["status"] == "approved"
    assert ("POST", "/organizations/org-uuid/apply", None, {"message": None}) in api.calls


def test_join_organization_manual_approval_is_applied_with_message(api):
    org_routes(api, org={**ORG, "auto_approve_applications": False})
    api.routes[APPLY_ROUTE] = ok({"id": "app-1", "status": "pending"})
    assert api.join_organization("org-uuid", " hi ", dry_run=False)["status"] == "applied"
    assert ("POST", "/organizations/org-uuid/apply", None, {"message": "hi"}) in api.calls


@pytest.mark.parametrize("kwargs,reason", [
    ({"org": {**ORG, "is_member": True}}, "member"),
    ({"members": [{"id": "org-uuid"}]}, "member"),
    ({"applications": [{"id": "a1", "status": "pending", "organization": {"id": "org-uuid"}}]}, "application"),
])
def test_join_organization_never_applies_twice(api, kwargs, reason):
    org_routes(api, **kwargs)
    result = api.join_organization("org-uuid", None, dry_run=False)
    assert result["status"] == "existing" and result["reason"] == reason
    assert not any(call[:2] == APPLY_ROUTE for call in api.calls)


def test_join_organization_unknown_org_raises(api):
    org_routes(api)
    with pytest.raises(ClientError, match="not in"):
        api.join_organization("nope", None, dry_run=False)


def test_social_accounts_are_connected_rows(api):
    api.routes[("GET", "/clipper/bundle/accounts")] = ok({"connected": [{"id": "a1", "platform": "TIKTOK"}],
                                                          "verified": []})
    assert api.social_accounts() == [{"id": "a1", "platform": "TIKTOK"}]
    assert api.calls[0][2] == {"grouped": "true"}


def test_earnings_combines_balance_and_stats(api):
    api.routes[("GET", "/clipper/balance")] = ok({"available_micro": 0})
    api.routes[("GET", "/clipper/stats")] = ok({"total_earnings": 0.0})
    assert api.earnings() == {"balance": {"available_micro": 0}, "stats": {"total_earnings": 0.0}}


def test_submission_get_scans_list(api):
    api.routes[("GET", "/clipper/submissions")] = ok({"items": [{"id": "s1"}, {"id": "s2"}], "total": 2})
    assert api.submission("s2") == {"id": "s2"}
    with pytest.raises(ClientError, match="not found"):
        api.submission("s9")


# ==================== Submissions ====================

def test_create_submission_dedupes(api):
    existing = {"id": "s1", "campaign_id": CAMPAIGN["id"], "post_link": POST}
    api.routes[("GET", "/clipper/campaigns/XeccWu")] = ok(CAMPAIGN)
    api.routes[("GET", "/clipper/submissions")] = ok({"items": [existing], "total": 1})
    result = api.create_submission("XeccWu", POST, dry_run=False)
    assert result["status"] == "existing" and result["submission"] == existing
    assert api.calls[-1][2]["campaign_id"] == CAMPAIGN["id"]


def test_create_submission_dry_run(api):
    api.routes[("GET", "/clipper/campaigns/XeccWu")] = ok(CAMPAIGN)
    api.routes[("GET", "/clipper/submissions")] = ok({"items": [], "total": 0})
    result = api.create_submission("XeccWu", POST, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["request"]["url"].endswith("/api/v1/clipper/submissions")
    assert result["request"]["body"] == {"campaign_id": CAMPAIGN["id"], "post_links": [POST]}
    assert not any(call[0] == "POST" for call in api.calls)


def test_create_submission_refuses_unsupported_platform(api):
    api.routes[("GET", "/clipper/campaigns/XeccWu")] = ok({**CAMPAIGN, "supported_platforms": ["INSTAGRAM"]})
    with pytest.raises(ClientError, match="accepts only INSTAGRAM"):
        api.create_submission("XeccWu", POST, dry_run=True)


def test_create_submission_polls_batch(api):
    created = {"id": "s1", "post_link": POST}
    listings = [ok({"items": [], "total": 0}), ok({"items": [created], "total": 1})]
    api.routes[("GET", "/clipper/campaigns/XeccWu")] = ok(CAMPAIGN)
    api.routes[("GET", "/clipper/submissions")] = lambda params, body: listings.pop(0)
    api.routes[("POST", "/clipper/submissions")] = ok({"batch_id": "b1", "results": [{"post_link": POST,
                                                                                       "status": "queued"}]})
    api.routes[("GET", "/clipper/submissions/batches/b1")] = ok({"results": [{"post_link": POST,
                                                                              "status": "created"}]})
    result = api.create_submission("XeccWu", POST, dry_run=False)
    assert result == {"status": "created", "submission": created, "url": POST, "batch_id": "b1"}


def test_create_submission_reports_rejection(api):
    api.routes[("GET", "/clipper/campaigns/XeccWu")] = ok(CAMPAIGN)
    api.routes[("GET", "/clipper/submissions")] = ok({"items": [], "total": 0})
    api.routes[("POST", "/clipper/submissions")] = ok({"batch_id": "b1", "results": [
        {"post_link": POST, "status": "failed", "detail": "Account not linked"}]})
    with pytest.raises(ClientError, match="Account not linked"):
        api.create_submission("XeccWu", POST, dry_run=False)


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


# ==================== Standard browser login hooks ====================

class FakePage:
    def __init__(self, url, cookies):
        self.url = url
        self._cookies = cookies
        self.visited = []

    def cookie_list(self):
        return self._cookies

    def goto(self, url):
        self.visited.append(url)

    def wait_for_timeout(self, ms):
        pass


def test_browser_uses_standard_automated_login():
    assert VuesBrowser.MANUAL_LOGIN is False
    assert VuesBrowser.AUTH_LOGIN_HANDLER is None
    # No live page check: auth state is the saved session, proven over HTTP.
    assert VuesBrowser.AUTH_CHECK_URL == ""
    assert Config.BROWSER_SESSION_REQUIRES_API_TEST is True
    # Session tokens are auth-profile state, never tool-root config.
    assert set(Config.ADDITIONAL_AUTH_FIELDS) == set(TOKEN_FIELDS)


def test_on_authenticated_saves_supabase_session(monkeypatch):
    config = FakeConfig()
    browser = VuesBrowser(config)
    # @supabase/ssr cookie: "base64-" + base64url JSON, here split into two chunks
    # and holding "?>"-style bytes that only base64url encodes as "-"/"_".
    session = {"access_token": "a?>~", "refresh_token": "r", "expires_at": 1999999999}
    encoded = "base64-" + base64.urlsafe_b64encode(json.dumps(session).encode()).decode().rstrip("=")
    page = FakePage("https://vues.app/clipper/dashboard", [
        {"name": SESSION_COOKIE + ".0", "value": encoded[:20], "domain": "vues.app", "expires": -1},
        {"name": SESSION_COOKIE + ".1", "value": encoded[20:], "domain": "vues.app", "expires": -1},
        {"name": "ph_posthog", "value": "x", "domain": ".vues.app", "expires": -1},
    ])
    monkeypatch.setattr(VuesClient, "account", lambda self: {"id": "u1"})
    browser._on_authenticated(page)
    assert page.visited == ["https://vues.app/clipper"]
    assert config._store["SUPABASE_ACCESS_TOKEN"] == "a?>~"
    assert config._store["SUPABASE_REFRESH_TOKEN"] == "r"
    assert config._store["SUPABASE_EXPIRES_AT"] == "1999999999"
    assert config.has_saved_session()


def test_on_authenticated_without_vues_session_explains_signup():
    browser = VuesBrowser(FakeConfig())
    with pytest.raises(BrowserAutomationError, match="vues.app/login"):
        browser._on_authenticated(FakePage("https://vues.app/login", []))


def test_on_authenticated_without_creator_account(monkeypatch):
    encoded = "base64-" + base64.urlsafe_b64encode(json.dumps(
        {"access_token": "a", "refresh_token": "r"}).encode()).decode()
    page = FakePage("https://vues.app/clipper", [{"name": SESSION_COOKIE, "value": encoded, "expires": -1}])

    def no_user(self):
        raise ClientError("Vues HTTP 404: user not found")

    monkeypatch.setattr(VuesClient, "account", no_user)
    with pytest.raises(BrowserAutomationError, match="no creator account"):
        VuesBrowser(FakeConfig())._on_authenticated(page)


def test_rejected_refresh_clears_saved_session(monkeypatch):
    client = fresh_client({"SUPABASE_ACCESS_TOKEN": "old", "SUPABASE_REFRESH_TOKEN": "dead",
                           "SUPABASE_EXPIRES_AT": "1"})
    monkeypatch.setattr(client_module.requests, "post", lambda *a, **k: FakeResponse(400, {"error": "invalid_grant"}))
    with pytest.raises(CredentialError):
        client._access_token()
    assert not client.config.has_saved_session()
