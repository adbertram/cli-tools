"""Tests for ``AirtableClient.list_records`` pagination and offset exposure.

The offset is the only signal a caller has that more records exist beyond the
current batch. It must be exposed whenever the underlying Airtable response
carries one, including when the requested ``limit`` lands exactly on a page
boundary. A regression here silently drops every record past the boundary when
callers resume page-by-page (the coursecraft list 100-cap bug).
"""

from airtable_cli.client import AirtableClient


def _client() -> AirtableClient:
    client = AirtableClient.__new__(AirtableClient)
    client.base_url = "https://api.airtable.test/v0"
    client.headers = {"Authorization": "Bearer test"}
    return client


def _records(count: int, start: int = 0):
    return [{"id": f"rec{start + i:04d}", "fields": {"n": start + i}} for i in range(count)]


def test_single_page_limit_still_exposes_offset_when_more_exist(monkeypatch):
    """limit==page size: the upstream offset must survive (exact-boundary bug)."""
    client = _client()

    def fake_make_request(method, endpoint, params=None):
        # One full page of 100, and Airtable reports more after it.
        return {"records": _records(100), "offset": "OFFSET_NEXT"}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    response = client.list_records("appBase", "Tasks", limit=100)

    assert len(response["records"]) == 100
    # The caller asked for 100 and got 100, but Airtable has more -> the offset
    # MUST be returned so a page-by-page caller can continue.
    assert response["offset"] == "OFFSET_NEXT"


def test_natural_end_does_not_expose_offset(monkeypatch):
    """A short final page (no upstream offset) must not advertise more pages."""
    client = _client()

    def fake_make_request(method, endpoint, params=None):
        # Fewer than a full page and no offset -> this is the end of the data.
        return {"records": _records(42)}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    response = client.list_records("appBase", "Tasks", limit=100)

    assert len(response["records"]) == 42
    assert "offset" not in response


def test_internal_pagination_accumulates_pages_up_to_limit(monkeypatch):
    """A large limit follows the offset internally and accumulates every page."""
    client = _client()
    pages = [
        {"records": _records(100, start=0), "offset": "PAGE2"},
        {"records": _records(100, start=100), "offset": "PAGE3"},
        {"records": _records(71, start=200)},  # final short page, no offset
    ]
    calls = {"i": 0}

    def fake_make_request(method, endpoint, params=None):
        page = pages[calls["i"]]
        calls["i"] += 1
        return page

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    response = client.list_records("appBase", "Tasks", limit=1000)

    assert len(response["records"]) == 271
    assert "offset" not in response
    assert calls["i"] == 3
