#!/usr/bin/env python3
"""One basis names one column, and a fixed ask resolves to exactly one basis.

Three defects hit the same field on 2026-08-06, all of them drift between the
`price_basis` enum in `deal_schema.json`, `schema.PRICE_FIELD_BY_BASIS`, and
`validate.PRICE_BASES` -- three hand-kept copies of one vocabulary:

  * `ask_price` mapped to `current_price` while the rows using it held the
    amount in `static_price`. `priced_amount()` returned None on 256 of 484
    ask_price rows -- 234 of Depop's 303 -- so each silently dropped out of
    landed cost, $/lb, fees, tax, profit and the score while still looking
    populated.
  * `estimated` was legal in the enum and in `PRICE_BASES` but was never a key
    in the map. A record holding a real $45.00 `buy_now_price` under
    `price_basis: estimated` returned None from `priced_amount()`, which made
    `validate.check` skip the hammer rule entirely -- a $999 hammer on a $45
    listing passed `--strict` clean.
  * `PRICE_BASIS_RULE` named only `buy_now_price` and `current_price`, so a
    fixed-ask source with neither left the worker to guess. 85 Facebook rows of
    ONE identical shape carried four different bases.

The answers: a fixed ask IS a static price, an estimated price is an invented
price, and the vocabulary is now ONE table that the other two sides are derived
from or checked against.
"""
from __future__ import annotations

import re

import pytest

from legoscout_cli.ledger import schema as deal_schema
from legoscout_cli.ledger import validate as vdr
from legoscout_cli.sources import listing
from legoscout_cli.sources import readers

# `unknown` names no stored column ON PURPOSE: it means the listing was not
# read, so `priced_amount()` returning None for it is the honest answer.
BASES_WITHOUT_A_COLUMN = ("unknown",)

RETIRED = ("ask_price", "estimated")

# Every `price_basis: <token>` assignment a rule text hands a worker.
ASSIGNMENT_RE = re.compile(r"price_basis:\s*`?([a-z_]+)`?")


def schema_bases():
    """The `price_basis` enum, read from `deal_schema.json` itself."""
    return tuple(deal_schema.load()["properties"]["price_basis"]["enum"])


# --- defect 2: every basis resolves to the column its rows actually hold -----

@pytest.mark.parametrize("basis", [b for b in schema_bases()
                                   if b not in BASES_WITHOUT_A_COLUMN])
def test_priced_amount_returns_the_number_for_every_priced_basis(basis):
    """A basis the schema allows must read a number out of a real record.

    Parametrised off the live enum, so adding a basis to `deal_schema.json`
    without mapping it in `PRICE_FIELD_BY_BASIS` fails here rather than turning
    into a ledger full of Nones.
    """
    column = deal_schema.PRICE_FIELD_BY_BASIS.get(basis)
    assert column is not None, (
        "price_basis %r is in the schema enum but names no column in "
        "PRICE_FIELD_BY_BASIS, so priced_amount() returns None for every row "
        "that uses it" % basis)

    record = {"listing_key": "test|1", "price_basis": basis,
              "buy_now_price": None, "current_price": None, "static_price": None}
    record[column] = 42.5
    assert deal_schema.priced_amount(record) == 42.5

    # $0 is a real price on a zero-bid auction and must not read as absent.
    record[column] = 0
    assert deal_schema.priced_amount(record) == 0


@pytest.mark.parametrize("basis", BASES_WITHOUT_A_COLUMN)
def test_a_basis_that_names_no_column_reads_as_no_price(basis):
    """`estimated`/`unknown` return None -- no fallback to another column."""
    record = {"listing_key": "test|1", "price_basis": basis,
              "buy_now_price": 10.0, "current_price": 20.0, "static_price": 30.0}
    assert deal_schema.priced_amount(record) is None


def test_static_price_basis_reads_static_price_not_current_price():
    """The exact shape that broke: the ask lives in `static_price` alone."""
    record = {"listing_key": "depop|1", "price_basis": "static_price",
              "listing_type": "fixed", "buy_now_price": None,
              "current_price": None, "static_price": 28.0}
    assert deal_schema.priced_amount(record) == 28.0


@pytest.mark.parametrize("basis", RETIRED)
def test_a_retired_basis_is_gone_from_all_three_sides_at_once(basis):
    """Leaving it in any one of the three is what let them disagree."""
    assert basis not in schema_bases()
    assert basis not in vdr.PRICE_BASES
    assert basis not in deal_schema.PRICE_BASIS_COLUMNS
    assert basis not in deal_schema.PRICE_FIELD_BY_BASIS


def test_the_validator_and_the_schema_allow_the_same_bases():
    """`PRICE_BASES` is derived from the schema, so it cannot be hand-drifted."""
    assert tuple(vdr.PRICE_BASES) == schema_bases()


def test_the_map_is_exhaustive_over_the_enum():
    """Every enum value has an entry, so none can silently price as nothing."""
    assert set(deal_schema.PRICE_BASIS_COLUMNS) == set(schema_bases())


def test_price_bases_raises_when_the_two_sides_drift(tmp_path):
    """The guard itself: an enum value with no entry must not survive a read.

    Written against a COPY of the real schema with one value added back, which
    is exactly the state `estimated` was in.
    """
    import json

    doc = json.loads(open(deal_schema.SCHEMA, encoding="utf-8").read())
    doc["properties"]["price_basis"]["enum"].append("estimated")
    drifted = tmp_path / "deal_schema.json"
    drifted.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(deal_schema.Invalid) as exc:
        deal_schema.price_bases(str(drifted))
    assert "estimated" in str(exc.value)


def test_every_priced_basis_maps_to_a_real_deal_column():
    """No mapping may point at a column `deal_schema.json` does not define."""
    columns = deal_schema.load()["properties"]
    for basis, column in deal_schema.PRICE_FIELD_BY_BASIS.items():
        assert basis in schema_bases(), \
            "PRICE_FIELD_BY_BASIS maps %r, which the schema enum does not allow" % basis
        assert column in columns, \
            "price_basis %r names column %r, which is not a deal field" % (basis, column)


# --- defect 4: an unresolvable basis must not read as "nothing to check" -----

def test_an_unresolvable_basis_raises_instead_of_reporting_the_record_clean():
    """The exact shape that passed `--strict`: $45 listing, $999 hammer.

    `estimated` named no column, so `priced_amount()` returned None and the
    hammer rule read that as "no price to compare against" and skipped. The
    record was reported with zero errors and zero warnings.
    """
    record = {"listing_key": "ebay|basis-estimated", "source": "ebay",
              "listing_type": "fixed", "price_basis": "estimated",
              "buy_now_price": 45.0, "current_price": None, "static_price": None,
              "available_fulfillment": ["shipping"], "status": "active",
              "fee_breakdown": {"hammer": 999.0}}
    with pytest.raises(deal_schema.Invalid) as exc:
        vdr.check(record)
    assert "ebay|basis-estimated" in str(exc.value)
    assert "estimated" in str(exc.value)


@pytest.mark.parametrize("basis,filled", [
    ("buy_now", "current_price"),
    ("static_price", "current_price"),
    # The case the three hand-written per-basis lines never covered.
    ("current_price", "static_price"),
    ("unknown", "buy_now_price"),
])
def test_a_legal_basis_whose_column_is_empty_is_an_error(basis, filled):
    """A stored price the declared basis does not name is a reported ERROR.

    Not a raise: the basis is legal, so this is a data defect on one row and
    `legoscout deals validate` must keep checking the other 2,313.
    """
    record = {"listing_key": "ebay|empty-basis-column", "source": "ebay",
              "listing_type": "fixed", "price_basis": basis,
              "buy_now_price": None, "current_price": None, "static_price": None,
              "available_fulfillment": ["shipping"], "status": "active"}
    record[filled] = 45.0
    _key, errors, _warns = vdr.check(record)
    assert any("holds no number" in e for e in errors), \
        "basis=%r with only %s stored produced no error: %s" % (basis, filled, errors)


def test_a_basis_whose_column_holds_the_number_passes_that_rule():
    """The same rule must stay quiet on a correct row."""
    record = {"listing_key": "ebay|good", "source": "ebay",
              "listing_type": "fixed", "price_basis": "static_price",
              "buy_now_price": None, "current_price": None, "static_price": 45.0,
              "available_fulfillment": ["shipping"], "status": "active"}
    _key, errors, _warns = vdr.check(record)
    assert not any("holds no number" in e for e in errors), errors


# --- defect 3: a fixed ask resolves to exactly one basis ---------------------

def test_a_fixed_ask_with_only_static_price_resolves_to_exactly_one_basis():
    """The shape that produced four different answers now produces one.

    `price_basis_for` walks the same `PRICE_BASIS_BRANCHES` table the rule text
    is rendered from, so the sentence a worker reads and the value the code
    computes cannot drift.
    """
    fixed_ask = {"listing_key": "facebook|1", "listing_type": "fixed",
                 "buy_now_price": None, "current_price": None,
                 "static_price": 45.0}
    assert listing.price_basis_for(fixed_ask) == "static_price"

    # And the basis it names round-trips back to the number.
    fixed_ask["price_basis"] = listing.price_basis_for(fixed_ask)
    assert deal_schema.priced_amount(fixed_ask) == 45.0


def test_the_branches_are_ordered_and_exhaustive():
    """Every price shape a listing can publish resolves, and to one basis."""
    cases = {
        (   ): None,                                   # nothing published
        ("buy_now_price",): "buy_now",
        ("current_price",): "current_price",
        ("static_price",): "static_price",
        ("buy_now_price", "current_price"): "buy_now",
        ("buy_now_price", "static_price"): "buy_now",
        ("current_price", "static_price"): "current_price",
        ("buy_now_price", "current_price", "static_price"): "buy_now",
    }
    for filled, expected in cases.items():
        record = {"listing_key": "test|1", "buy_now_price": None,
                  "current_price": None, "static_price": None}
        for column in filled:
            record[column] = 25.0
        if expected is None:
            # An unpriced listing was never read. It is not a `unknown` row.
            with pytest.raises(listing.Undetermined):
                listing.price_basis_for(record)
        else:
            assert listing.price_basis_for(record) == expected, \
                "columns %s resolved wrong" % (filled,)


def test_the_rule_text_names_a_basis_for_the_fixed_ask_case():
    """The prose itself must carry the third branch, not only the table.

    A source worker reads `PRICE_BASIS_RULE`, not `PRICE_BASIS_BRANCHES`. The
    rule is rendered from the table, so this checks the rendering never drops a
    branch.
    """
    rule = listing.PRICE_BASIS_RULE
    named = ASSIGNMENT_RE.findall(rule)
    assert named == [basis for _, basis, _ in listing.PRICE_BASIS_BRANCHES], \
        "the rendered rule names %s but the table declares %s" % (
            named, [b for _, b, _ in listing.PRICE_BASIS_BRANCHES])
    assert "static_price" in named
    assert "fixed ask" in rule
    for column, _, _ in listing.PRICE_BASIS_BRANCHES:
        assert column in rule, "the rule never names the %s column" % column


@pytest.mark.parametrize(
    "namespace", sorted(n for n in readers._load()
                        if getattr(readers._load()[n], "PRICE_BASIS_RULE", None)))
def test_no_source_rule_tells_a_worker_to_record_a_retired_basis(namespace):
    """Every per-source rule assigns only bases the schema still allows."""
    rule = readers._load()[namespace].PRICE_BASIS_RULE
    illegal = sorted(set(ASSIGNMENT_RE.findall(rule)) - set(schema_bases()))
    assert illegal == [], \
        "%s's PRICE_BASIS_RULE tells a worker to record %s" % (namespace, illegal)


@pytest.mark.parametrize("namespace", ("craigslist", "facebook"))
def test_the_fixed_ask_sources_state_their_own_single_answer(namespace):
    """Craigslist and Facebook publish no bid and no BIN, so they say so.

    Both inherited a shared rule that named no branch for them, and both ended
    up with four bases across one listing shape. A module-level override states
    the one answer rather than leaving it to be derived.
    """
    module = readers._load()[namespace]
    rule = module.PRICE_BASIS_RULE
    assert rule != listing.PRICE_BASIS_RULE, \
        "%s still inherits the shared rule verbatim" % namespace
    assert set(ASSIGNMENT_RE.findall(rule.split(listing._RULE_HEAD)[0])) \
        == {"static_price"}, \
        "%s's own prose must name static_price and nothing else" % namespace
