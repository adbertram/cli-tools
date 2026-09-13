"""Offline tests for the shared list-command helpers.

These cover the option-validation behavior added in response to the
chaos-engineer findings: unknown ``--properties`` and ``--filter`` fields are
actionable errors instead of silent empty results, and a negative ``--limit``
is rejected.
"""
import pytest
import typer
from cli_tools_shared.filters import FilterValidationError

from grokbot_sessions_cli.commands import _render

ROWS = [
    {"id": "1", "name": "Lego Scout", "turn": 3, "raw": {"id": "r1", "secret": "x"}},
    {"id": "2", "name": "Kalshi Guru", "turn": 5, "raw": {"id": "r2", "secret": "y"}},
]


def test_fetch_limit_rejects_negative_limit():
    with pytest.raises(typer.BadParameter):
        _render.fetch_limit(-1, None)


def test_fetch_limit_zero_means_zero_rows():
    assert _render.fetch_limit(0, None) == 0


def test_fetch_limit_fetches_wide_when_filtered():
    assert _render.fetch_limit(5, ["name:eq:x"]) is None


def test_apply_row_filters_matches_known_field():
    filtered = _render.apply_row_filters(ROWS, ["name:eq:Lego Scout"])
    assert [row["id"] for row in filtered] == ["1"]


def test_apply_row_filters_rejects_nested_field_paths():
    """Filters are top-level; a dotted path is reported, not silently empty."""
    with pytest.raises(FilterValidationError) as excinfo:
        _render.apply_row_filters(ROWS, ["raw.id:eq:r2"])
    assert "not filterable" in str(excinfo.value)


def test_apply_row_filters_rejects_unknown_field():
    with pytest.raises(FilterValidationError):
        _render.apply_row_filters(ROWS, ["nope:eq:1"])


def test_apply_row_filters_is_case_sensitive_on_values_only():
    # eq stays exact; the field name is what gets validated.
    assert _render.apply_row_filters(ROWS, ["name:eq:lego scout"]) == []
    assert len(_render.apply_row_filters(ROWS, ["name:ilike:lego scout"])) == 1


def test_apply_row_filters_returns_unchanged_without_filter_or_rows():
    assert _render.apply_row_filters(ROWS, None) == ROWS
    assert _render.apply_row_filters([], ["name:eq:x"]) == []


def test_select_properties_projects_requested_fields():
    selected = _render.select_properties(ROWS, "id,name")
    assert selected == [
        {"id": "1", "name": "Lego Scout"},
        {"id": "2", "name": "Kalshi Guru"},
    ]


def test_select_properties_supports_dot_notation():
    selected = _render.select_properties(ROWS, "id,raw.secret")
    assert selected[0] == {"id": "1", "raw.secret": "x"}


def test_select_properties_emits_explicit_null_for_absent_field():
    selected = _render.select_properties(ROWS, "id,missing")
    assert selected[0]["missing"] is None


def test_select_properties_rejects_a_field_that_matches_nothing():
    with pytest.raises(typer.BadParameter) as excinfo:
        _render.select_properties(ROWS, "nope")
    assert "Available fields" in str(excinfo.value)


def test_select_properties_leaves_empty_rows_and_empty_request_alone():
    assert _render.select_properties([], "nope") == []
    assert _render.select_properties(ROWS, None) == ROWS
    assert _render.select_properties(ROWS, " , ") == ROWS
