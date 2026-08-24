"""Regression coverage for date-property filters on `database page list`.

Notion date properties accept their own operator vocabulary (equals, before,
after, on_or_before, on_or_after, the relative ranges, and the presence
checks). Mapping a generic comparison operator onto a number operator such as
`greater_than_or_equal_to` produced a 400 from the Notion API.
"""
import pytest
from typer.testing import CliRunner

from cli_tools_shared.filters import FilterValidationError

from notion_cli.commands import database as database_cmd


SCHEMA = {
    "Publish Date": "date",
    "Status": "status",
    "Title": "title",
    "Word Count": "number",
}


def build(filter_string):
    return database_cmd.build_filter_from_standard([filter_string], schema=SCHEMA)


@pytest.mark.parametrize(
    "filter_string,expected_operator",
    [
        ("Publish Date:equals:2026-07-20", "equals"),
        ("Publish Date:before:2026-07-20", "before"),
        ("Publish Date:after:2026-07-20", "after"),
        ("Publish Date:on_or_before:2026-07-20", "on_or_before"),
        ("Publish Date:on_or_after:2026-07-20", "on_or_after"),
    ],
)
def test_native_date_operators_build_date_conditions(filter_string, expected_operator):
    assert build(filter_string) == {
        "property": "Publish Date",
        "date": {expected_operator: "2026-07-20"},
    }


@pytest.mark.parametrize(
    "alias,expected_operator",
    [
        ("eq", "equals"),
        ("gt", "after"),
        ("gte", "on_or_after"),
        ("lt", "before"),
        ("lte", "on_or_before"),
    ],
)
def test_generic_aliases_map_to_notion_date_operators(alias, expected_operator):
    assert build(f"Publish Date:{alias}:2026-07-20") == {
        "property": "Publish Date",
        "date": {expected_operator: "2026-07-20"},
    }


@pytest.mark.parametrize(
    "filter_string,expected_operator",
    [
        ("Publish Date:is_empty:true", "is_empty"),
        ("Publish Date:is_not_empty:true", "is_not_empty"),
        ("Publish Date:is_not_empty", "is_not_empty"),
        ("Publish Date:null", "is_empty"),
        ("Publish Date:notnull", "is_not_empty"),
    ],
)
def test_presence_operators_send_boolean_true(filter_string, expected_operator):
    assert build(filter_string) == {
        "property": "Publish Date",
        "date": {expected_operator: True},
    }


@pytest.mark.parametrize(
    "filter_string,expected_operator",
    [
        ("Publish Date:past_week", "past_week"),
        ("Publish Date:this_week:true", "this_week"),
        ("Publish Date:next_month", "next_month"),
        ("Publish Date:past_year", "past_year"),
    ],
)
def test_relative_operators_send_empty_object(filter_string, expected_operator):
    assert build(filter_string) == {
        "property": "Publish Date",
        "date": {expected_operator: {}},
    }


def test_unknown_date_operator_is_rejected_locally():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Publish Date:ilike:%2026%")

    message = str(excinfo.value)
    assert "Publish Date" in message
    assert "type: date" in message
    assert "on_or_after" in message
    assert "gte=on_or_after" in message


def test_unrecognized_operator_token_is_rejected_before_the_api_call():
    """`Publish Date:sometime:2026-07-20` must not reach Notion as an equals filter.

    The shared validator now rejects the unknown operator token itself, so the
    error names the operator instead of the value it used to be folded into.
    """
    with pytest.raises(FilterValidationError) as excinfo:
        build("Publish Date:sometime:2026-07-20")

    message = str(excinfo.value)
    assert "Unknown operator 'sometime'" in message
    # The Notion-native date operators stay listed as supported.
    assert "on_or_after" in message


@pytest.mark.parametrize(
    "value",
    ["2026-07-20", "2026-07-20T09:00:00.000+00:00", "2026-07-20T09:00:00Z", "today"],
)
def test_accepted_date_values(value):
    assert build(f"Publish Date:on_or_after:{value}") == {
        "property": "Publish Date",
        "date": {"on_or_after": value},
    }


def test_implicit_equals_accepts_a_bare_iso_date():
    assert build("Publish Date:2026-07-20") == {
        "property": "Publish Date",
        "date": {"equals": "2026-07-20"},
    }


def test_date_value_operator_requires_a_value():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Publish Date:on_or_after")

    assert "requires an ISO 8601 date value" in str(excinfo.value)


def test_relative_operator_rejects_a_supplied_value():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Publish Date:past_week:2026-07-20")

    assert "takes no value" in str(excinfo.value)


def test_property_missing_from_schema_is_rejected():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Ship Date:on_or_after:2026-07-20")

    message = str(excinfo.value)
    assert "'Ship Date' does not exist in the database schema" in message
    assert "Publish Date" in message


def test_date_filter_combines_with_other_property_filters():
    assert database_cmd.build_filter_from_standard(
        ["Publish Date:gte:2026-07-20", "Status:eq:Published"],
        schema=SCHEMA,
    ) == {
        "and": [
            {"property": "Publish Date", "date": {"on_or_after": "2026-07-20"}},
            {"property": "Status", "status": {"equals": "Published"}},
        ]
    }


def test_two_sided_date_range_translates_both_bounds():
    """The weekly-quota shape: gte+lte on one date property must become
    Notion-native on_or_after + on_or_before conditions, never number-style
    comparison keys the API rejects with a 400."""
    assert database_cmd.build_filter_from_standard(
        ["Publish Date:gte:2026-08-24", "Publish Date:lte:2026-08-30"],
        schema=SCHEMA,
    ) == {
        "and": [
            {"property": "Publish Date", "date": {"on_or_after": "2026-08-24"}},
            {"property": "Publish Date", "date": {"on_or_before": "2026-08-30"}},
        ]
    }


def test_number_property_still_uses_number_comparison_operators():
    assert build("Word Count:gte:1000") == {
        "property": "Word Count",
        "number": {"greater_than_or_equal_to": 1000.0},
    }


def test_comparison_operator_on_text_property_is_rejected():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Title:gte:abc")

    message = str(excinfo.value)
    assert "'Title'" in message
    assert "type: title" in message


def test_unsupported_generic_operator_is_rejected_instead_of_skipped():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Title:startswith:Azure")

    message = str(excinfo.value)
    assert "'startswith'" in message
    assert "type: title" in message
    assert "eq" in message


class SchemaClient:
    """Minimal client stub exposing the two calls `page list` makes."""

    def __init__(self):
        self.queries = []

    def get_database(self, database_id, data_source_id=None):
        return {
            "properties": {name: {"type": ptype} for name, ptype in SCHEMA.items()}
        }

    def query_database_all(self, **kwargs):
        self.queries.append(kwargs)
        return []


def test_page_list_sends_date_filter_to_the_api(monkeypatch):
    client = SchemaClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["list", "-d", "db-posts", "--filter", "Publish Date:gte:2026-07-20", "--limit", "25"],
    )

    assert result.exit_code == 0
    assert client.queries[0]["filter_obj"] == {
        "property": "Publish Date",
        "date": {"on_or_after": "2026-07-20"},
    }


def test_page_list_rejects_unknown_date_operator_without_calling_the_api(monkeypatch):
    client = SchemaClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["list", "-d", "db-posts", "--filter", "Publish Date:contains:2026"],
    )

    assert result.exit_code == 1
    assert client.queries == []
    assert "is not valid for date property 'Publish Date'" in result.stderr
