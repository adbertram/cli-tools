"""Tests for resumable, paced multi-page crawls against the storefront.

The storefront rate-limits bursts (HTTP 429 `local_rate_limited`), so a
full-catalog crawl must (a) persist each page as it arrives, (b) resume from the
first uncached page on the next run, (c) pace consecutive live requests via
`--page-delay`, and (d) fail with an actionable message and a non-zero exit when
the rate limit is terminal.

All HTTP is mocked; nothing here touches the live storefront.
"""

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from americasthriftsupply_cli import client as client_module
from americasthriftsupply_cli import main
from americasthriftsupply_cli.client import (
    PAGE_SIZE,
    AmericasthriftsupplyClient,
    PagedCrawlError,
)
from cli_tools_shared.exceptions import ClientError


runner = CliRunner()

BASE_URL = "https://example.test"


def _product(index: int) -> dict:
    """A minimal /products.json record with the fields normalize_product reads."""
    return {
        "id": index,
        "handle": f"p{index}",
        "title": f"Product {index}",
        "created_at": f"2026-01-01T00:00:{index:02d}",
        "variants": [{"price": "10.00", "available": True}],
        "images": [],
    }


def _full_page(start: int) -> list:
    return [_product(start + offset) for offset in range(PAGE_SIZE)]


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {}
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeStorefront:
    """Records every HTTP request and serves scripted page responses."""

    def __init__(self, pages: dict, rate_limited_pages=()):
        self.pages = pages
        self.rate_limited_pages = set(rate_limited_pages)
        self.requested_pages = []

    def __call__(self, method, url, headers=None, params=None, timeout=None):
        page = params["page"]
        self.requested_pages.append(page)
        if page in self.rate_limited_pages:
            return _FakeResponse(429, {"errors": "local_rate_limited"})
        return _FakeResponse(200, {"products": self.pages[page]})


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    """Isolated cache dir + caching enabled, so tests never touch the real profile."""
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("CACHE_TTL", "3600")
    return SimpleNamespace(base_url=BASE_URL, storage_dir=tmp_path)


@pytest.fixture
def sleeps(monkeypatch):
    """Capture every sleep the client performs (paging pace and retry backoff)."""
    recorded = []
    monkeypatch.setattr(client_module.time, "sleep", recorded.append)
    return recorded


def _client(config, **kwargs):
    return AmericasthriftsupplyClient(config=config, **kwargs)


def _cache_files(tmp_path):
    return sorted(path.name for path in (tmp_path / "cache").glob("_fetch_page_*.json"))


# --- page-level cache persistence ---------------------------------------------


def test_each_fetched_page_is_cached_on_success(cache_env, tmp_path, sleeps, monkeypatch):
    """A two-page crawl writes one cache file per page, not one per crawl."""
    storefront = _FakeStorefront({1: _full_page(1), 2: [_product(999)]})
    monkeypatch.setattr(client_module.requests, "request", storefront)

    rows = _client(cache_env).list_products(limit=PAGE_SIZE + 1, page_delay=0)

    assert len(rows) == PAGE_SIZE + 1
    assert storefront.requested_pages == [1, 2]
    assert len(_cache_files(tmp_path)) == 2


def test_partial_crawl_persists_the_pages_that_succeeded(cache_env, tmp_path, sleeps, monkeypatch):
    """Page 1 survives on disk even though the crawl died on page 2."""
    storefront = _FakeStorefront({1: _full_page(1)}, rate_limited_pages=[2])
    monkeypatch.setattr(client_module.requests, "request", storefront)

    with pytest.raises(PagedCrawlError):
        _client(cache_env, max_retries=0).list_products(limit=PAGE_SIZE * 3, page_delay=0)

    assert len(_cache_files(tmp_path)) == 1


# --- resume from cache on re-run ----------------------------------------------


def test_rerun_resumes_from_first_uncached_page(cache_env, tmp_path, sleeps, monkeypatch):
    """The second run serves page 1 from cache and only requests page 2."""
    first = _FakeStorefront({1: _full_page(1)}, rate_limited_pages=[2])
    monkeypatch.setattr(client_module.requests, "request", first)
    with pytest.raises(PagedCrawlError):
        _client(cache_env, max_retries=0).list_products(limit=PAGE_SIZE * 3, page_delay=0)
    assert first.requested_pages == [1, 2]

    second = _FakeStorefront({2: [_product(999)]})
    monkeypatch.setattr(client_module.requests, "request", second)
    rows = _client(cache_env).list_products(limit=PAGE_SIZE * 3, page_delay=0)

    # Page 1 was never re-requested; the crawl picked up at page 2.
    assert second.requested_pages == [2]
    assert len(rows) == PAGE_SIZE + 1
    assert rows[0]["id"] == 1
    assert rows[-1]["id"] == 999


def test_cached_page_is_reused_across_different_limits(cache_env, tmp_path, sleeps, monkeypatch):
    """Page size is fixed, so a page cached by one --limit serves another."""
    storefront = _FakeStorefront({1: _full_page(1)})
    monkeypatch.setattr(client_module.requests, "request", storefront)

    _client(cache_env).list_products(limit=5, page_delay=0)
    _client(cache_env).list_products(limit=50, page_delay=0)

    assert storefront.requested_pages == [1]


# --- --page-delay pacing -------------------------------------------------------


def test_page_delay_is_slept_between_live_pages(cache_env, sleeps, monkeypatch):
    """Three live pages sleep the configured delay twice - never before page 1."""
    storefront = _FakeStorefront({1: _full_page(1), 2: _full_page(1000), 3: [_product(9999)]})
    monkeypatch.setattr(client_module.requests, "request", storefront)

    _client(cache_env).list_products(limit=PAGE_SIZE * 3, page_delay=7.5)

    assert storefront.requested_pages == [1, 2, 3]
    assert sleeps == [7.5, 7.5]


def test_no_page_delay_for_single_page_request(cache_env, sleeps, monkeypatch):
    storefront = _FakeStorefront({1: [_product(1)]})
    monkeypatch.setattr(client_module.requests, "request", storefront)

    _client(cache_env).list_products(limit=10, page_delay=30.0)

    assert sleeps == []


def test_cached_pages_do_not_incur_page_delay(cache_env, sleeps, monkeypatch):
    """Resuming does not pay the pace for pages served from disk."""
    storefront = _FakeStorefront({1: _full_page(1), 2: [_product(999)]})
    monkeypatch.setattr(client_module.requests, "request", storefront)
    _client(cache_env).list_products(limit=PAGE_SIZE * 2, page_delay=0)
    sleeps.clear()

    _client(cache_env).list_products(limit=PAGE_SIZE * 2, page_delay=45.0)

    assert sleeps == []


def test_page_delay_reaches_the_client_from_the_command(monkeypatch):
    captured = {}

    class _Recorder:
        def list_products(self, limit, collection, page_delay):
            captured["page_delay"] = page_delay
            return []

    monkeypatch.setattr(main, "get_client", lambda: _Recorder())
    result = runner.invoke(main.products_app, ["list", "--page-delay", "12.5"])

    assert result.exit_code == 0
    assert captured["page_delay"] == 12.5


def test_page_delay_default_is_the_documented_constant(monkeypatch):
    captured = {}

    class _Recorder:
        def list_products(self, limit, collection, page_delay):
            captured["page_delay"] = page_delay
            return []

    monkeypatch.setattr(main, "get_client", lambda: _Recorder())
    result = runner.invoke(main.products_app, ["list"])

    assert result.exit_code == 0
    assert captured["page_delay"] == client_module.DEFAULT_PAGE_DELAY


def test_negative_page_delay_is_rejected(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: pytest.fail("client must not be called"))
    result = runner.invoke(main.products_app, ["list", "--page-delay", "-1"])
    assert result.exit_code != 0


# --- informative terminal 429 --------------------------------------------------


def test_rate_limit_exhaustion_message_reports_progress_and_resume(cache_env, tmp_path, sleeps, monkeypatch):
    storefront = _FakeStorefront({1: _full_page(1), 2: _full_page(1000)}, rate_limited_pages=[3])
    monkeypatch.setattr(client_module.requests, "request", storefront)

    with pytest.raises(PagedCrawlError) as exc:
        _client(cache_env, max_retries=0).list_products(limit=PAGE_SIZE * 4, page_delay=5.0)

    message = str(exc.value)
    assert "local_rate_limited" in message
    assert "stopped after 2 page(s)" in message
    assert f"yielding {PAGE_SIZE * 2} products" in message
    assert str(tmp_path / "cache") in message
    assert "resume from page 3" in message
    assert "--page-delay 30" in message
    assert "current: 5s" in message
    assert "cache clear" in message


def test_rate_limit_message_states_when_nothing_was_persisted(cache_env, sleeps, monkeypatch):
    """With caching off, the message must not claim the pages are resumable."""
    monkeypatch.setenv("CACHE_ENABLED", "false")
    storefront = _FakeStorefront({1: _full_page(1)}, rate_limited_pages=[2])
    monkeypatch.setattr(client_module.requests, "request", storefront)

    with pytest.raises(PagedCrawlError) as exc:
        _client(cache_env, max_retries=0).list_products(limit=PAGE_SIZE * 2, page_delay=0)

    message = str(exc.value)
    assert "Response caching is disabled" in message
    assert "restarts at page 1" in message
    assert "resume from page" not in message


def test_products_list_exits_nonzero_with_the_message_on_stderr(monkeypatch):
    """Terminal rate limit stays fail-fast: exit 1, explanation on stderr, no data."""
    failure = PagedCrawlError(
        cause=ClientError("HTTP 429: local_rate_limited"),
        endpoint="/products.json",
        resource="products",
        pages_fetched=7,
        items_fetched=1750,
        page_delay=5.0,
        cache_dir="/tmp/cache",
        cache_enabled=True,
    )

    class _FailingClient:
        def list_products(self, limit, collection, page_delay):
            raise failure

    monkeypatch.setattr(main, "get_client", lambda: _FailingClient())
    result = runner.invoke(main.products_app, ["list"], catch_exceptions=False)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "local_rate_limited" in result.stderr
    assert "stopped after 7 page(s) yielding 1750 products" in result.stderr
    assert "/tmp/cache" in result.stderr
    assert "resume from page 8" in result.stderr
    assert "--page-delay 30" in result.stderr


def test_collections_list_shares_the_crawl_path(cache_env, sleeps, monkeypatch):
    """collections list is paced and page-cached by the same paginator."""
    calls = []

    def fake_request(method, url, headers=None, params=None, timeout=None):
        calls.append(params["page"])
        if params["page"] == 1:
            return _FakeResponse(200, {"collections": [{"id": i, "handle": f"c{i}"} for i in range(PAGE_SIZE)]})
        return _FakeResponse(200, {"collections": [{"id": 999, "handle": "c999"}]})

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    rows = _client(cache_env).list_collections(limit=PAGE_SIZE * 2, page_delay=3.0)

    assert calls == [1, 2]
    assert sleeps == [3.0]
    assert len(rows) == PAGE_SIZE + 1


def test_unexpected_response_shape_fails_fast(cache_env, sleeps, monkeypatch):
    def fake_request(method, url, headers=None, params=None, timeout=None):
        return _FakeResponse(200, {"unexpected": []})

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    with pytest.raises(ClientError, match="missing 'products'"):
        _client(cache_env).list_products(limit=10, page_delay=0)
