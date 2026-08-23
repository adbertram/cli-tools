"""Tests for WordPress list pagination alignment.

WordPress computes the result offset for a paginated REST request as
``(page - 1) * per_page``. The list_* helpers previously shrank ``per_page`` on
the final page (``min(remaining, 100)``), which moved the offset to an earlier
window and returned DUPLICATE rows whenever the requested limit was not a
multiple of 100. These tests pin the fix: every page is fetched at a fixed
``per_page=100`` and the result is trimmed to the caller's limit, so the offset
stays aligned and the returned rows are unique.

The fake server also reproduces the adamtheautomator.com origin bug where a real
query string is 301-stripped back to the default first page, so pagination only
works through the ``X-HTTP-Method-Override: GET`` JSON-body path.
"""

from __future__ import annotations

from unittest.mock import patch

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


def _paginating_server(all_rows):
    """Return a requests.request replacement that honors the (page-1)*per_page offset.

    Pagination parameters are only honored when they arrive in the JSON body
    (the X-HTTP-Method-Override path). If a query string is present at all, the
    server returns just the default first page, mirroring the real redirect bug.
    """

    def fake_request(*, method, url, headers, json=None, params=None, auth=None, **kwargs):
        if params:
            page_items = all_rows[:10]
            total_pages = (len(all_rows) + 9) // 10
            return _FakeResponse(page_items, {"x-wp-totalpages": str(total_pages)})

        body = json or {}
        per_page = int(body.get("per_page", 10))
        page = int(body.get("page", 1))
        start = (page - 1) * per_page
        page_items = all_rows[start:start + per_page]
        total_pages = (len(all_rows) + per_page - 1) // per_page
        return _FakeResponse(page_items, {"x-wp-totalpages": str(total_pages)})

    return fake_request


def _post(idx):
    return {
        "id": idx,
        "title": {"rendered": f"Post{idx}"},
        "slug": f"post{idx}",
        "status": "publish",
        "link": f"https://example.com/post{idx}",
        "date": "2026-01-01T00:00:00",
    }


def _media(idx):
    return {
        "id": idx,
        "title": {"rendered": f"Media{idx}"},
        "slug": f"media{idx}",
        "source_url": f"https://example.com/media{idx}.png",
        "media_type": "image",
        "mime_type": "image/png",
        "date": "2026-01-01T00:00:00",
    }


def test_list_posts_non_multiple_limit_has_no_duplicates():
    """A limit that is not a multiple of 100 must return unique rows, not repeats."""
    client = _make_client()
    all_posts = [_post(i) for i in range(1, 501)]  # 500 posts available

    fake = _paginating_server(all_posts)
    with patch("wordpress_cli.client.requests.request", side_effect=fake):
        posts = client.list_posts(limit=120)  # spans 2 pages at per_page=100

    ids = [p.id for p in posts]
    assert len(posts) == 120
    assert len(set(ids)) == 120  # every row unique, no offset-misalignment duplicates
    assert ids[0] == 1
    assert ids[-1] == 120


def test_list_posts_collects_every_page():
    """list_posts walks all pages and returns the full set, not just page 1."""
    client = _make_client()
    all_posts = [_post(i) for i in range(1, 251)]  # 250 posts -> 3 pages at per_page=100

    fake = _paginating_server(all_posts)
    with patch("wordpress_cli.client.requests.request", side_effect=fake) as mock_request:
        posts = client.list_posts(limit=1000)

    ids = [p.id for p in posts]
    assert len(posts) == 250
    assert len(set(ids)) == 250
    assert ids[0] == 1
    assert ids[-1] == 250
    assert mock_request.call_count == 3


def test_list_posts_pagination_uses_full_pages():
    """Every page requests per_page=100 so the server offset stays aligned."""
    client = _make_client()
    all_posts = [_post(i) for i in range(1, 501)]

    calls = []

    def recording(*args, **kwargs):
        calls.append(kwargs)
        return _paginating_server(all_posts)(*args, **kwargs)

    with patch("wordpress_cli.client.requests.request", side_effect=recording):
        client.list_posts(limit=120)

    for kwargs in calls:
        assert kwargs["method"] == "POST"
        assert kwargs["headers"]["X-HTTP-Method-Override"] == "GET"
        assert not kwargs.get("params")
        assert kwargs["json"]["per_page"] == 100


def test_list_media_non_multiple_limit_has_no_duplicates():
    """list_media with a non-multiple-of-100 limit returns unique rows."""
    client = _make_client()
    all_media = [_media(i) for i in range(1, 501)]

    fake = _paginating_server(all_media)
    with patch("wordpress_cli.client.requests.request", side_effect=fake):
        media = client.list_media(limit=150)

    ids = [m.id for m in media]
    assert len(media) == 150
    assert len(set(ids)) == 150
    assert ids[0] == 1
    assert ids[-1] == 150
