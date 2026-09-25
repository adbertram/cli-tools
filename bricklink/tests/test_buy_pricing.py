from bricklink_cli.buy.pricing import lower_percentile_price, score_price_guide


def test_lower_percentile_qty_weighted():
    details = [
        {"unit_price": 1.0, "quantity": 1, "shipping_available": True},
        {"unit_price": 2.0, "quantity": 8, "shipping_available": True},
        {"unit_price": 10.0, "quantity": 1, "shipping_available": True},
    ]
    # 10 units: one at 1, eight at 2, one at 10. Bottom 20% => first 2 units => ceiling price 2.0
    assert lower_percentile_price(details, percentile=20) == 2.0
    assert lower_percentile_price(details, percentile=10) == 1.0


def test_score_gap_vs_avg():
    payload = {
        "currency_code": "USD",
        "min_price": "1.0",
        "max_price": "10.0",
        "avg_price": "5.0",
        "qty_avg_price": "4.5",
        "unit_quantity": 3,
        "total_quantity": 10,
        "price_detail": [
            {"quantity": 1, "unit_price": "1.0", "shipping_available": True},
            {"quantity": 8, "unit_price": "2.0", "shipping_available": True},
            {"quantity": 1, "unit_price": "10.0", "shipping_available": True},
        ],
    }
    m = score_price_guide(payload, percentile=20)
    assert m["lower_pct_price"] == 2.0
    assert m["gap_abs"] == 3.0
    assert abs(m["gap_ratio"] - 0.6) < 1e-9


from bricklink_cli.buy.pricing import landed_buy_cost, opportunity_score, DEFAULT_SHIPPING_ESTIMATE


def test_landed_buy_adds_default_shipping():
    assert landed_buy_cost(10.0) == 10.0 + DEFAULT_SHIPPING_ESTIMATE
    assert landed_buy_cost(10.0, shipping_estimate=6.0) == 16.0
    assert landed_buy_cost(None) is None


def test_opportunity_score_includes_shipping():
    bare = opportunity_score(buy_proxy=10.0, sell_proxy=20.0, shipping_estimate=0)
    assert bare["opportunity_abs"] == 10.0
    with_ship = opportunity_score(buy_proxy=10.0, sell_proxy=20.0, shipping_estimate=5.5)
    assert with_ship["landed_buy"] == 15.5
    assert with_ship["opportunity_abs"] == 4.5
    assert abs(with_ship["opportunity_ratio"] - 4.5 / 20.0) < 1e-9
