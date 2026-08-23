"""Tests for `notion database create` (client + command).

The Notion API is never hit: the NotionClient's `_make_request` is replaced
with a fake that records the request and returns a canned create-database
response shaped like API 2025-09-03.
"""
import json

import pytest

from notion_cli.client import NotionClient
from notion_cli.commands import database as database_cmd


def make_client(captured):
    """Build a NotionClient whose _make_request is captured (no live API)."""
    client = NotionClient.__new__(NotionClient)

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        captured.append({"method": method, "endpoint": endpoint, "data": data})
        return {
            "object": "database",
            "id": "db-container-1",
            "url": "https://www.notion.so/db-container-1",
            "is_inline": (data or {}).get("is_inline", False),
            "data_sources": [{"id": "ds-1", "name": "New Tasks"}],
        }

    client._make_request = fake_make_request
    return client


# --------------------------------------------------------------------------
# Client-level: create_database body shape
# --------------------------------------------------------------------------


def test_create_database_posts_initial_data_source_properties():
    captured = []
    client = make_client(captured)

    properties = {
        "Name": {"title": {}},
        "Priority": {"select": {"options": [{"name": "High"}]}},
    }

    result = client.create_database(
        parent_page_id="parent-page-1",
        title="New Tasks",
        properties=properties,
        inline=True,
    )

    assert len(captured) == 1
    req = captured[0]
    assert req["method"] == "POST"
    assert req["endpoint"] == "/databases"

    body = req["data"]
    assert body["parent"] == {"type": "page_id", "page_id": "parent-page-1"}
    assert body["title"] == [{"type": "text", "text": {"content": "New Tasks"}}]
    # Properties MUST nest under initial_data_source.properties (not top-level).
    assert "properties" not in body
    assert body["initial_data_source"]["properties"] == properties
    assert body["is_inline"] is True

    # Response surfaces container id + data_sources array.
    assert result["id"] == "db-container-1"
    assert result["data_sources"] == [{"id": "ds-1", "name": "New Tasks"}]


def test_create_database_defaults_to_not_inline():
    captured = []
    client = make_client(captured)

    client.create_database(
        parent_page_id="parent-page-1",
        title="Plain DB",
        properties={"Name": {"title": {}}},
    )

    assert captured[0]["data"]["is_inline"] is False


# --------------------------------------------------------------------------
# Command-level: flag parsing -> properties -> client -> output
# --------------------------------------------------------------------------


def run_create(monkeypatch, captured, **overrides):
    """Invoke database_create with a captured client and printed output."""
    client = make_client(captured)
    printed_json = []

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_json", printed_json.append)
    monkeypatch.setattr(database_cmd, "print_success", lambda message: None)

    kwargs = dict(
        parent_page_id="parent-page-1",
        title="Tasks",
        title_property="Name",
        inline=False,
        properties_json=None,
        text_props=None,
        number_props=None,
        select_props=None,
        multi_select_props=None,
        status_props=None,
        date_props=None,
        checkbox_props=None,
        url_props=None,
        email_props=None,
        phone_props=None,
        people_props=None,
        files_props=None,
        relation_props=None,
        relation_type="dual_property",
    )
    kwargs.update(overrides)
    database_cmd.database_create(**kwargs)
    return captured, printed_json


def sent_properties(captured):
    return captured[0]["data"]["initial_data_source"]["properties"]


def test_command_adds_default_title_property_when_none_given(monkeypatch):
    captured, printed = run_create(monkeypatch, [])

    props = sent_properties(captured)
    assert props == {"Name": {"title": {}}}

    out = printed[0]
    assert out["id"] == "db-container-1"
    assert out["data_source_ids"] == ["ds-1"]
    assert out["data_sources"] == [{"id": "ds-1", "name": "New Tasks"}]
    assert out["url"] == "https://www.notion.so/db-container-1"


def test_command_builds_choice_property_with_options(monkeypatch):
    captured, _ = run_create(
        monkeypatch,
        [],
        status_props=["Phase:Todo|Doing|Done"],
        select_props=["Priority:High|Low"],
        date_props=["Due"],
    )

    props = sent_properties(captured)
    assert props["Phase"] == {
        "status": {"options": [{"name": "Todo"}, {"name": "Doing"}, {"name": "Done"}]}
    }
    assert props["Priority"] == {
        "select": {"options": [{"name": "High"}, {"name": "Low"}]}
    }
    assert props["Due"] == {"date": {}}
    # Title still auto-added.
    assert props["Name"] == {"title": {}}


def test_command_relation_uses_target_data_source_id(monkeypatch):
    captured, _ = run_create(
        monkeypatch,
        [],
        relation_props=["Project:target-ds-99"],
        relation_type="single_property",
    )

    props = sent_properties(captured)
    assert props["Project"] == {
        "relation": {
            "data_source_id": "target-ds-99",
            "type": "single_property",
            "single_property": {},
        }
    }


def test_command_merges_raw_properties_json(monkeypatch):
    captured, _ = run_create(
        monkeypatch,
        [],
        properties_json=json.dumps({"Notes": {"rich_text": {}}}),
        number_props=["Score"],
    )

    props = sent_properties(captured)
    assert props["Notes"] == {"rich_text": {}}
    assert props["Score"] == {"number": {}}
    # No title in JSON or flags -> default title property added.
    assert props["Name"] == {"title": {}}


def test_command_keeps_title_from_raw_properties_json(monkeypatch):
    captured, _ = run_create(
        monkeypatch,
        [],
        title_property="Name",
        properties_json=json.dumps({"Task": {"title": {}}}),
    )

    props = sent_properties(captured)
    # User-defined title kept; no extra "Name" title property added.
    assert props["Task"] == {"title": {}}
    assert "Name" not in props


def test_command_inline_flag_forwarded(monkeypatch):
    captured, _ = run_create(monkeypatch, [], inline=True)
    assert captured[0]["data"]["is_inline"] is True


def test_command_invalid_relation_format_exits(monkeypatch):
    import typer

    with pytest.raises(typer.Exit) as exc:
        run_create(monkeypatch, [], relation_props=["NoColonHere"])
    assert exc.value.exit_code == 1


def test_command_invalid_properties_json_exits(monkeypatch):
    import typer

    with pytest.raises(typer.Exit) as exc:
        run_create(monkeypatch, [], properties_json="{not json")
    assert exc.value.exit_code == 1


def test_build_create_property_schema_rejects_unknown_type():
    with pytest.raises(ValueError):
        database_cmd.build_create_property_schema("title")
