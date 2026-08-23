"""Regression tests for ITEM_DETAIL_JS page-state detection.

These run the real extractor JS against synthetic ``/itm/<id>`` markup, so the
banner regexes are covered rather than only the Python parser that consumes
their output.
"""

import pytest
from playwright.sync_api import sync_playwright

from ebay_cli.browser_client import ITEM_DETAIL_JS


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
