"""Regression tests for ITEM_DETAIL_JS page-state detection.

These run the real extractor JS against synthetic ``/itm/<id>`` markup, so the
banner regexes are covered rather than only the Python parser that consumes
their output.
"""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from ebay_cli.browser_client import ITEM_DETAIL_JS, parse_item_status


def _item_page_state(body_html: str) -> dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(f"<html><body>{body_html}</body></html>")
        state = page.evaluate(ITEM_DETAIL_JS)
        browser.close()
    return state


# Banner text captured from live /itm pages. The first is the one that used to
# be missed: a sold Buy It Now listing never says "ended" anywhere.
ENDED_BANNERS = [
    "This listing sold on Sun, Jul 26 at 5:47 PM.",
    "This listing was ended by the seller because the item is no longer available.",
    "This listing has ended.",
    "Bidding has ended on this item.",
    "This auction ended on Jul 26, 2026.",
]


@pytest.mark.parametrize("banner", ENDED_BANNERS)
def test_ended_banner_detects_every_end_of_listing_wording(banner):
    state = _item_page_state(f"<div>{banner}</div><h1>LEGO Mixed Bag Of Floral Parts</h1>")
    assert state["ended_banner"] is True


def test_live_listing_is_not_flagged_as_ended():
    """A live listing that merely reports past sales must stay active."""
    state = _item_page_state(
        """
        <h1 class="x-item-title__mainTitle"><span class="ux-textspans">LEGO Technic Panel</span></h1>
        <div class="x-price-primary"><span class="ux-textspans">US $2.95</span></div>
        <div class="x-quantity__availability"><span class="ux-textspans">5 available / 12 sold</span></div>
        """
    )
    assert state["ended_banner"] is False


def test_captured_item_jsonld_reaches_the_status_parser():
    """Item 137582327361 explicitly reports InStock without a quantity row."""
    fixture = Path(__file__).parent / "fixtures" / "item_137582327361_jsonld.html"
    url = "https://www.ebay.com/itm/137582327361?orig_cvip=true"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body=fixture.read_text(), content_type="text/html"))
            page.goto(url)
            state = page.evaluate(ITEM_DETAIL_JS)
        finally:
            browser.close()
    assert state["quantity"] is None
    assert state["ended_banner"] is False
    assert len(state["jsonld"]) == 2
    status = parse_item_status("137582327361", state)
    assert status["availability"] == "InStock"
    assert status["ended"] is False
