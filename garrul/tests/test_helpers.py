"""scan_filter: deciding whether _pages needs a client-side scan or can trust the raw page.

Part of the Finding 1 fix (chaos-engineer report): --limit must bound the FILTERED
result, not the raw fetch window, whenever a --filter clause is not fully pushed to
Garrul as a query parameter. These are pure-function tests -- no network involved.
"""

from garrul_cli.commands.comments import QUEUE_FILTERS
from garrul_cli.helpers import scan_filter


def test_no_filters_means_no_scan_is_needed():
    assert scan_filter(QUEUE_FILTERS, []) is None
    assert scan_filter(None, []) is None


def test_an_eq_filter_on_a_translated_field_is_fully_covered():
    assert scan_filter(QUEUE_FILTERS, ["status:eq:approved"]) is None


def test_a_ne_filter_on_the_same_field_is_not_covered():
    scan = scan_filter(QUEUE_FILTERS, ["status:ne:approved"])
    assert scan is not None
    assert [row["status"] for row in scan([{"status": "pending"}, {"status": "approved"}])] == ["pending"]


def test_a_filter_on_a_field_with_no_translator_is_not_covered():
    scan = scan_filter(QUEUE_FILTERS, ["id:eq:c1"])
    assert scan is not None
    assert scan([{"id": "c1"}, {"id": "c2"}]) == [{"id": "c1"}]


def test_two_filter_flags_or_together_and_are_never_covered():
    """server_params only ever pushes a lone --filter group; scan_filter must agree."""
    scan = scan_filter(QUEUE_FILTERS, ["status:eq:approved", "status:eq:spam"])
    assert scan is not None
    assert [row["status"] for row in scan([{"status": "approved"}, {"status": "pending"}, {"status": "spam"}])] == [
        "approved",
        "spam",
    ]


def test_one_group_is_covered_only_when_every_and_clause_is_covered():
    # Both clauses translate: no scan needed.
    assert scan_filter(QUEUE_FILTERS, ["status:eq:approved,host:eq:blog.example.test"]) is None
    # 'id' has no translator, so the whole AND group is uncovered even though 'status' does.
    scan = scan_filter(QUEUE_FILTERS, ["status:eq:approved,id:eq:c1"])
    assert scan is not None
    assert scan([{"status": "approved", "id": "c1"}, {"status": "approved", "id": "c2"}]) == [
        {"status": "approved", "id": "c1"}
    ]


def test_a_filter_map_with_no_field_at_all_is_never_covered():
    """users list has no FilterMap: every --filter is always client-side."""
    scan = scan_filter(None, ["name:eq:Ann"])
    assert scan is not None
    assert scan([{"name": "Ann"}, {"name": "Bea"}]) == [{"name": "Ann"}]


def test_a_comma_inside_the_filter_value_round_trips_through_the_coverage_check():
    """post_slug is eq-translated; a literal comma in the slug must not break re-parsing."""
    assert scan_filter(QUEUE_FILTERS, ["post_slug:eq:foo\\,bar"]) is None
