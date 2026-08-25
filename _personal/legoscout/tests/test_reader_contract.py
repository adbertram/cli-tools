"""A source reader may not contradict its own registry entry.

`sources/readers/estatesalesorg.py` answered `auction_end_date` with
`listing.never_an_auction("EstateSales.org is a sale-listing directory, not a
transacting marketplace, so no lot on it opens or closes")` while the registry
said `auction_tier: "always"` and every live item page carried `bidding: 1`, a
`start_date_time`/`item_close_date_time` pair and a `timezone`.
`estatesalesorg|125565727` was `status_text="active"` and closing
`2026-08-10 21:25:00` `US/Central`, and `readers.read(deal, "auction_end_date")`
returned the literal string `not-an-auction` for it.

Nothing raised, because both halves were well-formed on their own. A row with no
close date can never be seen to expire, so `invalidate.sweep` skips it forever.

Two things are tested: the reader now returns a real close date from a recorded
live payload, and the guard raises on the contradiction.

The payloads below are trimmed copies of real `window.pageData.item` blobs
fetched on 2026-08-06. They are fixtures on purpose -- the guard and the parser
must be provable without the network, and a live auction's close time moves when
a soft close extends it.
"""
from __future__ import annotations

import pytest

from legoscout_cli.sources import listing, reader_contract
from legoscout_cli.sources import readers
from legoscout_cli.sources.readers import estatesalesorg

# Trimmed from https://estatesales.org/online-auctions/125565727 on 2026-08-06.
LIVE_AUCTION = (
    '<html><script>window.pageData = {"item":{'
    '"id":125565727,"status_text":"active","bidding":1,'
    '"item_close_date_time":"2026-08-10 21:25:00",'
    '"start_date_time":"2026-08-06 00:23:33",'
    '"timezone":"US/Central","shipping":1,"starting_price":"5.00"'
    '}};</script></html>'
)
# https://estatesales.org/online-auctions/original-lego-movie-paperback-125619413
EASTERN_AUCTION = LIVE_AUCTION.replace(
    '"US/Central"', '"US/Eastern"').replace(
    '"2026-08-10 21:25:00"', '"2026-08-08 16:01:00"')

DEAL = {"listing_key": "estatesalesorg|125565727",
        "direct_url": "https://estatesales.org/online-auctions/125565727"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Serve the recorded page instead of fetching, and keep the cache clean."""
    listing.clear_cache()
    yield
    listing.clear_cache()


def _serve(monkeypatch, page):
    monkeypatch.setattr(listing, "http", lambda url: page)


# --- the reader reads the real close time -----------------------------------

def test_auction_end_date_returns_the_real_close_time(monkeypatch):
    _serve(monkeypatch, LIVE_AUCTION)

    value, evidence = estatesalesorg.auction_end_date(DEAL)

    assert value == "2026-08-10T21:25:00-05:00"
    assert value != "not-an-auction"
    assert "item_close_date_time" in evidence


def test_auction_start_date_returns_the_real_open_time(monkeypatch):
    _serve(monkeypatch, LIVE_AUCTION)

    value, _ = estatesalesorg.auction_start_date(DEAL)

    assert value == "2026-08-06T00:23:33-05:00"


def test_the_stated_timezone_is_honoured(monkeypatch):
    """Same wall clock, different zone, different instant.

    This source's consignors span US/Eastern, US/Central and US/Mountain, so
    dropping the zone moves a close time by hours.
    """
    _serve(monkeypatch, EASTERN_AUCTION)

    value, _ = estatesalesorg.auction_end_date(DEAL)

    assert value == "2026-08-08T16:01:00-04:00"


def test_the_value_matches_the_schema_and_the_expiry_sweep(monkeypatch):
    from legoscout_cli.ledger import schema as deal_schema
    from legoscout_cli.invalidate import sweep

    _serve(monkeypatch, LIVE_AUCTION)
    value, _ = estatesalesorg.auction_end_date(DEAL)

    deal_schema.validate({"listing_key": "estatesalesorg|125565727",
                          "auction_end_date": value})
    # The stored value has to be one `parse_past` can actually read, or the row
    # can never expire -- which is the whole defect, in a second costume.
    # The value carries an explicit -05:00 offset (2026-08-10T21:25:00-05:00
    # == 2026-08-11T02:25:00 UTC), so `parse_past` compares it as that exact
    # instant, not a calendar date -- these two checks stay well clear of it
    # on either side rather than landing inside the same UTC day.
    import datetime as dt

    def at(day):
        return dt.datetime(2026, 8, day, tzinfo=dt.timezone.utc)

    assert sweep.parse_past(value, at(12)) is True
    assert sweep.parse_past(value, at(9)) is False
    # The sentinel the reader used to return is the state that made a live row
    # unexpirable: `parse_past` reads it as "never ends".
    assert sweep.parse_past("not-an-auction", at(11)) is False


def test_readers_read_dispatches_to_the_real_reader(monkeypatch):
    _serve(monkeypatch, LIVE_AUCTION)

    value, _ = readers.read(DEAL, "auction_end_date")

    assert value == "2026-08-10T21:25:00-05:00"


# --- a payload that cannot answer raises, it does not fall back -------------

@pytest.mark.parametrize("removed,expected", [
    ('"item_close_date_time":"2026-08-10 21:25:00",', "item.item_close_date_time"),
    ('"timezone":"US/Central",', "item.timezone"),
])
def test_a_missing_half_of_the_answer_raises(monkeypatch, removed, expected):
    _serve(monkeypatch, LIVE_AUCTION.replace(removed, ""))

    with pytest.raises(listing.Undetermined) as exc:
        estatesalesorg.auction_end_date(DEAL)

    assert expected in str(exc.value)
    assert "not-an-auction" not in str(exc.value).replace(
        "a fixed-price listing", "")


def test_an_unknown_timezone_raises_rather_than_assuming_an_offset(monkeypatch):
    _serve(monkeypatch, LIVE_AUCTION.replace('"US/Central"', '"Mars/Olympus"'))

    with pytest.raises(listing.Undetermined, match="not a zone"):
        estatesalesorg.auction_end_date(DEAL)


def test_an_unreadable_stamp_raises(monkeypatch):
    _serve(monkeypatch, LIVE_AUCTION.replace(
        '"2026-08-10 21:25:00"', '"next Tuesday"'))

    with pytest.raises(listing.Undetermined, match="YYYY-MM-DD"):
        estatesalesorg.auction_end_date(DEAL)


# --- the guard --------------------------------------------------------------

def test_the_guard_raises_on_the_shipped_contradiction():
    """An `always` source whose reader answers `never_an_auction()`.

    This is the exact combination that shipped. It must not be expressible
    without something raising.
    """
    with pytest.raises(reader_contract.ReaderContractError) as exc:
        reader_contract.assert_consistent({"craigslist": "always"})

    message = str(exc.value)
    assert "craigslist" in message
    assert "never_an_auction()" in message
    assert "not-an-auction" in message


def test_the_guard_raises_on_the_inverse_contradiction():
    """A `never` source that writes a real close-time reader is equally wrong."""
    with pytest.raises(reader_contract.ReaderContractError, match="hibid"):
        reader_contract.assert_consistent({"hibid": "never"})


def test_estatesalesorg_no_longer_trips_the_guard():
    reader_contract.assert_consistent({"estatesalesorg": "always"})


def test_the_live_registry_and_every_reader_agree():
    """The ship gate. `legoscout sources validate` runs this same check."""
    from legoscout_cli.sources import registry

    assert registry.check() == []


def test_a_source_with_no_reader_module_is_not_a_finding():
    """Sources are registered before their reader is written."""
    assert reader_contract.problems({"a_brand_new_source": "always"}) == []


def test_sentinels_are_recognised_by_code_identity_not_by_name():
    """Every sentinel closure is already NAMED `auction_end_date`.

    Matching on `__name__` would flag every real reader too, so the check
    compares code objects, which only the factory's own closures share.
    """
    built = listing.never_an_auction("a different reason")

    assert built.__name__ == "auction_end_date"
    assert reader_contract.sentinel_name(built) == "listing.never_an_auction()"
    assert reader_contract.sentinel_name(estatesalesorg.auction_end_date) is None
    assert reader_contract.sentinel_name(None) is None


def test_shipping_estimate_states_the_true_reason():
    """The rate exists; it is just not published until after the hammer.

    The old text said EstateSales.org "takes no order and quotes no freight",
    which is the same false premise that produced the auction defect.
    """
    _, reason = estatesalesorg.shipping_estimate(DEAL)

    assert "post-auction invoice" in reason
    assert "not a transacting marketplace" not in reason
