"""Output contract tests for the command layer."""

import json

import pytest

from vinted_cli.main import TABLE_COLUMNS, _render, _requested_fields

ROWS = [
    {
        "id": 1,
        "title": "LEGO city",
        "brand": "LEGO",
        "price": "12.0",
        "currency": "USD",
        "condition": "Very good",
        "url": "https://www.vinted.com/items/1-lego-city",
        "size": "M",
    }
]


def test_requested_fields_parses_and_trims():
    assert _requested_fields("id, title ,price") == ["id", "title", "price"]


@pytest.mark.parametrize("value", [None, "", "   ", ",", " , , "])
def test_requested_fields_returns_none_when_nothing_was_requested(value):
    assert _requested_fields(value) is None


def test_render_table_drops_no_requested_column_at_the_print_table_ceiling():
    """Guard the count that triggers the truncation this test protects against."""
    assert len(TABLE_COLUMNS) == 6


def test_render_json_emits_every_field(capsys):
    _render(ROWS, table=False, properties=None, empty="none")

    payload = json.loads(capsys.readouterr().out)
    assert payload == ROWS


def test_render_json_projects_only_the_requested_fields(capsys):
    _render(ROWS, table=False, properties="id,url", empty="none")

    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"id": 1, "url": "https://www.vinted.com/items/1-lego-city"}]


def test_render_table_shows_every_requested_property(capsys):
    """print_table drops columns past its sixth by default.

    A user who names eight fields must see eight, not six.
    """
    _render(
        ROWS,
        table=True,
        properties="id,title,brand,price,currency,condition,url,size",
        empty="none",
    )

    out = capsys.readouterr().out
    for field in ("id", "title", "brand", "price", "currency", "condition", "url", "size"):
        assert field in out, f"table output dropped the requested column {field}"


def test_render_table_uses_the_default_columns_without_properties(capsys):
    _render(ROWS, table=True, properties=None, empty="none")

    out = capsys.readouterr().out
    for column in TABLE_COLUMNS:
        assert column.replace("_", " ").title() in out
    assert "https://www.vinted.com" not in out


def test_render_table_reports_an_empty_result_on_stderr(capsys):
    """stdout carries data only. A human message belongs on stderr."""
    _render([], table=True, properties=None, empty="No listings found.")

    captured = capsys.readouterr()
    assert "No listings found." in captured.err
    assert captured.out == ""


def test_render_json_emits_an_empty_list_rather_than_a_message(capsys):
    _render([], table=False, properties=None, empty="No listings found.")

    assert json.loads(capsys.readouterr().out) == []
