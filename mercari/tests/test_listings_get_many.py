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
        def get_items(self, item_ids):
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
