"""Hermetic parser tests against real AuctionZip HTML captured live.

Fixtures under tests/fixtures/ are verbatim DOM captured from a
Cloudflare-cleared browser session during CLI creation. These tests pin the
parser contract without needing a live session.
"""

from pathlib import Path

import pytest

from auctionzip_cli.parsers import parse_lot_detail, parse_search_results

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://www.auctionzip.com"


@pytest.fixture(scope="module")
def search_html() -> str:
    return (FIXTURES / "search_lego.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def lot_html() -> str:
    return (FIXTURES / "lot_open.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def gallery_lot_html() -> str:
    """A lot that HAS photos. `lot_open.html` has none, so it cannot pin the
    gallery contract -- and a parser that returned nothing would pass against it.
    Captured live 2026-08-04 from auction-lot/unopened-lego-creator_5596A08A47.
    """
    return (FIXTURES / "lot_with_gallery.html").read_text(encoding="utf-8")


def test_search_returns_both_card_variants(search_html):
    rows = parse_search_results(search_html, BASE_URL)
    assert len(rows) == 2


def test_search_live_timed_card(search_html):
    rows = parse_search_results(search_html, BASE_URL)
    row = rows[0]
    assert row["ref"] == "9295BB0625"
    assert row["lot_number"] == "244"
    assert row["title"] == "Lego Storage Filled with Lego Sets and Instruction Books"
    assert row["auction_house"] == "Don R. Wallick Auctions"
    assert row["current_bid"] == "$21"
    assert row["current_bid_amount"] == 21.0
    assert row["bids"] == 9
    assert row["time_remaining"] == "7d 21h 1m left to bid"
    assert row["close_time"] is None
    assert row["estimate"] is None
    assert row["url"] == (
        "https://www.auctionzip.com/auction-lot/"
        "lego-storage-filled-with-lego-sets-and-instructio_9295BB0625"
    )


def test_search_scheduled_card_with_estimate(search_html):
    rows = parse_search_results(search_html, BASE_URL)
    row = rows[1]
    assert row["ref"] == "26D5CDA127"
    assert row["lot_number"] == "461"
    assert row["title"] == "Large Group of Lego Pieces"
    assert row["auction_house"] == "Matthew Bullock Auctioneers"
    assert row["current_bid_amount"] == 15.0
    assert row["bids"] == 0
    assert row["time_remaining"] is None
    assert row["close_time"] == "August 1, 2026 9:00 AM CDT"
    assert row["estimate"] == "$30 - $300"


def test_search_respects_limit(search_html):
    rows = parse_search_results(search_html, BASE_URL, limit=1)
    assert len(rows) == 1
    assert rows[0]["ref"] == "9295BB0625"


def test_lot_core_fields(lot_html):
    lot = parse_lot_detail(lot_html, url=f"{BASE_URL}/auction-lot/x_9295BB0625")
    assert lot["ref"] == "9295BB0625"
    assert lot["catalog_ref"] == "AO78ZIJK0S"
    assert lot["lot_number"] == "244"
    assert lot["title"] == "Lego Storage Filled with Lego Sets and Instruction Books"
    assert lot["auction_house"] == "Don R. Wallick Auctions"
    assert lot["currency"] == "USD"
    assert lot["url"] == f"{BASE_URL}/auction-lot/x_9295BB0625"


def test_lot_bidding_fields(lot_html):
    lot = parse_lot_detail(lot_html)
    assert lot["current_bid"] == "$17"
    assert lot["current_bid_amount"] == 17.0
    assert lot["bids"] == 8
    assert lot["next_bid"] == "$18 USD"
    assert lot["next_bid_amount"] == 18.0


def test_lot_buyer_premium(lot_html):
    lot = parse_lot_detail(lot_html)
    assert lot["buyer_premium"] == "10%"
    assert lot["buyer_premium_pct"] == 10.0
    assert "premium" in lot["conditions_of_sale"].lower()


def test_lot_status_and_timing(lot_html):
    lot = parse_lot_detail(lot_html)
    assert lot["status"] == "open"
    assert lot["auction_type"] == "Timed Auction"
    assert lot["close_time"] == "August 1, 2026 12:00 PM EDT"
    assert lot["time_remaining"] == "7d 21h 5m"


def test_lot_location_joins_address_lines(lot_html):
    lot = parse_lot_detail(lot_html)
    assert lot["location"] == "965 North Wooster Ave, Strasburg, OH, US 44680"
    assert "Antiques - Collectibles - Furniture" in lot["category"]


def test_lot_payment_and_shipping_terms(lot_html):
    lot = parse_lot_detail(lot_html)
    assert "American Express" in lot["accepted_payment"]
    assert "PICKED UP" in lot["shipping_terms"]
    assert "Pickup will be on MONDAY AUGUST 3, 2026" in lot["shipping_terms"]


def test_lot_rejects_non_lot_html():
    with pytest.raises(ValueError):
        parse_lot_detail("<html><body><p>not a lot</p></body></html>")


def test_lot_returns_its_own_gallery_at_full_size(gallery_lot_html):
    lot = parse_lot_detail(gallery_lot_html)
    assert lot["image_urls"] == [
        "https://image.invaluable.com/housePhotos/AnnettesLakesideAuction"
        "/01/817001/H22635-L443949881_original.jpg",
        "https://image.invaluable.com/housePhotos/AnnettesLakesideAuction"
        "/01/817001/H22635-Lw6Hv8ZIyTT57U_original.jpg",
    ]


def test_lot_gallery_excludes_the_neighbouring_lots_thumbnails(gallery_lot_html):
    """A lot page also renders the PREVIOUS and NEXT lots' photos.

    A loose `img[src*=housePhotos]` scan attributes those to this lot, which is
    how a downstream set identification ends up made from another lot's picture.
    """
    lot = parse_lot_detail(gallery_lot_html)
    joined = " ".join(lot["image_urls"])
    assert "L443961688" not in joined   # the previous lot
    assert "LjtVI53g6B5SUs" not in joined  # the next lot
    assert "prev-next" not in joined
    assert all(u.endswith("_original.jpg") for u in lot["image_urls"])


def test_a_lot_with_no_photos_returns_an_empty_list(lot_html):
    """Not an error. A photo-less lot is a real thing, and `[]` says so."""
    lot = parse_lot_detail(lot_html)
    assert lot["image_urls"] == []
