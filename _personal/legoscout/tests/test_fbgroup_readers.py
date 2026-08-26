#!/usr/bin/env python3
"""The shared Facebook-GROUP reader base, and the three pilot namespaces on it.

A Facebook group is not Facebook Marketplace, and the two differences that cost
real money are pinned here:

1. ONE POST IS NOT ONE LISTING. Live 2026-08-25, post 2559186437869269 in group
   250458852075384 listed 21 separately priced sets ($10..$300) with their own
   availability. Keyed per post, 20 of those 21 buyable items vanish and the one
   that survives carries a price that is wrong for most of them. So the key
   carries a per-item sub-key, and a key without one RAISES rather than being
   read as an item.

2. The feed is RANKED, not chronological, and the CLI exposes no sort. The
   registry records that as the documented recency-sort exception; what this
   file pins is the code half -- there is no reader that pretends to a close
   date or a shipping rate this surface does not publish.

`seller_id` is here because the honest answer to "does this surface publish a
keyed seller identity?" turned out to be YES: Facebook carries
`feedback.owning_profile.id` on every group story node and the `facebook` CLI
did not expose it. It does now (`author_id`, added 2026-08-25), so this is a
deterministic field read rather than a NEEDS_PAGE_READ gap.

Payloads are trimmed copies of real `facebook groups posts get` output fetched
2026-08-25. Fixtures on purpose: a live post gets edited and sold.
"""
from __future__ import annotations

import re

import pytest

from legoscout_cli.ledger import shipping
from legoscout_cli.pricing import preflight
from legoscout_cli.sources import fbgroup, listing, reader_contract, readers
from legoscout_cli.sources.readers import (fbgroup_bricklinkww,
                                           fbgroup_retiredsets,
                                           fbgroup_usabst)

MODULES = (fbgroup_retiredsets, fbgroup_bricklinkww, fbgroup_usabst)
NAMESPACES = ("fbgroup-retiredsets", "fbgroup-bricklinkww", "fbgroup-usabst")

# facebook groups posts get 250458852075384/posts/2560051471116099
ROVER = {
    "post_id": "2560051471116099",
    "title": "READ THE ENTIRE LISTING, ANY QUESTIONS THAT CAN BE ANSWERED BY "
             "READING THE LISTING WILL BE IGNORED.",
    "author": "Jerzy Banasiak",
    "author_id": "1940746",
    "text": "Selling brand new & sealed Technics Apollo Lunar Roving Vehicle "
            "set 42182. Selling for $175 firm. I'm located in the northwest "
            "suburbs of Chicago. Pickup will be one of the local police "
            "stations. Will gladly ship at buyer's expense.",
    "timestamp": "2026-08-25T20:23:08+00:00",
    "url": "https://www.facebook.com/groups/250458852075384/posts/2560051471116099/",
    "comment_count": 0,
    "comments": [],
    "image_urls": ["https://scontent-iad3-2.xx.fbcdn.net/v/t39.30808-6/785678081.jpg"],
}

DEAL = {"listing_key": "fbgroup-retiredsets|2560051471116099#42182",
        "direct_url": ROVER["url"]}


@pytest.fixture(autouse=True)
def no_network():
    listing.clear_cache()
    yield
    listing.clear_cache()


def _serve(monkeypatch, payload):
    """Serve one payload and count how many CLI calls the readers make."""
    calls = []

    def fake_cli(argv):
        calls.append(argv)
        return payload

    monkeypatch.setattr(listing, "cli", fake_cli)
    return calls


# --- the key: one ledger row per ITEM ---------------------------------------

@pytest.mark.parametrize("printed,expected", [
    ("42182", "42182"),
    (42182, "42182"),
    ("10497-1", "10497-1"),
    ("31157", "31157"),
    ("Yoda Minifigure Activity set", "yoda-minifigure-activity-set"),
    ("  76391  ", "76391"),
])
def test_item_key_normalizes_the_identifier_the_post_prints(printed, expected):
    assert fbgroup.item_key(printed) == expected


@pytest.mark.parametrize("printed", ["", "   ", "---", "$$$"])
def test_item_key_refuses_an_identifier_that_names_nothing(printed):
    with pytest.raises(listing.Undetermined, match="identifies nothing"):
        fbgroup.item_key(printed)


def test_item_key_refuses_to_truncate_a_long_description():
    """Truncating would silently merge two items into one ledger row."""
    with pytest.raises(listing.Undetermined, match="key the item by the set number"):
        fbgroup.item_key("x" * (fbgroup._ITEM_KEY_MAX + 1))


def test_build_listing_key_matches_the_registered_format():
    key = fbgroup.build_listing_key("fbgroup-retiredsets", "2559186437869269",
                                    "31157")

    assert key == "fbgroup-retiredsets|2559186437869269#31157"


def test_build_listing_key_refuses_a_non_numeric_post_id():
    with pytest.raises(listing.Undetermined, match="not a Facebook group post id"):
        fbgroup.build_listing_key("fbgroup-retiredsets", "Legosforsale", "31157")


def test_split_key_returns_the_post_and_the_item():
    assert fbgroup.split_key(DEAL) == ("2560051471116099", "42182")


def test_split_key_refuses_a_row_keyed_per_post():
    """The 21-set post is the standing argument; a per-post key must not read."""
    with pytest.raises(listing.Undetermined, match="names a POST rather than an item"):
        fbgroup.split_key({"listing_key": "fbgroup-retiredsets|2559186437869269"})


@pytest.mark.parametrize("key", ["fbgroup-retiredsets|abc#42182",
                                 "fbgroup-retiredsets|2559186437869269#"])
def test_split_key_refuses_a_malformed_half(key):
    with pytest.raises(listing.Undetermined, match="does not split"):
        fbgroup.split_key({"listing_key": key})


# --- one fetch per POST, not per item ---------------------------------------

def test_twenty_one_items_in_one_post_cost_one_cli_call(monkeypatch):
    calls = _serve(monkeypatch, ROVER)
    items = ["21357", "31157", "43243", "40902", "31173", "43277", "43305",
             "21351", "31165", "76391", "43266", "76327", "75422", "75404",
             "43265", "42205", "42208", "21345", "76447", "30716",
             "yoda-minifigure-activity-set"]

    for item in items:
        deal = {"listing_key": "fbgroup-retiredsets|2559186437869269#%s" % item}
        assert fbgroup_retiredsets.seller_name(deal)[0] == "Jerzy Banasiak"

    assert len(calls) == 1, "the fetch must be keyed by the post, not the row"


def test_the_cache_never_leaks_one_group_post_into_another(monkeypatch):
    """Two namespaces can hold the same post id only by mistake -- but the key
    still separates them, the way listing.cached() requires."""
    calls = _serve(monkeypatch, ROVER)

    fbgroup_retiredsets.seller_name(DEAL)
    fbgroup_bricklinkww.seller_name(
        {"listing_key": "fbgroup-bricklinkww|2560051471116099#42182"})

    assert len(calls) == 2


def test_the_fetch_asks_the_right_group_and_post(monkeypatch):
    calls = _serve(monkeypatch, ROVER)

    fbgroup_usabst.seller_name(
        {"listing_key": "fbgroup-usabst|27883082184719451#75936"})

    assert calls == [["facebook", "groups", "posts", "get",
                      "266584920129216/posts/27883082184719451"]]


# --- the two deterministic fields -------------------------------------------

def test_seller_name_reads_the_posts_author(monkeypatch):
    _serve(monkeypatch, ROVER)

    value, evidence = fbgroup_retiredsets.seller_name(DEAL)

    assert value == "Jerzy Banasiak"
    assert "author=" in evidence


def test_seller_id_reads_facebooks_numeric_profile_id(monkeypatch):
    _serve(monkeypatch, ROVER)

    value, evidence = fbgroup_retiredsets.seller_id(DEAL)

    assert value == "1940746"
    assert "author_id=" in evidence


@pytest.mark.parametrize("field,reader,match", [
    ("author", "seller_name", "no author"),
    ("author_id", "seller_id", "no author_id"),
])
def test_a_missing_identity_raises_rather_than_defaulting(monkeypatch, field,
                                                          reader, match):
    _serve(monkeypatch, dict(ROVER, **{field: None}))

    with pytest.raises(listing.Undetermined, match=match):
        getattr(fbgroup_retiredsets, reader)(DEAL)


def test_a_display_name_is_never_substituted_for_an_identity(monkeypatch):
    """The one substitution that would look plausible and be wrong."""
    payload = {k: v for k, v in ROVER.items() if k != "author_id"}
    _serve(monkeypatch, payload)

    with pytest.raises(listing.Undetermined):
        fbgroup_retiredsets.seller_id(DEAL)


@pytest.mark.parametrize("module", MODULES)
def test_every_pilot_namespace_answers_both_seller_fields(module):
    answered = readers.answers()[module.NAMESPACE]

    assert "seller_id" in answered and "seller_name" in answered


# --- the two structural answers ---------------------------------------------

@pytest.mark.parametrize("module", MODULES)
def test_a_group_post_is_never_an_auction(module):
    assert reader_contract.sentinel_name(module.auction_end_date) == \
        "listing.never_an_auction()"
    assert module.auction_end_date(DEAL)[0] == "not-an-auction"


@pytest.mark.parametrize("module", MODULES)
def test_a_group_post_quotes_no_destination_rate(module):
    assert reader_contract.sentinel_name(module.shipping_estimate) == \
        "listing.never_quotes_shipping()"
    quote, reason = module.shipping_estimate(DEAL)

    assert quote["status"] == shipping.UNQUOTED
    assert "no destination rate" in quote["reason"]
    assert "no destination rate" in reason


# --- the two fields that genuinely need the body ----------------------------

@pytest.mark.parametrize("field", ["item_location", "available_fulfillment"])
@pytest.mark.parametrize("namespace", NAMESPACES)
def test_the_prose_fields_name_the_body_rather_than_reporting_a_gap(namespace,
                                                                    field):
    where = readers.where(namespace, field)

    assert "NOT DOCUMENTED" not in where
    assert "BODY" in where


@pytest.mark.parametrize("field", ["item_location", "available_fulfillment"])
def test_reading_a_prose_field_raises_and_says_where_to_look(monkeypatch, field):
    _serve(monkeypatch, ROVER)

    with pytest.raises(listing.Undetermined, match="the post BODY"):
        readers.read(DEAL, field)


def test_silence_about_shipping_is_never_read_as_pickup_only():
    """The 2026-07-26 audit's mistake, restated for a source with no
    delivery_types at all: a missing answer is unread, not local pickup."""
    assert "never" in fbgroup.NEEDS_PAGE_READ["available_fulfillment"]
    assert "UNREAD" in fbgroup.NEEDS_PAGE_READ["available_fulfillment"]


# --- one price basis, enforced ----------------------------------------------

@pytest.mark.parametrize("namespace", NAMESPACES)
def test_a_group_post_declares_exactly_one_price_basis(namespace):
    assert readers.price_bases(namespace) == ("static_price",)


def test_the_declared_tuple_matches_the_rule_text():
    """The tuple and the prose are two statements of one fact; drift is the bug."""
    assigned = set(re.findall(
        r"price_basis:\s*`?([a-z_]+)`?",
        fbgroup.PRICE_BASIS_RULE.split(listing.PRICE_BASIS_RULE)[0]))

    assert assigned == set(fbgroup.PRICE_BASES)


# --- the shared base is shared, not copied ----------------------------------

def test_all_three_namespaces_share_one_implementation():
    """The point of the base module: 33 groups, one place to fix Facebook."""
    for attribute in ("PRICE_BASES", "PRICE_BASIS_RULE", "NEEDS_PAGE_READ",
                      "auction_end_date", "shipping_estimate"):
        values = [getattr(module, attribute) for module in MODULES]
        assert all(value is values[0] for value in values), attribute


def test_each_namespace_module_supplies_only_its_group_id():
    ids = {module.NAMESPACE: module.GROUP_ID for module in MODULES}

    assert ids == {"fbgroup-retiredsets": "250458852075384",
                   "fbgroup-bricklinkww": "2318028917",
                   "fbgroup-usabst": "266584920129216"}


# --- preflight: an active CLI-first namespace must name its binary ----------

@pytest.mark.parametrize("namespace", NAMESPACES)
def test_preflight_routes_every_group_namespace_to_the_facebook_binary(namespace):
    assert preflight.SOURCE_CLI_BINARIES[namespace] == "facebook"
