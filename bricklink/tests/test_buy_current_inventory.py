"""Local inventory lookup against an isolated SQLite store, with no credentials."""

import json
import socket
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bricklink_cli.buy import service as service_module
from bricklink_cli.buy.store import BuyStore
from bricklink_cli.commands import buy


@pytest.fixture
def inventory_app(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Local inventory lookup must not access credentials or network")

    monkeypatch.setattr(service_module, "get_config", lambda: SimpleNamespace(storage_dir=tmp_path))
    monkeypatch.setattr(service_module, "_default_cookie_jar", forbidden)
    monkeypatch.setattr(service_module, "BrickLinkBuyHttpClient", forbidden)
    monkeypatch.setattr(service_module.BuyService, "ensure_seeded", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    store = BuyStore(tmp_path / "buy" / "buy.sqlite3")
    store.replace_lots_for_item(
        item_type="PART", item_no="3001", id_item=264,
        lots=[
            {"id_inv": 123456, "qty": 5, "price_display": "US $1.50", "store_name": "Fixture store"},
            {"id_inv": 789012, "qty": 9, "price_display": "US $0.50", "store_name": "Other fixture"},
        ],
    )
    return buy.current_inventory_app


def test_get_saved_inventory_lot_by_exact_id(inventory_app):
    result = CliRunner().invoke(inventory_app, ["get", "123456"])
    assert result.exit_code == 0, result.output
    lot = json.loads(result.stdout)
    assert lot["id_inv"] == 123456
    assert lot["qty"] == 5
    assert lot["store"] == "Fixture store"


def test_get_missing_inventory_lot_fails_explicitly(inventory_app):
    result = CliRunner().invoke(inventory_app, ["get", "999999"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Inventory lot 999999 was not found in local inventory." in result.stderr


def test_get_saved_inventory_lot_as_table(inventory_app):
    result = CliRunner().invoke(inventory_app, ["get", "123456", "--table"])
    assert result.exit_code == 0, result.output
    assert "123456" in result.stdout
    assert "Fixture store" in result.stdout


def test_get_inventory_lot_rejects_nonpositive_id(inventory_app):
    result = CliRunner().invoke(inventory_app, ["get", "0"])
    assert result.exit_code == 2


def test_http_client_is_initialized_once_on_first_remote_access(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module, "get_config", lambda: SimpleNamespace(storage_dir=tmp_path))
    cookie_jar = tmp_path / "cookies.txt"
    calls = []
    client = object()
    monkeypatch.setattr(service_module, "_default_cookie_jar", lambda: cookie_jar)

    def create_client(**kwargs):
        calls.append(kwargs)
        return client

    monkeypatch.setattr(service_module, "BrickLinkBuyHttpClient", create_client)
    service = service_module.BuyService()
    assert calls == []
    assert service.client is client
    assert service.client is client
    assert calls == [{"cookie_jar_path": str(cookie_jar)}]
