from cli_tools_shared.filters import (
    apply_filters,
    validate_filters,
    FilterValidationError,
)

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


# ---- like / ilike are case-insensitive (SQL-LIKE semantics) ----

@pytest.mark.parametrize("op", ["like", "ilike"])
def test_like_is_case_insensitive(op):
    # `name:like:%google%` must match an entry named "Google". A case-sensitive
    # 'like' silently drops the match and reads as "not found".
    items = [
        {"id": "1", "name": "Google"},
        {"id": "2", "name": "google.com"},
        {"id": "3", "name": "RF Google"},
        {"id": "4", "name": "GitHub"},
    ]

    filtered = apply_filters(items, [f"name:{op}:%google%"])

    assert {item["id"] for item in filtered} == {"1", "2", "3"}


def test_like_anchors_full_value_with_wildcards():
    # Without a leading/trailing %, 'like' anchors the whole value (^...$).
    items = [
        {"id": "1", "name": "Google"},
        {"id": "2", "name": "google.com"},
    ]

    exact = apply_filters(items, ["name:like:google"])
    assert {item["id"] for item in exact} == {"1"}  # case-insensitive exact

    prefix = apply_filters(items, ["name:like:google%"])
    assert {item["id"] for item in prefix} == {"1", "2"}


# ---- allowed_fields: opt-in unsupported-field validation ----

def test_unsupported_field_raises_when_allowed_fields_declared():
    items = [{"id": "1", "name": "Google"}]

    with pytest.raises(FilterValidationError) as excinfo:
        apply_filters(items, ["Username:like:%x%"], allowed_fields=("id", "name", "group", "full_path"))

    msg = str(excinfo.value)
    assert "Username" in msg
    # Error lists the supported fields so the caller can correct the query.
    assert "name" in msg and "group" in msg


def test_unsupported_field_raises_even_on_empty_dataset():
    # Empty data must not mask an unsupported-field filter as a clean no-match.
    with pytest.raises(FilterValidationError):
        apply_filters([], ["URL:like:%x%"], allowed_fields=("id", "name"))


def test_validate_filters_raises_for_unsupported_field():
    with pytest.raises(FilterValidationError):
        validate_filters(["Username:eq:bob"], allowed_fields=("id", "name"))


def test_allowed_fields_permits_declared_fields():
    items = [
        {"id": "1", "name": "Google", "group": "Home"},
        {"id": "2", "name": "GitHub", "group": "Work"},
    ]
    allowed = ("id", "name", "group", "full_path")

    filtered = apply_filters(items, ["group:eq:Home"], allowed_fields=allowed)
    assert [item["id"] for item in filtered] == ["1"]


def test_allowed_fields_check_is_case_sensitive():
    # Field lookup at match time is case-sensitive, so a wrong-case field name
    # ('Name' vs 'name') would silently match nothing. The allowlist check must
    # reject it loudly rather than let that false-negative through.
    items = [{"id": "1", "name": "Google"}]
    with pytest.raises(FilterValidationError) as excinfo:
        apply_filters(items, ["Name:eq:Google"], allowed_fields=("id", "name"))
    assert "Name" in str(excinfo.value)


def test_no_allowed_fields_preserves_unrestricted_behavior():
    # Backward compat: without allowed_fields, an unknown field just matches
    # nothing (no error) -- existing callers are unaffected.
    items = [{"id": "1", "name": "Google"}]
    assert apply_filters(items, ["Username:eq:bob"]) == []


def test_empty_allowed_fields_is_a_caller_error():
    with pytest.raises(FilterValidationError):
        validate_filters(["name:eq:x"], allowed_fields=())
