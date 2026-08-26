"""Bulk score signals apply the fixed Duplo and target-color rules."""
from __future__ import annotations

import pytest

from legoscout_cli.scoring.score import score_record
from legoscout_cli.scoring.text_signals import scan


def _bulk_record(title: str = "LEGO bulk lot") -> dict:
    return {
        "listing_key": "test|bulk-signals",
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


def test_text_scan_reports_duplo_as_a_theme():
    assert "duplo" in scan("Large LEGO Duplo bulk lot")["themes"]


@pytest.mark.parametrize(
    ("record", "vision", "evidence"),
    [
        (_bulk_record("LEGO Duplo bulk lot"), _vision(), "listing text"),
        (_bulk_record(), _vision(themes=["duplo"]), "listing images"),
    ],
)
def test_duplo_reduces_bulk_quality_and_max_price(record, vision, evidence):
    scoring = score_record(record, vision)["scoring"]

    assert scoring["quality"] == 63
    assert scoring["quality_multiplier"] == pytest.approx(0.88)
    assert scoring["max_price"] == pytest.approx(35.20)
    assert evidence in scoring["signals"]["duplo"]["evidence"]


def test_majority_target_colors_raise_bulk_quality_and_max_price():
    vision = _vision(
        target_colors="strong",
        color_families=[
            "light_bluish_gray",
            "dark_bluish_gray",
            "black",
            "white",
        ],
    )

    scoring = score_record(_bulk_record(), vision)["scoring"]

    assert scoring["quality"] == 82
    assert scoring["quality_multiplier"] == pytest.approx(1.15)
    assert scoring["max_price"] == pytest.approx(46.00)
    assert "colors_strong" in scoring["signals"]


def test_visible_duplo_reduces_set_theme_quality():
    record = {
        "listing_key": "test|duplo-set",
        "listing_category": "set",
        "title": "LEGO block set",
        "estimated_total": 20.0,
        "potential_profit": 35.0,
        "set_completeness": "complete",
        "set_condition": "U",
    }

    scoring = score_record(record, _vision(themes=["duplo"]))["scoring"]

    assert scoring["signals"]["theme_liquidity"] == {
        "theme": "duplo",
        "multiplier": 0.88,
    }
