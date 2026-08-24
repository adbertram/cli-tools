"""Profit math never scores BrickLink's "no sales" shape as a real $0.00 comp."""
from __future__ import annotations

import pytest

from legoscout_cli.pricing import profit


def test_net_profit_is_resale_net_of_fees_less_landed_cost():
    result = profit.compute_potential_profit(
        avg_price=100.0, price_detail_count=5, estimated_total=50.0, fee_rate=0.13)

    assert result == {"priced": True, "potential_profit": round(100.0 * 0.87 - 50.0, 2)}


def test_missing_avg_price_is_unpriced():
    result = profit.compute_potential_profit(
        avg_price=None, price_detail_count=None, estimated_total=50.0, fee_rate=0.13)

    assert result == {"priced": False, "potential_profit": None}


@pytest.mark.parametrize("price_detail_count", [0, None])
def test_zero_avg_with_no_backing_listings_is_unpriced_not_a_real_zero(price_detail_count):
    """BrickLink's "no sales in the window" shape, not "sells for $0"."""
    result = profit.compute_potential_profit(
        avg_price=0.0, price_detail_count=price_detail_count,
        estimated_total=50.0, fee_rate=0.13)

    assert result == {"priced": False, "potential_profit": None}


def test_zero_avg_with_backing_listings_is_a_real_priced_zero():
    result = profit.compute_potential_profit(
        avg_price=0.0, price_detail_count=3, estimated_total=50.0, fee_rate=0.13)

    assert result["priced"] is True
    assert result["potential_profit"] == -50.0


def test_is_priced_matches_compute_potential_profit():
    assert profit.is_priced(100.0, 5) is True
    assert profit.is_priced(None, 5) is False
    assert profit.is_priced(0.0, 0) is False
    assert profit.is_priced(0.0, 3) is True


def test_blend_weights_by_comp_count():
    result = profit.blend_comp_average(500.0, 10, 540.0, 4)

    assert result["avg"] == round((500.0 * 10 + 540.0 * 4) / 14, 2)
    assert result["count"] == 14
    assert "bricklink (10 sold)" in result["basis"]
    assert "ebay (4 sold)" in result["basis"]


def test_blend_bricklink_only_when_ebay_has_no_evidence():
    result = profit.blend_comp_average(500.0, 10, None, 0)

    assert result == {"avg": 500.0, "count": 10,
                       "basis": "bricklink only (10 sold) -- no usable ebay comps"}


def test_blend_ebay_only_when_bricklink_has_no_evidence():
    """The bug-fix case: BrickLink confirms the set but reports its own
    "no sales in the window" shape (avg 0.0, count 0); eBay has real comps
    and prices the set alone rather than the set staying unpriced."""
    result = profit.blend_comp_average(0.0, 0, 540.0, 4)

    assert result == {"avg": 540.0, "count": 4,
                       "basis": "ebay only (4 sold) -- no usable bricklink comps in this condition"}


def test_blend_neither_source_has_evidence():
    result = profit.blend_comp_average(0.0, 0, None, 0)

    assert result == {"avg": None, "count": 0, "basis": "no usable comps from bricklink or ebay"}


def test_blend_gives_weight_one_to_a_priced_average_with_no_count():
    """BrickLink's avg_price and price_detail_count are parsed from independent
    raw keys, so a real average with an unset count is possible -- it must not
    be silently dropped to zero weight."""
    result = profit.blend_comp_average(500.0, None, 540.0, 4)

    assert result["count"] == 5
    assert result["avg"] == round((500.0 * 1 + 540.0 * 4) / 5, 2)
