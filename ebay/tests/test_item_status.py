"""Tests for the fulfillment-independent eBay item status path."""

import json

import pytest
from typer.testing import CliRunner

from ebay_cli.browser_client import (
    BrowserError,
    EbayBrowserClient,
    parse_item_detail,
    parse_item_status,
)
from ebay_cli.commands import search as search_commands
from ebay_cli.main import app


def _page_state(availability: str | None = "https://schema.org/InStock") -> dict:
    offer = {"@type": "Offer"}
    if availability is not None:
        offer["availability"] = availability
    return {
        "url": "https://www.ebay.com/itm/336724048050",
        "doc_title": "LEGO item | eBay",
        "dom_title": None,
        "pickup_dom": None,
        "shipping_values_dom": None,
        "quantity": None,
        "ended_banner": False,
        "error_page": False,
        "captcha": False,
        "jsonld": [
            {
                "@type": "Product",
                "name": "LEGO item",
                "offers": offer,
            }
        ],
    }


def test_status_reads_in_stock_without_fulfillment_rows():
    status = parse_item_status("336724048050", _page_state())

    assert status == {
        "item_id": "336724048050",
        "availability": "InStock",
        "ended": False,
        "url": "https://www.ebay.com/itm/336724048050",
    }


def test_status_reads_sold_out_without_fulfillment_rows():
    status = parse_item_status(
        "336724048050",
        _page_state("https://schema.org/SoldOut"),
    )

    assert status["availability"] == "SoldOut"
    assert status["ended"] is True


def test_status_treats_removed_item_page_as_ended():
    state = _page_state()
    state.update({"jsonld": [], "error_page": True})

    status = parse_item_status("336724048050", state)

    assert status["availability"] is None
    assert status["ended"] is True


def test_status_fails_when_page_carries_no_availability_evidence():
    with pytest.raises(BrowserError, match="carries no availability evidence"):
        parse_item_status("336724048050", _page_state(None))


def test_status_does_not_infer_ended_from_missing_title_and_offer():
    state = _page_state()
    state.update({"jsonld": [], "dom_title": None})

    with pytest.raises(BrowserError, match="carries no availability evidence"):
        parse_item_status("336724048050", state)


def test_detail_and_status_use_distinct_item_urls():
    detail_state = _page_state()
    detail_state["shipping_values_dom"] = "Free shipping"
    status_state = _page_state(None)
    status_state["ended_banner"] = True

    class _Page:
        def __init__(self, state: dict) -> None:
            self.state = state

        def wait_for_timeout(self, _milliseconds: int) -> None:
            pass

        def evaluate(self, _script: str) -> dict:
            return self.state

    class _Browser:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_page(self, url: str) -> _Page:
            self.urls.append(url)
            state = status_state if "orig_cvip=true" in url else detail_state
            return _Page(state)

    browser = _Browser()
    client = EbayBrowserClient(config=object())
    client._browser = browser

    client.get_item("336724048050")
    status = client.get_item_status("336724048050")

    assert browser.urls == [
        "https://www.ebay.com/itm/336724048050",
        "https://www.ebay.com/itm/336724048050?orig_cvip=true",
    ]
    assert status["availability"] == "SoldOut"
    assert status["ended"] is True


def test_full_detail_still_requires_fulfillment_rows():
    with pytest.raises(BrowserError, match="neither a local-pickup nor a shipping"):
        parse_item_detail("336724048050", _page_state())


class _StatusClient:
    def __init__(self) -> None:
        self.closed = False

    def get_item_status(self, item_id: str) -> dict:
        return {
            "item_id": item_id,
            "availability": "InStock",
            "ended": False,
            "url": f"https://www.ebay.com/itm/{item_id}",
        }

    def close(self) -> None:
        self.closed = True


def test_listings_status_command_returns_json_and_closes_client(monkeypatch):
    client = _StatusClient()
    monkeypatch.setattr(
        search_commands,
        "get_browser_client",
        lambda profile=None: client,
    )

    result = CliRunner().invoke(
        app,
        ["listings", "status", "336724048050"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "item_id": "336724048050",
        "availability": "InStock",
        "ended": False,
        "url": "https://www.ebay.com/itm/336724048050",
    }
    assert client.closed is True
