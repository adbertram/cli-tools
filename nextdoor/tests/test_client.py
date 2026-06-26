"""Nextdoor client regressions.

These tests cover the deterministic client logic (record normalization,
GraphQL routing/payloads, auth-wall detection, and error handling) without a
live Nextdoor session. Cookie loading is mocked so the persistent-profile
browser is never launched.
"""

import json
from pathlib import Path

import pytest

import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserCookie,
    RequestsRetryPolicy,
)

from nextdoor_cli import client as client_module
from nextdoor_cli.client import (
    NextdoorClient,
    normalize_feed_item,
    normalize_notification,
    normalize_search_suggestion,
    _is_login_wall,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """Load a captured GraphQL ``data`` object fixture."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ---- Pure normalizers (real captured shapes) --------------------------------


def test_normalize_feed_item_post_uses_subject_title():
    raw = {
        "feedItemType": "POST",
        "contentId": 489406804,
        "post": {"id": "post_489406804", "subject": "(HAHAHAHAHAHAH)", "body": "..."},
    }
    assert normalize_feed_item(raw) == {
        "id": 489406804,
        "type": "POST",
        "title": "(HAHAHAHAHAHAH)",
    }


def test_normalize_feed_item_promo_uses_sponsor_name():
    raw = {
        "feedItemType": "PROMO",
        "contentId": 6658602269397747960,
        "promo": {
            "promoType": "NAMPLUS_AD",
            "creative": {"sponsorName": {"text": "Homeaglow"}},
        },
    }
    assert normalize_feed_item(raw) == {
        "id": 6658602269397747960,
        "type": "PROMO",
        "title": "Homeaglow",
    }


def test_normalize_feed_item_unknown_type_has_no_title():
    raw = {"feedItemType": "MYSTERY", "contentId": 1, "post": {"subject": "ignored"}}
    record = normalize_feed_item(raw)
    assert record == {"id": 1, "type": "MYSTERY", "title": None}


def test_normalize_search_suggestion_wraps_plain_string():
    assert normalize_search_suggestion("House Cleaner") == {"suggestion": "House Cleaner"}


def test_normalize_notification_uses_type_title_badges():
    raw = {"type": "saved_bookmarks", "title": "Bookmarks", "badges": None, "__typename": "Shortcut"}
    assert normalize_notification(raw) == {
        "id": "saved_bookmarks",
        "label": "Bookmarks",
        "badges": None,
    }


# ---- Fixture-driven operation tests (real captured responses) ---------------


def test_get_feed_against_real_fixture(monkeypatch):
    data = _load_fixture("PersonalizedFeed")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    rows = client.get_feed(limit=50)

    # 8 POST + 3 PROMO items in the captured feed.
    assert len(rows) == 11
    assert {r["type"] for r in rows} == {"POST", "PROMO"}
    # Every row has a stable contentId-derived id and the documented keys.
    assert all(set(r.keys()) == {"id", "type", "title"} for r in rows)
    assert all(r["id"] is not None for r in rows)
    posts = [r for r in rows if r["type"] == "POST"]
    promos = [r for r in rows if r["type"] == "PROMO"]
    assert len(posts) == 8 and len(promos) == 3
    # POST titles come from post.subject; the captured feed has a known one.
    assert any(r["title"] == "(HAHAHAHAHAHAH)" for r in posts)
    # PROMO titles come from the sponsor name.
    assert {"Homeaglow", "Match NA", "Realtor.com"} == {r["title"] for r in promos}


def test_get_notifications_against_real_fixture(monkeypatch):
    data = _load_fixture("dashboardBadges")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    rows = client.get_notifications()

    assert rows == [
        {"id": "saved_bookmarks", "label": "Bookmarks", "badges": None},
        {"id": "events", "label": "Events", "badges": None},
        {"id": "interests", "label": "Interests", "badges": None},
    ]


def test_search_against_real_fixture(monkeypatch):
    data = _load_fixture("search_park")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    rows = client.search("park")

    assert rows[0] == {"suggestion": "House Cleaner"}
    assert {"suggestion": "Plumber"} in rows
    assert all(set(r.keys()) == {"suggestion"} for r in rows)
    assert len(rows) == 8


def test_get_me_against_real_fixture(monkeypatch):
    data = _load_fixture("getMe")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    user = client.get_me()

    # get_me returns the raw, rich user object (data.me.user).
    assert user["id"] == "user_57902626"
    assert user["legacyUserId"] == "57902626"
    assert user["name"]["displayName"] == "Adam Bertram"
    assert user["__typename"] == "UserProfile"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<!DOCTYPE html><html><body>Please log in</body></html>", True),
        ('<!doctype html><a href="/login/?next=/news_feed/">Login</a>', True),
        ('{"data": {"me": null}}', False),
        ("", False),
    ],
)
def test_is_login_wall(text, expected):
    assert _is_login_wall(text) is expected


# ---- Client transport (mocked session) --------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=None):
        self.status_code = status_code
        self._json_body = json_body
        if text is not None:
            self.text = text
        elif json_body is not None:
            self.text = json.dumps(json_body)
        else:
            self.text = ""
        self.headers = {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


def _make_client(monkeypatch, *, cookies=None):
    """Build a NextdoorClient with credentials present and cookies mocked."""
    cookies = cookies or [
        BrowserCookie(name="ndp_session_id", value="sess", domain=".nextdoor.com", path="/", expires=-1),
        BrowserCookie(name="csrftoken", value="csrf-abc", domain=".nextdoor.com", path="/", expires=-1),
    ]

    class _Config:
        base_url = "https://nextdoor.com/api/gql"

        def has_credentials(self):
            return True

        def get_missing_credentials(self):
            return []

        def get_browser(self):
            raise AssertionError("browser must not launch in mocked tests")

    monkeypatch.setattr(
        BrowserAuthState,
        "from_config",
        classmethod(lambda cls, cfg: BrowserAuthState(cookies=tuple(cookies))),
    )
    return NextdoorClient(config=_Config())


def test_missing_credentials_raises():
    class _Config:
        base_url = "https://nextdoor.com/api/gql"

        def has_credentials(self):
            return False

        def get_missing_credentials(self):
            return ["BROWSER_SESSION"]

    with pytest.raises(ClientError) as exc:
        NextdoorClient(config=_Config())
    assert "auth login" in str(exc.value)


def test_session_carries_cookies_and_csrf_header(monkeypatch):
    client = _make_client(monkeypatch)
    session = client.session
    assert session.cookies.get("ndp_session_id") == "sess"
    assert session.cookies.get("csrftoken") == "csrf-abc"
    assert session.headers["x-csrftoken"] == "csrf-abc"


def test_graphql_routes_operation_in_path_and_body(monkeypatch):
    client = _make_client(monkeypatch)
    captured = {}

    def fake_request(method, url, json=None):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = json
        return _FakeResponse(json_body={"data": {"me": {"user": {"id": "u1"}}}})

    monkeypatch.setattr(client.session, "request", fake_request)
    data = client._graphql("getMe")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://nextdoor.com/api/gql/getMe"
    assert captured["body"]["operationName"] == "getMe"
    assert (
        captured["body"]["extensions"]["persistedQuery"]["sha256Hash"]
        == client_module.PERSISTED_QUERIES["getMe"]
    )
    assert data == {"me": {"user": {"id": "u1"}}}


def test_graphql_unknown_operation_raises(monkeypatch):
    client = _make_client(monkeypatch)
    with pytest.raises(ClientError) as exc:
        client._graphql("NotARealOp")
    assert "Unknown Nextdoor GraphQL operation" in str(exc.value)


def test_graphql_login_wall_raises_auth_error(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(status_code=403, text="<!DOCTYPE html><body>Log in</body>"),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "auth login --force" in str(exc.value)


def test_graphql_null_me_raises_auth_error(monkeypatch):
    # Nextdoor answers an unauthenticated persisted query with HTTP 200 and
    # data.me == null (no 401/403, no GraphQL error). This must fail loudly.
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": None, "requestId": "x"}}),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "not authenticated" in str(exc.value).lower()
    assert "auth login --force" in str(exc.value)


def test_get_feed_raises_auth_error_on_null_me(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": None}}),
    )
    with pytest.raises(ClientError) as exc:
        client.get_feed()
    assert "not authenticated" in str(exc.value).lower()


def test_graphql_auth_error_in_errors_array(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"errors": [{"message": "Unauthorized session"}]}),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "auth login --force" in str(exc.value)


def test_graphql_generic_error_surfaces(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"errors": [{"message": "Bad request"}]}),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "GraphQL error" in str(exc.value)


def test_get_feed_normalizes_items(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(
            json_body={
                "data": {
                    "me": {
                        "personalizedFeed": {
                            "feedItems": [
                                {"feedItemType": "POST", "contentId": 1, "post": {"subject": "Hi"}}
                            ]
                        }
                    }
                }
            }
        ),
    )
    rows = client.get_feed(limit=5)
    assert rows == [{"id": 1, "type": "POST", "title": "Hi"}]


def test_get_me_raises_on_empty_user(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": {"user": None}}}),
    )
    with pytest.raises(ClientError) as exc:
        client.get_me()
    assert "logged out" in str(exc.value).lower()


def test_get_me_raises_auth_error_on_null_me(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": None}}),
    )
    # data.me == null is the unauthenticated signal — surfaced as a clear,
    # actionable auth error before required_path is reached.
    with pytest.raises(ClientError) as exc:
        client.get_me()
    assert "not authenticated" in str(exc.value).lower()


def test_get_notifications_normalizes_records(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(
            json_body={
                "data": {
                    "me": {
                        "shortcuts": [
                            {"type": "events", "title": "Events", "badges": 3, "__typename": "Shortcut"}
                        ]
                    }
                }
            }
        ),
    )
    rows = client.get_notifications()
    assert rows == [{"id": "events", "label": "Events", "badges": 3}]


def test_optional_list_rejects_non_list(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(
            json_body={"data": {"me": {"personalizedFeed": {"feedItems": "oops"}}}}
        ),
    )
    with pytest.raises(ClientError) as exc:
        client.get_feed()
    assert "list" in str(exc.value).lower()


def test_search_normalizes_suggestions(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(
            json_body={"data": {"dynamicSearchBarSuggestions": ["Gardeners", "Plumber"]}}
        ),
    )
    rows = client.search("garden")
    assert rows == [{"suggestion": "Gardeners"}, {"suggestion": "Plumber"}]


# ---- Retry wiring (shared RequestsRetryPolicy) ------------------------------


def _zero_delay_policy(max_retries=2):
    """A policy that retries without ever sleeping for a measurable time."""
    return RequestsRetryPolicy(max_retries=max_retries, base_delay=0, max_delay=0, jitter=0)


def test_request_retries_retryable_status_then_succeeds(monkeypatch):
    client = _make_client(monkeypatch)
    client._retry_policy = _zero_delay_policy()

    responses = [
        _FakeResponse(status_code=503),
        _FakeResponse(json_body={"data": {"me": {"user": {"id": "u1"}}}}),
    ]
    calls = {"n": 0}

    def fake_request(method, url, json=None):
        calls["n"] += 1
        return responses.pop(0)

    monkeypatch.setattr(client.session, "request", fake_request)

    data = client._graphql("getMe")

    assert calls["n"] == 2  # retried once after the 503
    assert data == {"me": {"user": {"id": "u1"}}}


def test_request_wraps_persistent_network_error(monkeypatch):
    client = _make_client(monkeypatch)
    client._retry_policy = _zero_delay_policy(max_retries=1)

    def fake_request(method, url, json=None):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "Nextdoor request failed after retries" in str(exc.value)
