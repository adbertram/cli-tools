#!/usr/bin/env python3
"""A corrupt record costs its own row, never the whole run and never the page.

Two defects, one shape: a single unusable value on ONE listing was allowed to
abort a whole-ledger operation, so the other 2000 records paid for it.

  * `score rescore` raised a bare `AssertionError: curve lookup fell through for
    x=nan` and stopped. The message named no listing, so the culprit could only
    be found by bisecting the ledger by hand, and NONE of the good records was
    rescored. The nan came from `price / max_price` where both were `inf`: an
    infinite `estimated_total` is a `number` to JSON Schema, so it cleared
    validation and the save.

  * `build_rows` raised out of its list comprehension and returned ZERO rows.
    An appraiser writing `fee_breakdown.premium_pct: "18%"` -- five distinct
    crash shapes reproduce below -- took 3 good rows down with 1 bad one, and
    an infinite `estimated_total` reached `json.dumps` as the bare token
    `Infinity`, which `await res.json()` cannot parse, so the page rendered
    nothing at all.

Isolation is not suppression. Nothing here substitutes a value for the one that
failed: the failing record is not written, not counted as scored, and is
reported BY LISTING KEY on stderr and in the payload.

The upstream fix -- rejecting non-finite numbers and mistyped `fee_breakdown`
values at the schema gate, so they never reach storage -- lives in
`test_schema_rejects_non_finite_numbers.py` and
`test_landed_cost_has_no_missing_data_fallback.py`. This file covers the rows
that are already stored, and the blast radius when one is.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3

import pytest

from legoscout_cli import paths
from legoscout_cli.display import rows as rows_module
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.scoring import rescore as rescore_module
from legoscout_cli.scoring import score as score_module
from legoscout_cli.sources import registry

CLEAN_KEYS = ("ebay|clean1", "ebay|clean2", "ebay|clean3")
POISONED = "ebay|poisoned"


# --------------------------------------------------------------------------
# A disposable ledger. The deals are ours; the source registry is a copy of the
# real one, because `rows.row()` resolves every listing_key through it.
# --------------------------------------------------------------------------

def _deal(key, **over):
    deal = {
        "listing_key": key,
        "source": "ebay",
        "id": key.split("|", 1)[1],
        "title": "LEGO lot %s" % key,
        "url": "https://www.ebay.com/itm/%s" % key,
        "direct_url": "https://www.ebay.com/itm/%s" % key,
        "status": "active",
        "listing_category": "set",
        "listing_type": "fixed",
        "price_basis": "static_price",
        "static_price": 50.0,
        "estimated_total": 55.0,
        "potential_profit": 40.0,
        "set_numbers": ["75192"],
        "set_condition": "U",
        "set_completeness": "complete",
        "used_avg_6mo": 95.0,
        "new_avg_6mo": 150.0,
        "seller_id": "seller-%s" % key,
        "seller_name": "Seller",
        "fee_breakdown": {"hammer": 50.0, "premium_pct": 0.0,
                          "sales_tax_pct": 0.07, "premium_amount": 0.0,
                          "sales_tax_amount": 3.5, "shipping_handling": 1.5},
        "available_fulfillment": ["shipping"],
        "first_seen_at": "2026-08-01T00:00:00+00:00",
        "last_seen_at": "2026-08-06T00:00:00+00:00",
    }
    deal.update(over)
    return deal


def _snapshot(real, dest):
    """A consistent copy taken through a read-only connection.

    `Connection.backup` rather than a file copy: the ledger runs in WAL mode, so
    the `.db` file alone can be missing committed transactions.
    """
    source = sqlite3.connect("file:%s?mode=ro" % real, uri=True)
    target = sqlite3.connect(dest)
    try:
        with target:
            source.backup(target)
    finally:
        source.close()
        target.close()


def _poison(path, updates):
    """Write the corrupt values with raw SQL.

    They are stored values, not accepted ones: `ledger_db.save()` now rejects
    every one of them at the schema gate. These are the rows already in a table
    -- written before that gate, or by a path that skipped it.
    """
    conn = sqlite3.connect(path)
    try:
        for listing_key, column, value in updates:
            conn.execute("UPDATE deals SET %s = ? WHERE listing_key = ?" % column,
                         (value, listing_key))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Three clean deals plus whatever the test poisons, in a scratch copy."""
    real = paths.DB_PATH
    if not os.path.isfile(real):
        raise FileNotFoundError(
            "the ledger is missing at %s, so the source registry these rows "
            "resolve against cannot be copied. Restore it from Dropbox rather "
            "than letting this suite skip." % real)
    copy = str(tmp_path / "found_deals.db")
    _snapshot(real, copy)
    conn = sqlite3.connect(copy)
    try:
        conn.execute("DELETE FROM deals")
        conn.commit()
    finally:
        conn.close()
    doc = ledger_db.load_document(copy)
    doc["deals"] = [_deal(key) for key in CLEAN_KEYS]
    ledger_db.save(doc, path=copy)
    # `rows.row()` reads the source registry through this singleton, which
    # defaults to the REAL ledger. Point it at the copy so no test can write
    # through a migration on Adam's ledger.
    monkeypatch.setattr(registry.sources, "path", copy)
    return copy


def _add(path, deal):
    doc = ledger_db.load_document(path)
    doc["deals"] = doc["deals"] + [deal]
    ledger_db.save(doc, path=path)


# --------------------------------------------------------------------------
# HIGH: an infinite estimated_total aborts the whole rescore
# --------------------------------------------------------------------------

def test_headroom_names_the_listing_it_could_not_price():
    """The listing_key is the whole point of the exception.

    Without it the failure was `curve lookup fell through for x=nan`, which is
    true, useless, and identical for every corrupt record in the ledger.
    """
    with pytest.raises(score_module.ScoringInputError) as raised:
        score_module.headroom(float("inf"), 120.0, "ebay|poisoned")
    assert "ebay|poisoned" in str(raised.value)
    assert raised.value.listing_key == "ebay|poisoned"


@pytest.mark.parametrize("price,max_price", [
    (float("inf"), 120.0),
    (float("nan"), 120.0),
    (55.0, float("inf")),
    (55.0, float("nan")),
])
def test_headroom_refuses_every_non_finite_pair(price, max_price):
    with pytest.raises(score_module.ScoringInputError):
        score_module.headroom(price, max_price, "ebay|x")


def test_interpolate_refuses_a_non_finite_position():
    """`nan` satisfies neither clamp branch nor `x0 <= x <= x1`, so it used to
    walk the whole curve and fall out of the bottom of the loop."""
    with pytest.raises(ValueError, match="finite"):
        score_module._interpolate(score_module._HEADROOM_CURVE, float("nan"))


def test_scoring_a_record_with_an_infinite_total_names_that_record():
    record = _deal(POISONED, estimated_total=float("inf"))
    with pytest.raises(score_module.ScoringInputError) as raised:
        score_module.score_record(record)
    assert POISONED in str(raised.value)


def test_one_unscorable_record_does_not_abort_the_rescore(ledger):
    """3 clean records still get a score, and the 4th is reported by key."""
    _add(ledger, _deal(POISONED))
    _poison(ledger, [(POISONED, "estimated_total", float("inf"))])

    summary = rescore_module.rescore(apply=False, include_rejected=False,
                                     limit=None, path=ledger)

    assert summary["stats"]["scored"] == len(CLEAN_KEYS)
    assert summary["stats"]["failed"] == 1
    assert [f["listing_key"] for f in summary["failed"]] == [POISONED]
    assert POISONED in summary["failed"][0]["error"]
    assert {row["listing_key"] for row in summary["rows"]} == set(CLEAN_KEYS)


def test_apply_writes_the_good_records_and_leaves_the_bad_one_alone(ledger):
    """Isolation, not substitution: nothing is invented for the bad record, and
    the good records are still written.

    The write goes through `upsert_deals()`, which validates and touches only
    the records handed to it. A whole-document `save()` re-validates the corrupt
    row that was already stored and refuses the ENTIRE ledger, which is the same
    blast radius one layer down: 3 good scores lost to 1 bad row.
    """
    _add(ledger, _deal(POISONED, score=42, last_score=42))
    _poison(ledger, [(POISONED, "estimated_total", float("inf"))])

    summary = rescore_module.rescore(apply=True, include_rejected=False,
                                     limit=None, path=ledger)

    assert summary["stats"]["failed"] == 1
    stored = {d["listing_key"]: d for d in ledger_db.load_deals(ledger)}
    assert stored[POISONED]["score"] == 42
    assert stored[POISONED].get("scoring") is None
    assert math.isinf(stored[POISONED]["estimated_total"])
    for key in CLEAN_KEYS:
        assert stored[key]["scoring"] is not None
        assert stored[key]["score"] is not None


def test_the_rescore_summary_is_parseable_json(ledger):
    """`allow_nan=False`. Python writes `NaN` / `Infinity`, which no other
    parser reads, and this summary is a caller-facing payload."""
    _add(ledger, _deal(POISONED))
    _poison(ledger, [(POISONED, "estimated_total", float("inf"))])
    summary = rescore_module.rescore(apply=False, include_rejected=False,
                                     limit=None, path=ledger)
    text = json.dumps(summary, allow_nan=False)
    assert json.loads(text)["stats"]["failed"] == 1


# --------------------------------------------------------------------------
# HIGH: one bad row kills the entire deals page
# --------------------------------------------------------------------------

# Every shape reproduced on `fee_breakdown`, with the exception each one threw
# out of `build_rows` before the fix.
CRASH_SHAPES = (
    ("ebay|pct-as-string", "premium_pct", "18%"),
    ("ebay|pct-as-numstr", "premium_pct", "0.18"),
    ("ebay|pct-as-list", "premium_pct", [0.18]),
    ("ebay|tax-inf", "sales_tax_pct", float("inf")),
    ("ebay|pct-nan", "premium_pct", float("nan")),
)


@pytest.fixture
def poisoned_page(ledger):
    """The three clean deals, one row per fee crash shape, and one infinite
    total. Every record is INSERTED clean and poisoned afterwards, because the
    schema gate now refuses to store any of these values."""
    for key, _field, _value in CRASH_SHAPES:
        _add(ledger, _deal(key))
    _add(ledger, _deal(POISONED))
    updates = [(POISONED, "estimated_total", float("inf"))]
    for key, field, value in CRASH_SHAPES:
        breakdown = dict(_deal(key)["fee_breakdown"])
        breakdown[field] = value
        updates.append((key, "fee_breakdown", json.dumps(breakdown)))
    _poison(ledger, updates)
    return ledger


def test_every_good_row_survives_a_poisoned_one(poisoned_page):
    built = rows_module.build_rows(path=poisoned_page)
    good = [row for row in built if "rowError" not in row]
    assert {row["key"] for row in good} == set(CLEAN_KEYS)


@pytest.mark.parametrize("key", [shape[0] for shape in CRASH_SHAPES])
def test_a_row_that_cannot_be_built_is_reported_not_dropped(poisoned_page, key):
    """Named, in place, with the reason. A dropped row is a silent wrong answer:
    the page would simply show one fewer deal, with nothing to say why."""
    built = {row["key"]: row for row in rows_module.build_rows(path=poisoned_page)}
    assert key in built, "the broken row was dropped instead of reported"
    broken = built[key]
    assert broken["rowError"]
    assert "FAILED" in broken["title"]
    # The page's own filters key on these, so a reported row stays reachable.
    assert broken["cat"] == "set"
    assert broken["status"] == "active"


def test_the_row_payload_is_parseable_json(poisoned_page):
    """`Infinity` on one field is what broke `await res.json()` for the whole
    page, so the payload is asserted against a strict parser, not eyeballed."""
    built = rows_module.build_rows(path=poisoned_page)
    text = json.dumps({"rows": built}, allow_nan=False)
    parsed = json.loads(text)
    assert len(parsed["rows"]) == len(CLEAN_KEYS) + len(CRASH_SHAPES) + 1


def test_an_infinite_total_fails_its_own_row_only(poisoned_page):
    built = {row["key"]: row for row in rows_module.build_rows(path=poisoned_page)}
    assert "total" in built[POISONED]["rowError"]
    assert built[CLEAN_KEYS[0]]["total"] == 55


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_js_numbers_refuses_a_number_json_parse_cannot_read(value):
    with pytest.raises(ValueError) as raised:
        rows_module.js_numbers({"total": value})
    assert "row.total" in str(raised.value), "the failing field must be named"


def test_js_numbers_still_renders_a_whole_float_as_an_integer():
    """The row contract the port was proved against, unchanged."""
    assert rows_module.js_numbers({"score": 70.0, "perLb": 2.5}) == {
        "score": 70, "perLb": 2.5}


def test_to_fixed_names_a_non_finite_input():
    """`Decimal("Infinity").quantize()` raises `InvalidOperation`, whose entire
    message is `[<class 'decimal.InvalidOperation'>]`."""
    with pytest.raises(ValueError, match="not a number"):
        rows_module._to_fixed(math.inf, 1)
