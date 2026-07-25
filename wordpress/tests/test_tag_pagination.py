"""Tests for WordPress tag list pagination.

The adamtheautomator.com origin issues a canonical 301 redirect that strips the
query string from any REST request carrying query parameters, which silently
collapses every paginated request back to the default first page. The client
works around this by sending GET query parameters in a JSON body via
``X-HTTP-Method-Override: GET``. These tests pin that behavior and prove the
client walks every page of a multi-page tag response.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from requests.auth import HTTPBasicAuth

from wordpress_cli.client import WordPressClient


def _make_client() -> WordPressClient:
    """Build a client without touching real config/credentials."""
    client = WordPressClient.__new__(WordPressClient)
    client.base_url = "https://example.com/wp-json/wp/v2"
    client.auth = HTTPBasicAuth("user", "pass")
    client.headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "test",
    }
    client.max_retries = 0
    client.base_delay = 0
    client.max_delay = 0
    client.jitter = 0
    return client


class _FakeResponse:
    def __init__(self, payload, headers):
        self._payload = payload
        self.headers = headers
        self.status_code = 200
        self.ok = True

    def json(self):
        return self._payload


def _paginating_server(all_tags):
    """Return a requests.request replacement that mimics the query-stripping origin.

    Pagination parameters are only honored when they arrive in the JSON body
    (the X-HTTP-Method-Override path). If a query string is present at all, the
    server returns just the default first page, mirroring the real redirect bug.
    """

    def fake_request(*, method, url, headers, json=None, params=None, auth=None, **kwargs):
        # A real request with query params is 301-stripped to the default page.
        if params:
            page_items = all_tags[:10]
            total_pages = (len(all_tags) + 9) // 10
            return _FakeResponse(page_items, {"x-wp-totalpages": str(total_pages)})

        body = json or {}
        per_page = int(body.get("per_page", 10))
        page = int(body.get("page", 1))
        start = (page - 1) * per_page
        page_items = all_tags[start:start + per_page]
        total_pages = (len(all_tags) + per_page - 1) // per_page
        return _FakeResponse(page_items, {"x-wp-totalpages": str(total_pages)})

    return fake_request


def _tag(idx):
    return {"id": idx, "name": f"Tag{idx}", "slug": f"tag{idx}", "count": 0}


def test_list_tags_collects_every_page():
    """list_tags walks all pages and returns the full tag set, not just page 1."""
    client = _make_client()
    all_tags = [_tag(i) for i in range(1, 251)]  # 250 tags -> 3 pages at per_page=100

    fake = _paginating_server(all_tags)
    with patch("wordpress_cli.client.requests.request", side_effect=fake) as mock_request:
        tags = client.list_tags(limit=1000)

    names = [t.name for t in tags]
    assert len(tags) == 250
    assert names[0] == "Tag1"
    assert names[-1] == "Tag250"
    assert "Tag104" in names  # a tag that lives past the first page
    # 250 tags at per_page=100 => 3 pages => 3 HTTP calls.
    assert mock_request.call_count == 3


def test_list_tags_uses_method_override_body_not_query():
    """Pagination params travel in the JSON body via X-HTTP-Method-Override, never the query."""
    client = _make_client()
    all_tags = [_tag(i) for i in range(1, 151)]  # 150 tags -> 2 pages

    fake = MagicMock(side_effect=_paginating_server(all_tags))
    with patch("wordpress_cli.client.requests.request", fake):
        tags = client.list_tags(limit=1000)

    assert len(tags) == 150
    for call in fake.call_args_list:
        kwargs = call.kwargs
        assert kwargs["method"] == "POST"
        assert kwargs["headers"]["X-HTTP-Method-Override"] == "GET"
        assert not kwargs.get("params")  # no query string
        # Full pages are always requested so the server offset stays aligned.
        assert kwargs["json"]["per_page"] == 100
        assert "page" in kwargs["json"]


def test_list_tags_respects_limit_across_pages():
    """--limit caps the total returned even when more pages exist."""
    client = _make_client()
    all_tags = [_tag(i) for i in range(1, 501)]  # 500 tags available

    fake = _paginating_server(all_tags)
    with patch("wordpress_cli.client.requests.request", side_effect=fake):
        tags = client.list_tags(limit=120)  # spans 2 pages at per_page=100

    assert len(tags) == 120
    assert tags[0].name == "Tag1"
    assert tags[-1].name == "Tag120"


def test_get_request_without_params_stays_a_get():
    """A GET with no query params is left untouched (no override, no body)."""
    client = _make_client()

    fake = MagicMock(return_value=_FakeResponse([{"ok": True}], {}))
    with patch("wordpress_cli.client.requests.request", fake):
        client._make_request("GET", "/tags")

    kwargs = fake.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert "X-HTTP-Method-Override" not in kwargs["headers"]
