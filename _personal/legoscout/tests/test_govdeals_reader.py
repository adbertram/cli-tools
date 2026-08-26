"""Contract tests for the browser-only GovDeals source reader."""
from __future__ import annotations

import pytest

from legoscout_cli.sources import listing, readers
from legoscout_cli.sources.readers import govdeals


@pytest.fixture
def govdeals_asset():
    """A recorded public GovDeals asset URL with both URL key segments."""
    return {
        "listing_key": govdeals.listing_key("10017", "5859"),
        "direct_url": "https://prod-seo.govdeals.com/en/asset/10017/5859",
    }


def test_listing_key_preserves_both_ordered_asset_url_segments():
    assert govdeals.listing_key("10017", "5859") == "govdeals|10017/5859"


@pytest.mark.parametrize("asset_id, opaque_id", [
    ("", "5859"),
    ("10017", ""),
    ("10017/5859", "asset"),
    ("10017", "58|59"),
])
def test_listing_key_refuses_incomplete_or_ambiguous_segments(asset_id, opaque_id):
    with pytest.raises(ValueError, match="URL segments"):
        govdeals.listing_key(asset_id, opaque_id)


def test_module_dispatches_for_the_complete_direct_url_key(govdeals_asset):
    key_suffix = govdeals_asset["listing_key"].split("|", 1)[1]

    assert readers.module_for(govdeals_asset["listing_key"]) is govdeals
    assert govdeals_asset["direct_url"].endswith("/" + key_suffix)


@pytest.mark.parametrize(
    "field, required_surface",
    [
        ("available_fulfillment", "delivery options"),
        ("item_location", "Item Location label"),
        ("auction_end_date", "close date and time"),
        ("seller_id", "Seller label"),
        ("seller_name", "Seller label"),
    ],
)
def test_browser_only_fields_name_the_live_page_surface(
        govdeals_asset, field, required_surface):
    where = readers.where(govdeals_asset["listing_key"], field)

    assert required_surface in where
    assert "Runtime browser" in where
    with pytest.raises(listing.Undetermined, match="govdeals"):
        readers.read(govdeals_asset, field)


def test_shipping_is_unquoted_not_a_zero_dollar_fallback(govdeals_asset):
    estimate, evidence = readers.read(govdeals_asset, "shipping_estimate")

    assert estimate["status"] == "unquoted"
    assert estimate["reason"] == evidence
    assert "destination shipping quote" in evidence
    assert "0.0" in evidence
