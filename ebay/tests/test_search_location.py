"""Tests for the United States item-location search filter."""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from typer.testing import CliRunner

from ebay_cli.browser_client import EbayBrowserClient
from ebay_cli.commands import search as search_commands
from ebay_cli.main import app


class _SearchResult:
    def to_dict(self) -> dict:
        return {"item_id": "123", "title": "LEGO set"}


class _RecordingSearchClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def search_active(self, **kwargs):
        self.calls.append(("active", kwargs))
        return [_SearchResult()]

    def search_completed(self, **kwargs):
        self.calls.append(("completed", kwargs))
        return [_SearchResult()]

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("active", [False, True])
def test_build_search_url_should_add_us_location_filter_for_each_search_mode(active):
    client = EbayBrowserClient(config=object())

    query = parse_qs(
        urlparse(
            client._build_search_url(
                keywords="lego",
                active=active,
                us_only=True,
            )
        ).query
    )

    assert query["LH_PrefLoc"] == ["1"]


@pytest.mark.parametrize(
    ("mode_args", "expected_mode", "mode_kwargs"),
    [
        ([], "completed", {"sold_only": False, "sop": "13"}),
        (["--active"], "active", {"listing_format": None, "sop": "10"}),
    ],
)
def test_listings_search_command_should_propagate_us_only_through_cli(
    monkeypatch, mode_args, expected_mode, mode_kwargs
):
    client = _RecordingSearchClient()
    monkeypatch.setattr(
        search_commands,
        "get_browser_client",
        lambda profile=None: client,
    )

    result = CliRunner().invoke(
        app,
        ["listings", "search", "lego", "--us-only", "--limit", "1", *mode_args],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"item_id": "123", "title": "LEGO set"}]
    expected_kwargs = {
        "keywords": "lego",
        "min_price": None,
        "max_price": None,
        "category": None,
        "condition": None,
        "us_only": True,
        "limit": 1,
    }
    expected_kwargs.update(mode_kwargs)
    assert client.calls == [(expected_mode, expected_kwargs)]
    assert client.closed is True
