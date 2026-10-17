"""Regression tests for Notion property argument mapping."""

from __future__ import annotations

import json
import subprocess

import pytest

from ata_blog_cli.client import AtaBlogClient, ClientError


# Live-schema property types used to drive update_article in these tests.
# Mirrors the real ATA Blog Notion database schema shape returned by
# `notion database schema <db_id>`.
_SCHEMA_PROPERTY_TYPES = {
    "Title": "title",
    "Keywords": "rich_text",
    "Excerpt": "rich_text",
    "Tags": "multi_select",
    "Category": "select",
    "Status": "status",
    "Published URL": "url",
    "X Post URL": "url",
    "LinkedIn Post URL": "url",
    "Promoted": "checkbox",
    "Author Paid": "checkbox",
    "Publish Date": "date",
    "Minimum Word Count": "number",
}


def _make_client(captured_args):
    """Build a client that records notion args and serves a fixed schema."""
    client = object.__new__(AtaBlogClient)
    client._property_types_cache = dict(_SCHEMA_PROPERTY_TYPES)

    def fake_run_notion(args):
        captured_args.append(args)
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({"ok": True}), stderr=""
        )

    client._run_notion = fake_run_notion
    return client


def _properties_payload(captured_args):
    """Extract the JSON object passed after --properties in the last call."""
    args = captured_args[-1]
    idx = args.index("--properties")
    return json.loads(args[idx + 1])


def test_social_post_urls_are_sent_as_notion_url_properties() -> None:
    """Non-empty URL fields must produce Notion url property payloads."""
    captured_args = []
    client = _make_client(captured_args)

    result = client.update_article(
        "page123",
        properties={
            "X Post URL": "https://x.com/i/web/status/tweet123",
            "LinkedIn Post URL": "https://www.linkedin.com/feed/update/urn:li:activity:123/",
        },
    )

    assert result == {"ok": True}
    assert captured_args[-1][:4] == ["database", "page", "update", "page123"]
    payload = _properties_payload(captured_args)
    assert payload == {
        "X Post URL": {"url": "https://x.com/i/web/status/tweet123"},
        "LinkedIn Post URL": {
            "url": "https://www.linkedin.com/feed/update/urn:li:activity:123/"
        },
    }


def test_empty_url_clears_to_null() -> None:
    """An empty url value must send url:null, not url:'' (Notion 400 fix)."""
    captured_args = []
    client = _make_client(captured_args)

    client.update_article("page123", properties={"Published URL": ""})

    payload = _properties_payload(captured_args)
    assert payload == {"Published URL": {"url": None}}


def test_empty_rich_text_clears_to_empty_list() -> None:
    """An empty rich_text value must send rich_text:[]."""
    captured_args = []
    client = _make_client(captured_args)

    client.update_article("page123", properties={"Keywords": ""})

    payload = _properties_payload(captured_args)
    assert payload == {"Keywords": {"rich_text": []}}


def test_empty_multi_select_clears_to_empty_list() -> None:
    """An empty multi_select value must send multi_select:[]."""
    captured_args = []
    client = _make_client(captured_args)

    client.update_article("page123", properties={"Tags": ""})

    payload = _properties_payload(captured_args)
    assert payload == {"Tags": {"multi_select": []}}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("yes", True),
        ("1", True),
        ("false", False),
        ("False", False),
        ("no", False),
        ("0", False),
    ],
)
def test_checkbox_boolean_coercion(value, expected) -> None:
    """Checkbox values coerce to real booleans in a checkbox payload."""
    captured_args = []
    client = _make_client(captured_args)

    client.update_article("page123", properties={"Promoted": value})

    payload = _properties_payload(captured_args)
    assert payload == {"Promoted": {"checkbox": expected}}


def test_ambiguous_checkbox_is_rejected() -> None:
    """Ambiguous checkbox values fail fast instead of defaulting."""
    captured_args = []
    client = _make_client(captured_args)

    with pytest.raises(ClientError, match="ambiguous boolean"):
        client.update_article("page123", properties={"Promoted": "maybe"})

    # Nothing should be sent to notion when coercion fails.
    assert captured_args == []


def test_clearing_url_and_setting_checkbox_in_one_call() -> None:
    """The original failing reproduction must build a valid payload."""
    captured_args = []
    client = _make_client(captured_args)

    client.update_article(
        "page123",
        properties={
            "Published URL": "",
            "X Post URL": "",
            "Promoted": "false",
        },
    )

    payload = _properties_payload(captured_args)
    assert payload == {
        "Published URL": {"url": None},
        "X Post URL": {"url": None},
        "Promoted": {"checkbox": False},
    }


def test_unknown_property_is_rejected() -> None:
    """Updating a property absent from the schema fails fast."""
    captured_args = []
    client = _make_client(captured_args)

    with pytest.raises(ClientError, match="Unknown property"):
        client.update_article("page123", properties={"Not A Real Prop": "x"})

    assert captured_args == []


def test_number_property_coercion() -> None:
    """Number properties coerce integer-valued strings to ints."""
    captured_args = []
    client = _make_client(captured_args)

    client.update_article("page123", properties={"Minimum Word Count": "1500"})

    payload = _properties_payload(captured_args)
    assert payload == {"Minimum Word Count": {"number": 1500}}
