#!/usr/bin/env python3
"""Facebook Marketplace: the two defects that made this source unreliable.

Both were silent. Neither raised, and both survived several runs.

1. `item_location` was unreadable. The module carried
   `NEEDS_PAGE_READ["item_location"] = "`marketplace get` often returns
   location: null -- carry the location from the `list` row instead"`, so
   `readers.read(deal, "item_location")` raised `Undetermined` for every
   Facebook row and the `legoscout deals refresh item_location` sweep did not
   list facebook among the sources that answer. The claim was true when it was
   written on 2026-07-24 and false afterwards: on 2026-08-18 eight live
   `marketplace get` calls returned a location on eight of eight -- Evansville
   IN, Henderson KY, Newburgh IN -- each identical to its own `list` row.

   Facebook prints a city and state under "Location is approximate" and never a
   ZIP, so the reader answers `require_city_state`, the no-ZIP sibling of
   `require_city_state_zip`. A bare town name is still refused: Chandler IN is
   15 miles from ZIP 47725 and Chandler AZ is 1,500.

2. `price_basis` drifted three ways for one row shape. Facebook runs no bidding
   and publishes no Buy It Now, so only the fixed-ask branch can ever match --
   yet the ledger held 36 `current_price` rows crawled 2026-07-30, 19 `buy_now`
   rows crawled 2026-08-04 (each duplicating the amount into `static_price` AND
   `buy_now_price`), and `static_price` after that. The rule text had named
   `static_price` since 2026-08-06 and prose alone did not hold it, so the fact
   is now a tuple a checker reads.

The payloads are trimmed copies of real `facebook marketplace get` output
fetched on 2026-08-18. Fixtures on purpose: a live listing sells.
"""
from __future__ import annotations

import pytest

from legoscout_cli.ledger import validate
from legoscout_cli.sources import listing, readers
from legoscout_cli.sources.readers import facebook

# facebook marketplace get 1533222438581861
EVANSVILLE = {
    "item_id": "1533222438581861",
    "title": "LEGO DC Super Heroes 76023 The Tumbler (Retired)",
    "price": 225.0,
    "location": "Evansville, IN",
    "availability": "Available",
    "delivery_types": ["IN_PERSON"],
    "seller_id": "100056675107101",
    "seller_name": "Kyle Hoffman",
}
# facebook marketplace get 1720056135806612 -- a different state, same shape.
HENDERSON = dict(EVANSVILLE, item_id="1720056135806612",
                 location="Henderson, KY", price=35.0)
# facebook marketplace get 28472857718965532 -- the only fulfillment shape that
# is not pickup-only. `SHIPPING_ONSITE` was absent from every row crawled before
# 2026-08-18, so the SHIPPING-prefix branch of `available_fulfillment` had never
# been exercised against a real payload.
SHIPS = dict(EVANSVILLE, item_id="28472857718965532",
             location="Newburgh, IN",
             delivery_types=["SHIPPING_ONSITE", "IN_PERSON"])

DEAL = {"listing_key": "facebook|1533222438581861",
        "direct_url": "https://www.facebook.com/marketplace/item/1533222438581861/"}


@pytest.fixture(autouse=True)
def no_network():
    listing.clear_cache()
    yield
    listing.clear_cache()


def _serve(monkeypatch, payload):
    monkeypatch.setattr(listing, "cli", lambda argv: payload)


# --- defect 1: the location is read, not hand-carried ------------------------

@pytest.mark.parametrize("payload,expected", [
    (EVANSVILLE, "Evansville, IN"),
    (HENDERSON, "Henderson, KY"),
    (SHIPS, "Newburgh, IN"),
])
def test_item_location_reads_the_city_and_state(monkeypatch, payload, expected):
    _serve(monkeypatch, payload)

    value, evidence = facebook.item_location(DEAL)

    assert value == expected
    assert "location=" in evidence


def test_item_location_refuses_a_bare_town(monkeypatch):
    """A town with no state cannot be resolved against ZIP 47725."""
    _serve(monkeypatch, dict(EVANSVILLE, location="Evansville"))

    with pytest.raises(listing.Undetermined, match="city_state-qualified"):
        facebook.item_location(DEAL)


def test_item_location_refuses_a_country_read_as_a_state(monkeypatch):
    _serve(monkeypatch, dict(EVANSVILLE, location="Evansville, US"))

    with pytest.raises(listing.Undetermined, match="not a USPS state"):
        facebook.item_location(DEAL)


def test_item_location_raises_when_the_listing_published_none(monkeypatch):
    """A null is a raise now, not an instruction to carry a value by hand."""
    _serve(monkeypatch, dict(EVANSVILLE, location=None))

    with pytest.raises(listing.Undetermined, match="no location"):
        facebook.item_location(DEAL)


def test_facebook_no_longer_claims_item_location_needs_a_page_read():
    """The stale NEEDS_PAGE_READ entry is what made the sweep skip this source."""
    assert "item_location" not in getattr(facebook, "NEEDS_PAGE_READ", {})
    assert "facebook" in readers.answers("item_location")


# --- the shipping-prefix branch, against a real payload ----------------------

def test_shipping_onsite_resolves_to_both_options(monkeypatch):
    _serve(monkeypatch, SHIPS)

    value, evidence = facebook.available_fulfillment(DEAL)

    assert value == ["local_pickup", "shipping"]
    assert "SHIPPING_ONSITE" in evidence


def test_pickup_only_listing_does_not_claim_shipping(monkeypatch):
    _serve(monkeypatch, EVANSVILLE)

    value, _ = facebook.available_fulfillment(DEAL)

    assert value == ["local_pickup"]


# --- defect 2: one basis, enforced rather than described ---------------------

def test_facebook_declares_exactly_one_price_basis():
    assert readers.price_bases("facebook") == ("static_price",)


def test_a_source_that_stores_several_bases_declares_none():
    """The guard must stay silent where more than one basis is legitimate.

    StockX is a bid/ask exchange and its 170 `buy_now` rows are correct.
    """
    assert readers.price_bases("stockx") is None
    assert readers.price_bases("ebay") is None


def _record(**over):
    rec = {"listing_key": "facebook|1533222438581861", "source": "facebook",
           "listing_type": "fixed", "status": "active",
           "available_fulfillment": ["local_pickup"],
           "item_location": "Evansville, IN",
           "price_basis": "static_price", "static_price": 225.0}
    rec.update(over)
    return rec


def _basis_errors(rec):
    _, errors, _ = validate.check(rec)
    return [e for e in errors if "PRICE_BASES" in e]


@pytest.mark.parametrize("basis,field", [("buy_now", "buy_now_price"),
                                         ("current_price", "current_price")])
def test_validate_rejects_a_basis_facebook_can_never_publish(basis, field):
    rec = _record(price_basis=basis, static_price=None, **{field: 225.0})

    assert _basis_errors(rec), (
        "a %r row on a source that runs no bidding must not validate" % basis)


def test_validate_accepts_the_declared_basis():
    assert not _basis_errors(_record())


def test_unknown_stays_legal_because_it_means_unread():
    assert not _basis_errors(_record(price_basis="unknown"))


def test_the_guard_is_silent_on_a_source_that_declares_nothing():
    rec = {"listing_key": "stockx|9", "source": "stockx", "listing_type": "fixed",
           "status": "active", "price_basis": "buy_now", "buy_now_price": 80.0,
           "available_fulfillment": ["shipping"], "item_location": "Portland, OR"}

    assert not _basis_errors(rec)


def test_the_declared_tuple_matches_the_rule_text():
    """The tuple and the prose are two statements of one fact; drift is the bug."""
    import re

    assigned = set(re.findall(r"price_basis:\s*`?([a-z_]+)`?",
                              facebook.PRICE_BASIS_RULE.split(
                                  listing.PRICE_BASIS_RULE)[0]))

    assert assigned == set(facebook.PRICE_BASES)
