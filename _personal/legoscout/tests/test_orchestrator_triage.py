#!/usr/bin/env python3
"""Triage rejects only on arithmetic, and never loses a candidate.

The nationwide Facebook search made the crawl about a thousand times wider than
the appraiser: `deliveryMethod=shipping` returned 1,174 unique LEGO listings
across four queries without exhausting, and one 25-record appraisal batch takes
19 minutes. Something has to choose the order, and the danger in a chooser is
that it quietly stops finding things.

So the tests below check two properties above all:

  * The ONLY rejection is provable. A shipped lot whose asking price alone
    already beats the walk-away $/lb cannot clear, because freight only adds
    cost. Nothing else may reject, however weak the listing looks.
  * Nothing vanishes. Every candidate is either appraised now, deferred to the
    next run, or rejected with a stated reason, and the three partition the
    input exactly.

The fixtures are real titles and prices from the live 2026-08-18 shipping pool.
"""
from __future__ import annotations

import pytest

from legoscout_cli.orchestrator import triage
from legoscout_cli.scoring.score import BULK_WALKAWAY_PER_LB


def candidate(title, price):
    return {"listing_key": "facebook|%s" % abs(hash((title, price))),
            "title": title, "static_price": price,
            "price_basis": "static_price"}


# Live rows whose asking price alone exceeds $4.00/lb.
DEAD = [
    candidate("1 lbs Genuine LEGO Bulk Lot", 6.0),                    # $6.00/lb
    candidate("LEGO Bulk Bricks 2 lbs, assorted City and Friends", 12.0),  # $6.00
    candidate("Bulk Lego Tires 2.2lbs", 18.0),                        # $8.18/lb
    candidate("4lb Lego Bulk Lot: Assorted Bricks, Mini-figures", 60.0),   # $15.00
    candidate("Bulk Lego 1.2lbs Mostly built set and fig", 12.0),      # $10.00/lb
]
# Live rows whose asking price alone already clears.
ALIVE = [
    candidate("21.5 lbs Authentic LEGO Bulk Lot - Clean", 50.0),       # $2.33/lb
    candidate("Lego Bulk Lot #1 - 20lbs", 60.0),                       # $3.00/lb
    candidate("6.5 lbs of Bulk Loose Lego", 25.0),                     # $3.85/lb
    candidate("5 lbs bulk Lego City assortment", 20.0),                # $4.00/lb
]


# --- stated_weight, including the bug that shipped in the first cut ----------

@pytest.mark.parametrize("title,expected", [
    ("1 lbs Genuine LEGO Bulk Lot", 1.0),
    ("Bulk Lego Tires 2.2lbs", 2.2),
    ("Lego Bulk Lot #1 - 20lbs", 20.0),
    ("6.5 lbs of Bulk Loose Lego", 6.5),
    ("4 pound Gallon Bags of Assorted Lego Bricks", 4.0),
])
def test_stated_weight_reads_the_sellers_number(title, expected):
    assert triage.stated_weight(title) == expected


def test_a_leading_decimal_weight_is_not_read_as_a_whole_number():
    """`.88 lb` is 0.88 lb. The first pattern read it as 88.

    That single character turned a $10 listing into $0.11/lb -- a reject
    promoted to the top of the run, which is the worst direction for an
    ordering bug to fail in.
    """
    assert triage.stated_weight("LEGO .88 lb Lot Bulk Loose Parts") == 0.88

    row = candidate("LEGO .88 lb Lot Bulk Loose Parts", 10.0)
    assert triage.price_per_lb(row) == pytest.approx(11.36, abs=0.01)
    assert triage.reject(row) is not None


@pytest.mark.parametrize("title", [
    "LEGO Disney Moana's Wayfinding Boat 43210 321 pcs",
    "Lego flowers",
    "LEGO Friends Aliya's Room 41740 used Complete",
    "",
])
def test_no_stated_weight_is_a_real_answer_not_a_gap(title):
    assert triage.stated_weight(title) is None
    assert triage.price_per_lb(candidate(title, 20.0)) is None


def test_a_zero_or_negative_weight_states_nothing():
    assert triage.stated_weight("LEGO 0 lbs lot") is None


# --- reject(): one rule, and it is arithmetic --------------------------------

@pytest.mark.parametrize("row", DEAD)
def test_price_alone_over_the_walkaway_can_never_clear(row):
    reason = triage.reject(row)

    assert reason is not None
    assert "walk-away" in reason
    assert "freight" in reason or "shipping" in reason


@pytest.mark.parametrize("row", ALIVE)
def test_a_lot_that_clears_on_price_alone_is_never_rejected(row):
    assert triage.reject(row) is None


def test_exactly_at_the_walkaway_is_kept():
    """The rule is strictly greater-than. $4.00/lb is the walk-away, not past it."""
    row = candidate("5 lbs bulk Lego City assortment", 5 * BULK_WALKAWAY_PER_LB)

    assert triage.price_per_lb(row) == BULK_WALKAWAY_PER_LB
    assert triage.reject(row) is None


@pytest.mark.parametrize("row", [
    candidate("Lego flowers", 50.0),
    candidate("Legos", 35.0),
    candidate("Big block legos", 8.0),
    candidate("LEGO Bulk Bricks and Baseplates", 40.0),
])
def test_nothing_without_a_stated_weight_is_ever_rejected(row):
    """A weak-looking listing is the appraiser's call, not this module's."""
    assert triage.reject(row) is None


def test_a_missing_price_does_not_reject():
    assert triage.reject({"title": "2 lbs LEGO bulk", "static_price": None}) is None


def test_a_boolean_is_not_a_price():
    """`True` is an int in Python and would divide happily into a $/lb."""
    assert triage.price_per_lb({"title": "2 lbs LEGO", "static_price": True}) is None


# --- rank(): ordering only, never a verdict ----------------------------------

def test_tiers_are_assigned_by_what_is_already_visible():
    assert triage.rank(candidate("Lego Bulk Lot #1 - 20lbs", 60.0)) == triage.WEIGHT_CLEARS
    assert triage.rank(candidate("LEGO Friends Aliya's Room 41740", 20.0)) == triage.SET_NUMBER
    assert triage.rank(candidate("Bulk Lego bricks assorted", 40.0)) == triage.BULK_NO_WEIGHT
    assert triage.rank(candidate("Lego flowers", 10.0)) == triage.OTHER


def test_every_tier_name_is_in_the_declared_order():
    for row in DEAD + ALIVE:
        assert triage.rank(row) in triage.TIERS


# --- triage(): partitions the input, loses nothing ---------------------------

def test_the_best_dollars_per_pound_is_appraised_first():
    appraise, _ = triage.triage(list(reversed(ALIVE)))

    assert [triage.price_per_lb(c) for c in appraise] == sorted(
        triage.price_per_lb(c) for c in ALIVE)


def test_a_weight_backed_lot_outranks_a_set_number():
    rows = [candidate("LEGO Friends Aliya's Room 41740", 20.0),
            candidate("Lego Bulk Lot #1 - 20lbs", 60.0)]

    appraise, _ = triage.triage(rows)

    assert appraise[0]["title"] == "Lego Bulk Lot #1 - 20lbs"


def test_order_inside_a_tier_is_the_callers():
    rows = [candidate("Bulk Lego bricks assorted A", 40.0),
            candidate("Bulk Lego bricks assorted B", 41.0),
            candidate("Bulk Lego bricks assorted C", 42.0)]

    appraise, _ = triage.triage(rows)

    assert [c["title"][-1] for c in appraise] == ["A", "B", "C"]


def test_appraise_deferred_and_rejected_partition_the_input_exactly():
    rows = DEAD + ALIVE + [candidate("Lego flowers", 10.0),
                           candidate("LEGO Friends Nova's Room 41755", 20.0)]

    appraise, rejected = triage.triage(rows, limit=3)
    later = triage.deferred(rows, limit=3)

    keys = lambda rs: {r["listing_key"] for r in rs}
    seen = keys(appraise) | keys(later) | {c["listing_key"] for c, _ in rejected}

    assert len(appraise) == 3
    assert seen == keys(rows), "a candidate went missing between the three buckets"
    assert not (keys(appraise) & keys(later)), "a candidate is in two buckets"


def test_a_limit_defers_rather_than_drops():
    rows = ALIVE + DEAD

    appraise, _ = triage.triage(rows, limit=2)
    later = triage.deferred(rows, limit=2)

    assert len(appraise) == 2
    assert len(later) == len(ALIVE) - 2
    assert triage.deferred(rows, limit=None) == []


def test_no_limit_appraises_everything_that_survived():
    appraise, rejected = triage.triage(DEAD + ALIVE)

    assert len(appraise) == len(ALIVE)
    assert len(rejected) == len(DEAD)


def test_a_negative_limit_raises_rather_than_silently_emptying_the_run():
    with pytest.raises(ValueError, match="limit must be >= 0"):
        triage.triage(ALIVE, limit=-1)


def test_summary_reports_the_deferred_count_rather_than_hiding_it():
    rows = DEAD + ALIVE

    got = triage.summary(rows, limit=2)

    assert got["candidates"] == len(rows)
    assert got["rejected_cannot_clear"] == len(DEAD)
    assert got["appraise_now"] == 2
    assert got["deferred_to_next_run"] == len(ALIVE) - 2
    assert sum(got["tiers"].values()) == got["appraise_now"]


def test_an_empty_crawl_is_not_an_error():
    appraise, rejected = triage.triage([])

    assert appraise == []
    assert rejected == []
    assert triage.summary([])["candidates"] == 0


# --- the cap is spread across tiers, so no category starves ------------------

def _many(prefix, n, price):
    return [candidate("%s %d" % (prefix, i), price) for i in range(n)]


def test_a_cap_reaches_every_tier_rather_than_filling_from_the_top():
    """Strict tier order appraised ZERO bulk lots on the live pool.

    482 set listings queued ahead of 321 bulk ones, so a cap of 100 filled with
    6 `weight_clears` + 94 `set_number`. Bulk LEGO by the pound is what this
    project buys, so that ordering was correct-looking and wrong.
    """
    rows = ALIVE + _many("LEGO City Police Station 60246 set", 480, 60.0) \
                 + _many("Bulk Lego bricks assorted", 320, 40.0)

    appraise, _ = triage.triage(rows, limit=100)
    tiers = {t: 0 for t in triage.TIERS}
    for row in appraise:
        tiers[triage.rank(row)] += 1

    assert len(appraise) == 100
    assert tiers[triage.WEIGHT_CLEARS] == len(ALIVE), "the proven tier fills first"
    assert tiers[triage.BULK_NO_WEIGHT] > 0, "bulk was starved by set listings"
    assert tiers[triage.SET_NUMBER] > 0


def test_the_share_each_tier_gets_tracks_its_size():
    rows = _many("LEGO set 60246 number", 300, 60.0) + \
           _many("Bulk Lego bricks assorted", 100, 40.0)

    appraise, _ = triage.triage(rows, limit=40)
    tiers = {t: 0 for t in triage.TIERS}
    for row in appraise:
        tiers[triage.rank(row)] += 1

    assert len(appraise) == 40
    assert tiers[triage.SET_NUMBER] > tiers[triage.BULK_NO_WEIGHT]
    assert tiers[triage.BULK_NO_WEIGHT] >= 8


def test_a_tier_too_small_for_its_share_gives_the_budget_back():
    """A small tier must not waste budget a larger one could spend."""
    rows = _many("LEGO set 60246 number", 200, 60.0) + \
           _many("Bulk Lego bricks assorted", 2, 40.0)

    appraise, _ = triage.triage(rows, limit=50)

    assert len(appraise) == 50, "the cap was not filled"


def test_the_cap_is_still_honoured_when_it_exceeds_the_pool():
    rows = ALIVE + _many("Bulk Lego bricks assorted", 3, 40.0)

    appraise, _ = triage.triage(rows, limit=999)

    assert len(appraise) == len(rows)
    assert triage.deferred(rows, limit=999) == []


def test_deferred_is_computed_by_difference_not_by_a_prefix_slice():
    """The picked set is no longer a prefix, so a slice would report the wrong rows."""
    rows = ALIVE + _many("LEGO set 60246 number", 20, 60.0) + \
           _many("Bulk Lego bricks assorted", 20, 40.0)

    appraise, _ = triage.triage(rows, limit=12)
    later = triage.deferred(rows, limit=12)

    picked = {id(c) for c in appraise}
    assert len(later) == len(rows) - 12
    assert not any(id(c) in picked for c in later), "a row is both appraised and deferred"
    assert {id(c) for c in appraise} | {id(c) for c in later} == {id(c) for c in rows}
