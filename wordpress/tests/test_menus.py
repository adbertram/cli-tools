"""Tests for WordPress navigation menu support."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner

from wordpress_cli.client import WordPressClient
from wordpress_cli.commands import menus


def test_resolve_menu_id_from_location():
    client = WordPressClient.__new__(WordPressClient)
    client.list_menu_locations = MagicMock(return_value={"main_menu": {"menu": 134}})

    assert client.resolve_menu_id(location="main_menu") == 134


def test_resolve_menu_id_rejects_unassigned_location():
    client = WordPressClient.__new__(WordPressClient)
    client.list_menu_locations = MagicMock(return_value={"footer": {"menu": 0}})

    with pytest.raises(ClientError, match="Menu location has no assigned menu: footer"):
        client.resolve_menu_id(location="footer")


def test_add_page_to_menu_returns_existing_item_without_duplicate_post():
    client = WordPressClient.__new__(WordPressClient)
    existing = {
        "id": 10,
        "type": "post_type",
        "object": "page",
        "object_id": 27009,
        "menus": 134,
    }
    client.list_menu_items = MagicMock(return_value=[existing])
    client._make_request = MagicMock()

    result = client.add_page_to_menu(page_id=27009, menu_id=134, title="About Adam")

    assert result == {"created": False, "menu_id": 134, "item": existing}
    client._make_request.assert_not_called()


def test_add_page_to_menu_posts_menu_item_payload():
    client = WordPressClient.__new__(WordPressClient)
    created = {"id": 44, "object_id": 27009, "menus": 134}
    client.list_menu_items = MagicMock(return_value=[])
    client._make_request = MagicMock(return_value=created)

    result = client.add_page_to_menu(
        page_id=27009,
        menu_id=134,
        title="About Adam",
        menu_order=8,
    )

    assert result == {"created": True, "menu_id": 134, "item": created}
    client._make_request.assert_called_once_with(
        "POST",
        "/menu-items",
        data={
            "status": "publish",
            "type": "post_type",
            "object": "page",
            "object_id": 27009,
            "menus": 134,
            "parent": 0,
            "title": "About Adam",
            "menu_order": 8,
        },
    )


def test_menu_add_page_command_prints_json(monkeypatch):
    class FakeClient:
        def resolve_menu_id(self, *, menu=None, location=None):
            assert menu is None
            assert location == "main_menu"
            return 134

        def add_page_to_menu(self, *, page_id, menu_id, title=None, menu_order=None):
            assert page_id == 27009
            assert menu_id == 134
            assert title == "About Adam"
            assert menu_order == 8
            return {"created": True, "menu_id": menu_id, "item": {"id": 44}}

    monkeypatch.setattr(menus, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(
        menus.app,
        ["add-page", "27009", "--location", "main_menu", "--title", "About Adam", "--menu-order", "8"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"created": True, "menu_id": 134, "item": {"id": 44}}
