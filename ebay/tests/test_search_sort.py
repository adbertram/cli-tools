"""Offline tests for the Source-CLI Sort Standard on `ebay listings search`.

These never hit eBay: they exercise the canonical ``--sort``/``--desc`` ->
``_sop`` mapping, the fail-fast reject paths, and the search-URL construction.
"""
import pytest
from typer.testing import CliRunner

from ebay_cli.browser_client import EbayBrowserClient, resolve_sop
from ebay_cli.main import app


# -- resolve_sop: canonical (field, desc) -> eBay _sop code --

def test_resolve_sop_maps_canonical_sorts():
    # newest (default) -> "ended recently" for completed comps (recency exception).
    assert resolve_sop("newest", False) == "13"
    # price low->high natural, high->low with --desc.
    assert resolve_sop("price", False) == "15"
    assert resolve_sop("price", True) == "16"
    # ending -> ending soonest.
    assert resolve_sop("ending", False) == "1"


def test_resolve_sop_is_case_insensitive():
    assert resolve_sop("NEWEST", False) == "13"
    assert resolve_sop("Price", True) == "16"


def test_resolve_sop_rejects_unknown_sort():
    with pytest.raises(ValueError, match="Invalid --sort 'bogus'"):
        resolve_sop("bogus", False)
    # The error must list the valid values so callers can self-correct.
    with pytest.raises(ValueError, match="newest, price, ending"):
        resolve_sop("relevance", False)


def test_resolve_sop_rejects_unsupported_desc_directions():
    # eBay completed-listing search has no descending twin for these fields;
    # reject rather than silently reordering.
    with pytest.raises(ValueError, match="no descending order for --sort newest"):
        resolve_sop("newest", True)
    with pytest.raises(ValueError, match="no descending order for --sort ending"):
        resolve_sop("ending", True)


def test_resolve_sop_active_maps_newest_to_newly_listed():
    # For ACTIVE listings, `newest` means eBay's true "newly listed" order.
    assert resolve_sop("newest", False, active=True) == "10"
    assert resolve_sop("ending", False, active=True) == "1"
    assert resolve_sop("price", False, active=True) == "15"
    assert resolve_sop("price", True, active=True) == "16"


def test_resolve_sop_active_rejects_unsupported_desc():
    with pytest.raises(ValueError, match="active-listing search has no descending order"):
        resolve_sop("newest", True, active=True)


# -- _build_search_url: the resolved _sop is actually injected --

def test_build_search_url_injects_sop_and_keeps_completed_filter():
    # Pass a truthy dummy config so __init__ does not read real credentials.
    client = EbayBrowserClient(config=object())

    default_url = client._build_search_url(keywords="LEGO 75357", sop="13")
    assert "_sop=13" in default_url
    assert "LH_Complete=1" in default_url
    assert "_nkw=LEGO+75357" in default_url

    price_low = client._build_search_url(keywords="LEGO 75357", sop="15")
    assert "_sop=15" in price_low

    price_high = client._build_search_url(keywords="LEGO 75357", sop="16")
    assert "_sop=16" in price_high


def test_build_search_url_default_sop_is_ended_recently():
    client = EbayBrowserClient(config=object())
    # The default argument encodes the canonical `newest` sort for comps.
    assert "_sop=13" in client._build_search_url(keywords="anything")


def test_build_search_url_active_drops_completed_and_sets_format():
    client = EbayBrowserClient(config=object())

    # Active search must NOT constrain to completed listings.
    active_all = client._build_search_url(keywords="LEGO bulk", active=True, sop="10")
    assert "_sop=10" in active_all
    assert "LH_Complete" not in active_all
    assert "LH_Sold" not in active_all
    assert "LH_BIN" not in active_all
    assert "LH_Auction" not in active_all

    bin_only = client._build_search_url(
        keywords="LEGO bulk", active=True, listing_format="bin", sop="10"
    )
    assert "LH_BIN=1" in bin_only
    assert "LH_Complete" not in bin_only

    auction_only = client._build_search_url(
        keywords="LEGO bulk", active=True, listing_format="auction", sop="1"
    )
    assert "LH_Auction=1" in auction_only
    assert "LH_BIN" not in auction_only


# -- CLI surface: fail-fast reject paths exit non-zero before any browser work --

def test_listings_search_rejects_unknown_sort_value():
    result = CliRunner().invoke(app, ["listings", "search", "widget", "--sort", "bogus"])
    assert result.exit_code != 0
    assert "Invalid --sort 'bogus'" in result.stderr
    assert "newest, price, ending" in result.stderr


def test_listings_search_rejects_desc_on_newest():
    result = CliRunner().invoke(
        app, ["listings", "search", "widget", "--sort", "newest", "--desc"]
    )
    assert result.exit_code != 0
    assert "no descending order for --sort newest" in result.stderr
