from cli_tools_shared.filters import apply_filters

import pytest


@pytest.mark.parametrize(
    ("filter_string", "expected_ids"),
    [
        ("unit_price:gt:500", ["higher", "thousand"]),
        ("unit_price:gte:500", ["exact", "higher", "thousand"]),
        ("unit_price:lt:500", ["low"]),
        ("unit_price:lte:500", ["low", "exact"]),
    ],
)
def test_comparison_filters_compare_numeric_strings_as_numbers(filter_string, expected_ids):
    items = [
        {"inventory_id": "low", "unit_price": "75.00"},
        {"inventory_id": "exact", "unit_price": "500.00"},
        {"inventory_id": "higher", "unit_price": "500.01"},
        {"inventory_id": "thousand", "unit_price": "1000.00"},
    ]

    filtered = apply_filters(items, [filter_string])

    assert [item["inventory_id"] for item in filtered] == expected_ids
