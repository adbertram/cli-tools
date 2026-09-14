"""Regression tests for `podio item list` filter handling."""
import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from podio_cli.commands import item


runner = CliRunner()


def _make_client(result):
    client = MagicMock()
    client.Item.filter.return_value = result
    return client


def _filter_attributes(client):
    assert client.Item.filter.called, "Item.filter was not called"
    _, kwargs = client.Item.filter.call_args
    return kwargs["attributes"]


def _items_response(items):
    return {"total": len(items), "filtered": len(items), "items": items}


def test_documented_field_op_value_filter_returns_matching_items(monkeypatch):
    items = [
        {"item_id": 11, "title": "Coding-Agent Governance", "status": "active"},
        {"item_id": 22, "title": "Unrelated item", "status": "active"},
    ]
    client = _make_client(_items_response(items))
    monkeypatch.setattr(item, "get_client", lambda: client)

    result = runner.invoke(
        item.app,
        [
            "list",
            "30529466",
            "--filter",
            "title:contains:Coding-Agent Governance",
            "--properties",
            "item_id,title,status",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["items"] == [items[0]]
    assert "filters" not in _filter_attributes(client)


@pytest.mark.parametrize(
    ("filter_expression", "expected_item_ids"),
    [
        ("status:eq:active", [11, 22]),
        ("score:gt:10", [23]),
        ("status:in:active|pending", [11, 12, 22]),
        ("status:ne:archived", [11, 12, 22]),
        ("deleted_at:null", [11, 22, 23]),
        ("title:startswith:Alpha", [11]),
        ("title:endswith:Omega", [12]),
        ("score:gte:10,status:ne:archived", [12]),
    ],
)
def test_supported_operators_filter_item_results(
    monkeypatch,
    filter_expression,
    expected_item_ids,
):
    items = [
        {"item_id": 11, "title": "Alpha report", "status": "active", "score": 5},
        {
            "item_id": 12,
            "title": "Beta Omega",
            "status": "pending",
            "score": 10,
            "deleted_at": "2026-01-01",
        },
        {"item_id": 22, "title": "Gamma", "status": "active", "score": 7},
        {"item_id": 23, "title": "Delta", "status": "archived", "score": 20},
    ]
    client = _make_client(_items_response(items))
    monkeypatch.setattr(item, "get_client", lambda: client)

    result = runner.invoke(item.app, ["list", "30529466", "--filter", filter_expression])

    assert result.exit_code == 0
    actual_ids = [record["item_id"] for record in json.loads(result.stdout)["items"]]
    assert actual_ids == expected_item_ids


def test_json_object_filter_remains_server_side(monkeypatch):
    server_filter = {"status": ["active"], "title": "Exact title"}
    items = [{"item_id": 11, "title": "Exact title", "status": "active"}]
    client = _make_client(_items_response(items))
    monkeypatch.setattr(item, "get_client", lambda: client)

    result = runner.invoke(
        item.app,
        ["list", "30529466", "--filter", json.dumps(server_filter)],
    )

    assert result.exit_code == 0
    assert _filter_attributes(client)["filters"] == server_filter
    assert json.loads(result.stdout)["items"] == items


def test_invalid_json_filter_exits_nonzero(monkeypatch):
    client = _make_client(_items_response([]))
    monkeypatch.setattr(item, "get_client", lambda: client)

    result = runner.invoke(item.app, ["list", "30529466", "--filter", '{"status":'])

    assert result.exit_code == 1
    assert "Invalid JSON in --filter" in result.stderr
    assert not client.Item.filter.called
