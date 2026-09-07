"""Tests for batched Mercari item detail reads."""

import json

import pytest
from typer.testing import CliRunner

from mercari_cli import client as client_module
from mercari_cli import main
from mercari_cli.client import (
    ClientError,
    MercariChallengeError,
    MercariItemNotFoundError,
)


def test_get_items_reuses_one_page_and_preserves_order(monkeypatch):
    client = client_module.MercariClient.__new__(client_module.MercariClient)
    pages = []
    calls = []

    def fake_app_shell(url):
        pages.append(url)
        return "PAGE"

    def fake_fetch(page, item_id):
        calls.append((page, item_id))
        if item_id == "m22222222222":
            raise MercariItemNotFoundError("not found")
        return {"id": item_id}

    monkeypatch.setattr(client, "_app_shell", fake_app_shell)
    monkeypatch.setattr(client, "_fetch_item_from_page", fake_fetch)
    monkeypatch.setattr(client_module, "normalize_item_detail", lambda item: item)

    rows = client.get_items(
        ["m11111111111", "m22222222222", "bad", "m33333333333"]
    )

    assert pages == [client_module.HOME_URL]
    assert calls == [
        ("PAGE", "m11111111111"),
        ("PAGE", "m22222222222"),
        ("PAGE", "m33333333333"),
    ]
    assert rows == [
        {
            "item_id": "m11111111111",
            "status": "ok",
            "item": {"id": "m11111111111"},
        },
        {
            "item_id": "m22222222222",
            "status": "error",
            "error_kind": "not_found",
            "error": "not found",
        },
        {
            "item_id": "bad",
            "status": "error",
            "error_kind": "unreadable",
            "error": "Invalid Mercari item id 'bad'. Expected an id like 'm12345678901' or an item URL.",
        },
        {
            "item_id": "m33333333333",
            "status": "ok",
            "item": {"id": "m33333333333"},
        },
    ]


def test_get_items_aborts_on_human_challenge(monkeypatch):
    client = client_module.MercariClient.__new__(client_module.MercariClient)
    calls = []
    monkeypatch.setattr(client, "_app_shell", lambda _url: "PAGE")

    def fake_fetch(_page, item_id):
        calls.append(item_id)
        if item_id == "m22222222222":
            raise MercariChallengeError("human verification challenge")
        return {"id": item_id}

    monkeypatch.setattr(client, "_fetch_item_from_page", fake_fetch)
    monkeypatch.setattr(client_module, "normalize_item_detail", lambda item: item)

    with pytest.raises(MercariChallengeError, match="human verification challenge"):
        client.get_items(["m11111111111", "m22222222222", "m33333333333"])

    assert calls == ["m11111111111", "m22222222222"]


def test_missing_item_response_uses_not_found_error_class(monkeypatch):
    client = client_module.MercariClient.__new__(client_module.MercariClient)
    monkeypatch.setattr(
        client,
        "_capture",
        lambda *_args, **_kwargs: [{"data": {"item": None}}],
    )

    with pytest.raises(MercariItemNotFoundError, match="m11111111111.*not found"):
        client._fetch_item_from_page("PAGE", "m11111111111")


def test_get_many_command_returns_stable_records(monkeypatch):
    class FakeClient:
        def get_items(self, item_ids, *, status_only=False):
            return [
                {
                    "item_id": item_id,
                    "status": "ok",
                    "item": {"id": item_id, "name": "LEGO"},
                }
                for item_id in item_ids
            ]

        def close(self):
            return None

    monkeypatch.setattr(main, "get_client", FakeClient)

    result = CliRunner().invoke(
        main.listings_app,
        ["get-many", "m11111111111", "m22222222222", "--properties", "id"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "item_id": "m11111111111",
            "status": "ok",
            "item": {"id": "m11111111111"},
        },
        {
            "item_id": "m22222222222",
            "status": "ok",
            "item": {"id": "m22222222222"},
        },
    ]


def test_get_many_rejects_oversized_batch_before_starting_browser(monkeypatch):
    def fail_if_called():
        raise AssertionError("browser client must not start for an oversized batch")

    monkeypatch.setattr(main, "get_client", fail_if_called)
    item_ids = [f"m{index:011d}" for index in range(main.MAX_GET_MANY_ITEMS + 1)]

    result = CliRunner().invoke(main.listings_app, ["get-many", *item_ids])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        f"Error: get-many accepts at most {main.MAX_GET_MANY_ITEMS} item IDs; "
        f"received {main.MAX_GET_MANY_ITEMS + 1}.\n"
    )


def test_get_items_isolates_bad_pricing_and_preserves_valid_siblings(monkeypatch):
    client = client_module.MercariClient.__new__(client_module.MercariClient)
    ids = ["m11111111111", "m22222222222", "m33333333333"]
    calls = []

    def fetch(_page, item_id):
        calls.append(item_id)
        return {
            "itemId": item_id, "status": "on_sale", "price": 100,
            "priceSummary": {
                "totalPrice": 110,
                "headline": None if item_id == ids[1] else "+$0.10 Buyer Protection fee",
            },
        }

    monkeypatch.setattr(client, "_app_shell", lambda _url: "PAGE")
    monkeypatch.setattr(client, "_fetch_item_from_page", fetch)
    rows = client.get_items(ids)

    assert calls == ids
    assert [row["item_id"] for row in rows] == ids
    assert [row["status"] for row in rows] == ["ok", "error", "ok"]
    assert rows[1]["error_kind"] == "unreadable"
    assert "priceSummary.headline" in rows[1]["error"]
    assert "item" not in rows[1]
    assert rows[0]["item"]["buyer_protection_fee_cents"] == 10
    assert rows[2]["item"]["buyer_protection_fee_cents"] == 10


@pytest.mark.parametrize("status", ["on_sale", "sold_out", "trading"])
def test_status_only_reads_uncached_status_without_pricing(monkeypatch, status):
    client = client_module.MercariClient.__new__(client_module.MercariClient)
    item_id = "m11111111111"
    raw = {"itemId": item_id, "status": status, "lastSoldAt": 1788676849}
    monkeypatch.setattr(client, "_app_shell", lambda _url: "PAGE")
    monkeypatch.setattr(client, "_fetch_item_from_page", lambda _page, _item_id: raw)

    rows = client.get_items([item_id], status_only=True)

    assert rows == [{"item_id": item_id, "status": "ok", "item": {
        "id": item_id, "url": f"https://www.mercari.com/us/item/{item_id}/",
        "status": status, "lastSoldAt": 1788676849,
    }}]
    assert raw == {"itemId": item_id, "status": status, "lastSoldAt": 1788676849}
    priced = client.get_items([item_id])
    assert priced[0]["status"] == "error"
    assert "no integer price" in priced[0]["error"]


@pytest.mark.parametrize("status", [None, "", "  ", False, 0])
def test_status_only_rejects_missing_or_invalid_status(monkeypatch, status):
    client = client_module.MercariClient.__new__(client_module.MercariClient)
    monkeypatch.setattr(client, "_app_shell", lambda _url: "PAGE")
    monkeypatch.setattr(client, "_fetch_item_from_page", lambda _page, _item_id: {
        "itemId": "m11111111111", "status": status,
    })
    rows = client.get_items(["m11111111111"], status_only=True)
    assert rows[0]["status"] == "error"
    assert rows[0]["error_kind"] == "unreadable"
    assert "no published status" in rows[0]["error"]
    assert "item" not in rows[0]


def test_get_many_status_only_option_reaches_real_client_and_emits_json(monkeypatch):
    client = client_module.MercariClient.__new__(client_module.MercariClient)
    client._browser = None
    monkeypatch.setattr(client, "_app_shell", lambda _url: "PAGE")
    monkeypatch.setattr(client, "_fetch_item_from_page", lambda _page, item_id: {
        "itemId": item_id, "status": "sold_out", "priceSummary": {"headline": None},
    })
    monkeypatch.setattr(main, "get_client", lambda: client)

    result = CliRunner().invoke(
        main.listings_app, ["get-many", "--status-only", "m11111111111"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)[0] == {
        "item_id": "m11111111111", "status": "ok", "item": {
            "id": "m11111111111", "url": "https://www.mercari.com/us/item/m11111111111/",
            "status": "sold_out",
        },
    }
    assert "Reading 1 Mercari item details." in result.stderr
