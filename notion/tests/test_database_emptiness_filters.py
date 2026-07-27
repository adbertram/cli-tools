"""Regression coverage for `null` / `notnull` filters on `database page list`.

Notion nests the emptiness condition under the property's type key, for example
{"property": "Keywords", "rich_text": {"is_empty": true}}. The builder used to
emit a flat {"property": ..., "is_empty": ...} body, and the Notion API rejected
it with HTTP 400 "body failed validation".
"""
import pytest
from typer.testing import CliRunner

from cli_tools_shared.filters import FilterValidationError

from notion_cli.commands import database as database_cmd


SCHEMA = {
    "Keywords": "rich_text",
    "Title": "title",
    "Category": "select",
    "Status": "status",
    "Tags": "multi_select",
    "Word Count": "number",
    "Published URL": "url",
    "Instructors": "relation",
    "Publish Date": "date",
    "Promoted": "checkbox",
    "Excerpt Length": "formula",
}


def build(filter_string):
    return database_cmd.build_filter_from_standard([filter_string], schema=SCHEMA)


@pytest.mark.parametrize(
    "field,prop_type",
    [
        ("Keywords", "rich_text"),
        ("Title", "title"),
        ("Category", "select"),
        ("Status", "status"),
        ("Tags", "multi_select"),
        ("Word Count", "number"),
        ("Published URL", "url"),
        ("Instructors", "relation"),
    ],
)
def test_null_nests_is_empty_under_the_property_type(field, prop_type):
    assert build(f"{field}:null") == {
        "property": field,
        prop_type: {"is_empty": True},
    }


@pytest.mark.parametrize(
    "field,prop_type",
    [
        ("Keywords", "rich_text"),
        ("Category", "select"),
        ("Status", "status"),
    ],
)
def test_notnull_nests_is_not_empty_under_the_property_type(field, prop_type):
    assert build(f"{field}:notnull") == {
        "property": field,
        prop_type: {"is_not_empty": True},
    }


def test_emptiness_condition_is_never_flat():
    """The 400-producing shape must not come back."""
    assert "is_empty" not in build("Keywords:null")


def test_checkbox_property_rejects_null_and_names_its_operators():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Promoted:null")

    message = str(excinfo.value)
    assert "'Promoted'" in message
    assert "type: checkbox" in message
    assert "Supported operators: eq, ne." in message


def test_formula_property_rejects_notnull_and_names_the_valid_types():
    with pytest.raises(FilterValidationError) as excinfo:
        build("Excerpt Length:notnull")

    message = str(excinfo.value)
    assert "'Excerpt Length'" in message
    assert "type: formula" in message
    assert "rich_text" in message


def test_date_property_keeps_its_own_presence_operators():
    assert build("Publish Date:null") == {
        "property": "Publish Date",
        "date": {"is_empty": True},
    }


def test_emptiness_filter_combines_with_other_property_filters():
    assert database_cmd.build_filter_from_standard(
        ["Keywords:null", "Status:eq:Published"],
        schema=SCHEMA,
    ) == {
        "and": [
            {"property": "Keywords", "rich_text": {"is_empty": True}},
            {"property": "Status", "status": {"equals": "Published"}},
        ]
    }


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


def test_page_list_sends_the_nested_emptiness_filter_to_the_api(monkeypatch):
    client = SchemaClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["list", "-d", "db-posts", "--filter", "Keywords:null", "--limit", "2"],
    )

    assert result.exit_code == 0
    assert client.queries[0]["filter_obj"] == {
        "property": "Keywords",
        "rich_text": {"is_empty": True},
    }


def test_page_list_rejects_checkbox_null_without_calling_the_api(monkeypatch):
    client = SchemaClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["list", "-d", "db-posts", "--filter", "Promoted:null"],
    )

    assert result.exit_code == 1
    assert client.queries == []
    assert "type: checkbox" in result.stderr
