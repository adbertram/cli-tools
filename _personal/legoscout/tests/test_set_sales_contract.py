"""Set comp lookup always sends a valid BrickLink item number."""
from __future__ import annotations

import pytest

from legoscout_cli.pricing import set_sales


def _summary():
    return {
        "avg_price": "100.00",
        "qty_avg_price": "100.00",
        "min_price": "90.00",
        "max_price": "110.00",
        "total_quantity": "2",
        "unit_quantity": "2",
        "currency_code": "USD",
        "price_detail": [{}, {}],
    }


def test_bare_set_number_gets_the_required_sequence_suffix():
    calls = []

    def runner(args):
        calls.append(args)
        return {"name": "Millennium Falcon"} if args[:2] == ["catalog", "set"] else _summary()

    result = set_sales.summarize_set("75192", "U", 50.0, 0.13, runner=runner)

    assert result["set_no"] == "75192-1"
    assert calls == [
        ["catalog", "set", "75192-1"],
        ["catalog", "price", "SET", "75192-1", "--condition", "U", "--sold"],
        ["catalog", "price", "SET", "75192-1", "--condition", "N", "--sold"],
    ]


@pytest.mark.parametrize("set_no", ["75192-U", "75192-0", "75192-null", "set 75192"])
def test_invalid_sequence_never_reaches_bricklink(set_no):
    def runner(_args):
        pytest.fail("an invalid set number reached BrickLink")

    with pytest.raises(set_sales.LookupFailed, match="positive sequence suffix"):
        set_sales.summarize_set(set_no, "U", 50.0, 0.13, runner=runner)


def test_condition_is_required_and_never_defaults_to_new():
    def runner(args):
        return {"name": "Millennium Falcon"} if args[:2] == ["catalog", "set"] else _summary()

    with pytest.raises(set_sales.LookupFailed, match="condition must be"):
        set_sales.summarize_set("75192", None, 50.0, 0.13, runner=runner)


def test_purchase_price_and_fee_rate_are_optional_together():
    """A comps-only caller with no landed cost gets comps, no potential_profit."""
    result = set_sales.summarize_set("75192", "U", runner=lambda args:
                                     {"name": "Millennium Falcon"} if args[:2] == ["catalog", "set"] else _summary())

    assert result["potential_profit"] is None
    assert result["selected_condition_priced"] is True
    assert result["used"]["six_month_avg_sold_price"] == 100.0


def test_purchase_price_without_fee_rate_raises():
    with pytest.raises(set_sales.LookupFailed, match="given together or omitted together"):
        set_sales.summarize_set("75192", "U", purchase_price=50.0, runner=lambda _args: _summary())
