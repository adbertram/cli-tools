"""Parser tests backed by REAL captured /api/orders payloads.

Fixtures: tests/fixtures/orders_list.json (GET /api/orders, 6 live records)
and tests/fixtures/orders_detail_med-seg.json (GET /api/orders/med-seg),
captured 2026-09-03 from Adam's authenticated trainee.digital session. No
value below is invented: assertions compare derived fields against the real
record values in the fixtures.
"""

from __future__ import annotations

import math

import pytest

from trainee_digital_cli.parsers import (
    ORDERS_LIST_URL,
    normalize_order,
    normalize_order_detail,
    normalize_orders,
)


def test_real_records_normalize_with_url(orders_list_body):
    rows = normalize_orders(orders_list_body)
    assert len(rows) == len(orders_list_body) == 6
    for raw, row in zip(orders_list_body, rows):
        assert row["id"] == raw["id"]
        assert row["title"] == raw["title"]
        assert row["url"] == ORDERS_LIST_URL
        assert row["url"] == "https://trainee.digital/orders"


def test_real_records_keep_every_api_field(orders_list_body):
    """The output record is the raw API record plus the derived url -- no
    filtering, so the 'all data the API provides' contract holds."""
    rows = normalize_orders(orders_list_body)
    for raw, row in zip(orders_list_body, rows):
        for key, value in raw.items():
            assert key in row, f"raw field {key} dropped from normalized record"
            assert row[key] == value, f"raw field {key} altered by normalization"


def test_real_records_are_strict_json_numbers(orders_list_body):
    """Records must be strict JSON: every number finite (no NaN/Infinity)."""
    for row in normalize_orders(orders_list_body):
        for key, value in row.items():
            if isinstance(value, float):
                assert math.isfinite(value), f"{key} is not finite: {value}"
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, float):
                        assert math.isfinite(item), f"{key} holds non-finite {item}"


def test_fixture_covers_pay_shapes(orders_list_body):
    """The fixture exercises several per-unit rates so pay handling is tested
    against real shapes (all are '$<decimal>' strings in the live feed)."""
    pays = {row["pay"] for row in orders_list_body}
    assert pays == {"$0.40", "$0.55", "$0.90", "$0.48", "$0.35", "$0.42"}


def test_detail_normalize_keeps_guidelines_and_adds_url(order_detail_body):
    row = normalize_order_detail(order_detail_body, "med-seg")
    assert row["id"] == "med-seg"
    assert row["url"] == ORDERS_LIST_URL
    assert row["totalPay"] == "≈ $480 total"
    assert row["dataset"] == "DICOM exports"
    assert isinstance(row["guidelines"], list) and len(row["guidelines"]) == 4
    assert row["createdAt"] == "2026-06-25T07:49:06.000Z"


def test_detail_keeps_every_api_field(order_detail_body):
    row = normalize_order_detail(order_detail_body, "med-seg")
    for key, value in order_detail_body.items():
        assert key in row, f"detail field {key} dropped"
        assert row[key] == value, f"detail field {key} altered"


def test_normalize_orders_rejects_non_list():
    with pytest.raises(TypeError):
        normalize_orders({"not": "a list"})


def test_normalize_orders_none_is_empty():
    assert normalize_orders(None) == []


def test_normalize_order_rejects_non_dict():
    with pytest.raises(TypeError):
        normalize_order(["not", "a", "dict"])


def test_normalize_order_detail_id_fallback():
    row = normalize_order_detail({"title": "x"}, "fallback-id")
    assert row["id"] == "fallback-id"
    assert row["url"] == ORDERS_LIST_URL


def test_normalize_order_does_not_mutate_input():
    raw = {"id": "a", "title": "t"}
    snapshot = dict(raw)
    normalize_order(raw)
    assert raw == snapshot
