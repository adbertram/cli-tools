"""Tests for the Source-CLI Sort Standard on `products list`.

The America's Thrift Supply storefront's Shopify JSON endpoints ignore the
`?sort_by=` parameter (verified live), so `--sort`/`--desc` sort the returned
result set client-side on the normalized fields. These tests cover:
  - `_resolve_sort` validation (default newest, case-insensitive, fail-fast)
  - `_sort_products` ordering for newest/price and their `--desc` reversals
  - the `products list` command surface: unknown --sort exits non-zero, and
    newest/price ordering flows through to JSON output.
"""

import json

import pytest
import typer
from typer.testing import CliRunner

from americasthriftsupply_cli import main


runner = CliRunner()


# Scrambled input order on purpose; each field yields a distinct ordering.
SAMPLE_ROWS = [
    {"id": 2, "handle": "b", "title": "Mid", "created_at": "2026-02-01T00:00:00", "price_usd": 20.0},
    {"id": 1, "handle": "a", "title": "Newest", "created_at": "2026-03-01T00:00:00", "price_usd": 50.0},
    {"id": 3, "handle": "c", "title": "Oldest", "created_at": "2026-01-01T00:00:00", "price_usd": 5.0},
    {"id": 4, "handle": "d", "title": "NoPrice", "created_at": "2026-02-15T00:00:00", "price_usd": None},
]


class _FakeClient:
    """Stand-in for the storefront client so command tests never hit the network."""

    def list_products(self, limit: int = 100, collection=None, page_delay: float = 0.0):
        return [dict(row) for row in SAMPLE_ROWS][:limit]


# --- _resolve_sort (validation / fail-fast) -----------------------------------


def test_resolve_sort_default_is_newest():
    assert main._resolve_sort("newest") == "newest"


def test_resolve_sort_accepts_price():
    assert main._resolve_sort("price") == "price"


def test_resolve_sort_is_case_insensitive():
    assert main._resolve_sort("NEWEST") == "newest"
    assert main._resolve_sort("Price") == "price"


def test_resolve_sort_rejects_unknown_field():
    """Unknown --sort fails fast with valid values listed and no fallback."""
    with pytest.raises(typer.BadParameter) as exc:
        main._resolve_sort("bogus")
    message = str(exc.value)
    assert "bogus" in message
    assert "newest" in message
    assert "price" in message


# --- _sort_products (ordering) ------------------------------------------------


def test_sort_products_newest_natural_is_newest_first():
    ordered = main._sort_products(SAMPLE_ROWS, "newest", desc=False)
    assert [row["id"] for row in ordered] == [1, 4, 2, 3]


def test_sort_products_newest_desc_is_oldest_first():
    ordered = main._sort_products(SAMPLE_ROWS, "newest", desc=True)
    assert [row["id"] for row in ordered] == [3, 2, 4, 1]


def test_sort_products_price_natural_is_low_to_high_unpriced_last():
    ordered = main._sort_products(SAMPLE_ROWS, "price", desc=False)
    assert [row["id"] for row in ordered] == [3, 2, 1, 4]


def test_sort_products_price_desc_is_high_to_low_unpriced_last():
    ordered = main._sort_products(SAMPLE_ROWS, "price", desc=True)
    assert [row["id"] for row in ordered] == [1, 2, 3, 4]


# --- products list command surface --------------------------------------------


def test_products_list_unknown_sort_exits_nonzero(monkeypatch):
    """`products list --sort bogus` exits non-zero (no network call needed)."""
    monkeypatch.setattr(main, "get_client", lambda: _FakeClient())
    result = runner.invoke(main.products_app, ["list", "--sort", "bogus"])
    assert result.exit_code != 0


def test_products_list_default_sort_is_newest_first(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: _FakeClient())
    result = runner.invoke(main.products_app, ["list"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [row["id"] for row in rows] == [1, 4, 2, 3]


def test_products_list_price_sort_orders_low_to_high(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: _FakeClient())
    result = runner.invoke(main.products_app, ["list", "--sort", "price"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [row["id"] for row in rows] == [3, 2, 1, 4]


def test_products_list_price_desc_orders_high_to_low(monkeypatch):
    monkeypatch.setattr(main, "get_client", lambda: _FakeClient())
    result = runner.invoke(main.products_app, ["list", "--sort", "price", "--desc"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [row["id"] for row in rows] == [1, 2, 3, 4]
