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


# ---- unknown operators are rejected, not folded into the value ----

def test_unknown_operator_raises():
    # 'status:bogusop:active' used to parse as eq with the value
    # 'bogusop:active', match nothing, and print an empty result that reads as
    # "nothing matched" rather than "your filter is wrong".
    with pytest.raises(FilterValidationError) as excinfo:
        validate_filters(["status:bogusop:active"])

    msg = str(excinfo.value)
    assert "bogusop" in msg
    # The message lists the supported operators so the caller can correct it.
    assert "eq" in msg and "notnull" in msg and "startswith" in msg


def test_unknown_operator_raises_through_apply_filters():
    items = [{"id": "1", "status": "active"}]

    with pytest.raises(FilterValidationError):
        apply_filters(items, ["status:bogusop:active"])


def test_unknown_operator_in_second_comma_part_raises():
    with pytest.raises(FilterValidationError) as excinfo:
        validate_filters(["status:eq:active,price:bogusop:100"])
    assert "bogusop" in str(excinfo.value)


def test_unknown_operator_message_suggests_explicit_operator():
    # A colon-bearing value is still expressible; the error says how.
    with pytest.raises(FilterValidationError) as excinfo:
        validate_filters(["url:https://example.com"])
    assert "url:eq:https://example.com" in str(excinfo.value)


def test_two_token_shorthand_still_means_eq():
    items = [
        {"id": "1", "status": "active"},
        {"id": "2", "status": "archived"},
    ]

    assert [i["id"] for i in apply_filters(items, ["status:active"])] == ["1"]


def test_known_operators_are_unaffected():
    validate_filters([
        "status:eq:active",
        "price:gte:100",
        "name:like:%widget%",
        "category:in:a|b",
        "deleted_at:null",
        "email:notnull",
        "created:gt:2024-01-01",
    ])


def test_value_containing_colon_is_allowed_with_an_explicit_operator():
    items = [{"id": "1", "url": "https://example.com"}]

    filtered = apply_filters(items, ["url:eq:https://example.com"])

    assert [i["id"] for i in filtered] == ["1"]


# ---- extra_operators: service-native operator vocabularies ----

def test_extra_operators_are_accepted():
    # Notion-style date operators the shared module cannot evaluate but the
    # calling CLI translates itself.
    validate_filters(
        ["Publish Date:on_or_after:2026-07-20"],
        extra_operators=("before", "on_or_after", "past_week", "is_not_empty"),
    )


def test_extra_operators_do_not_impose_shared_value_arity():
    # 'past_week' takes no value and 'is_not_empty' takes one. The caller owns
    # that arity, so the shared validator must accept both forms.
    validate_filters(
        ["Publish Date:past_week", "Publish Date:is_not_empty:true"],
        extra_operators=("past_week", "is_not_empty"),
    )


def test_extra_operators_do_not_whitelist_everything_else():
    with pytest.raises(FilterValidationError) as excinfo:
        validate_filters(
            ["Publish Date:bogusop:2026-07-20"],
            extra_operators=("before", "on_or_after"),
        )

    msg = str(excinfo.value)
    assert "bogusop" in msg
    # Declared service-native operators appear in the supported list.
    assert "on_or_after" in msg


def test_empty_extra_operators_behaves_like_none():
    with pytest.raises(FilterValidationError):
        validate_filters(["status:bogusop:active"], extra_operators=())
