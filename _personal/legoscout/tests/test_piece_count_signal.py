"""A stated PIECE COUNT on a bulk lot is a pick-over marker.

`facebook|28198740076450822`, "Bulk Lot of 1000 Miscellaneous Pieces (Shades
of Grey)", scored 85 on 2026-08-24 because Technic (+4) and strong target
colours (+7) fired and nothing read the seller's own headline: the lot was
advertised by COUNTED PIECES, not pounds. Counting is what a seller does after
sorting a lot -- the minifigs and good sets are already pulled and the ask
prices the remainder as inventory (Adam, 2026-08-24).

`piece_count_advertised` detects the number+unit pair deterministically,
floored at three digits so small set piece counts never fire, and
`BULK_SIGNALS["piece_count_advertised"]` prices the consequence: -20 quality,
x0.72 max-price, which lands a counted plain-lot walk-away at $2.88/lb --
just under Adam's $3/lb preferred line.
"""
from __future__ import annotations

import pytest

from legoscout_cli.scoring.score import score_record
from legoscout_cli.scoring.text_signals import scan


# --- detection: the counting shapes sellers actually write -------------------

@pytest.mark.parametrize("text", [
    # the exact regression title
    "Bulk Lot of 1000 Miscellaneous Pieces ( Shades of Grey )",
    "1000 pieces of LEGO",
    "Over 1,000 Pieces!",
    "1,200+ pcs",
    "assorted LEGO, approximately 750 pc lot",
    "a 1000-piece bulk assortment",
    "huge lot with well over 500 piece count",
    "Pieces: 850",
    "lego parts 250pcs mixed",
])
def test_a_stated_bulk_piece_count_fires(text):
    assert scan(text)["piece_count_advertised"] is True


# --- detection: honest lots must not fire ------------------------------------

@pytest.mark.parametrize("text", [
    # pounds-denominated listings are the garage-clearout shape to protect
    "15 lbs of LEGO bulk lot",
    "LEGO lot weighing 25 pounds",
    "sold by the pound",
    # small counts belong to boxed sets, not picked-over bulk
    "LEGO City Police Station, 62 pieces",
    "a few loose pieces included",
    "bulk LEGO bricks, no piece count given",
])
def test_weight_denominated_and_small_counts_do_not_fire(text):
    result = scan(text)

    assert result["piece_count_advertised"] is False


def test_by_the_pound_and_piece_count_are_independent_signals():
    result = scan("Bulk Lot of 1000 Miscellaneous Pieces")

    assert result["piece_count_advertised"] is True
    assert result["by_the_pound"] is False


# --- scoring: the penalty ------------------------------------------------------

def _bulk_record(title: str = "LEGO bulk lot") -> dict:
    return {
        "listing_key": "test|piece-count",
        "listing_category": "bulk",
        "title": title,
        "estimated_total": 20.0,
        "weight_lbs": 10.0,
    }


def _vision(**changes) -> dict:
    vision = {
        "status": "checked",
        "image_count": 1,
        "target_colors": "none",
        "color_families": [],
        "themes": [],
        "minifigs": "not_visible",
        "contamination": [],
        "retired_sets_visible": False,
        "weight_estimate_lbs": None,
        "weight_confidence": None,
        "notes": "Test observation.",
    }
    vision.update(changes)
    return vision


def test_piece_count_reduces_bulk_quality_and_max_price():
    scoring = score_record(_bulk_record("Bulk lot, 1000 pieces"), _vision())[
        "scoring"]

    assert scoring["quality"] == 55
    assert scoring["quality_multiplier"] == pytest.approx(0.72)
    assert scoring["max_price"] == pytest.approx(28.80)
    assert "listing text" in scoring["signals"]["piece_count_advertised"]["evidence"]


def test_set_listings_advertising_piece_counts_are_not_penalized():
    """A set may legitimately state its catalog piece count; the penalty is
    bulk-path only."""
    plain = {
        "listing_key": "test|set",
        "listing_category": "set",
        "title": "LEGO Creator set, used",
        "estimated_total": 30.0,
        "potential_profit": 40.0,
        "set_completeness": "complete",
        "set_condition": "U",
    }
    counted = {**plain, "title": "LEGO Creator set, used, 710 pieces"}

    assert (score_record(counted)["scoring"]
            == score_record(plain)["scoring"])


def test_the_facebook_regression_now_scores_in_the_mid_50s():
    """The exact 2026-08-24 row: Technic + strong grays still fire, but the
    counted-piece penalty drags 85 down to ~55 and the walk-away from $77.28
    to ~$55.64 on the vision-estimated 15 lb."""
    record = _bulk_record("Bulk Lot of 1000 Miscellaneous Pieces")
    record["estimated_total"] = 44.45
    record["weight_lbs"] = None
    vision = _vision(
        target_colors="strong",
        color_families=["light_bluish_gray", "dark_bluish_gray"],
        themes=["technic"],
        weight_estimate_lbs=15.0,
        weight_confidence="medium",
    )

    scoring = score_record(record, vision)["scoring"]

    assert scoring["quality"] == 66
    assert scoring["quality_multiplier"] == pytest.approx(0.9274)
    assert scoring["max_price"] == pytest.approx(55.64)
    assert scoring["score"] == 55
