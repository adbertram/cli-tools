"""A display request reads source metadata once and refreshes it next request."""
import json
from unittest.mock import patch

import pytest

from legoscout_cli.display import rows
from legoscout_cli.ledger import db
from legoscout_cli.sources import registry


def _ledger(tmp_path, name, short):
    path = str(tmp_path / (name + ".db"))
    db.init(path).close()
    conn = registry._connect(path)
    with conn:
        conn.execute("INSERT INTO sources (namespace, payload) VALUES (?, ?)", (
            "ebay", json.dumps({"short": short, "display_name": "eBay",
                                "aliases": ["auction-market"],
                                "capability": {"can_offer": False}})))
    conn.close()
    db.upsert_deals([{
        "listing_key": "ebay|" + str(i), "source": "ebay", "title": "LEGO bulk lot",
        "url": "https://www.ebay.com/itm/" + str(i), "current_price": 25,
        "price_basis": "current_price", "status": "active",
        "listing_category": "bulk", "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
    } for i in range(3)], path=path)
    return path


def test_one_registry_read_per_request_preserves_rows_and_refreshes(tmp_path):
    path = _ledger(tmp_path, "first", "eBay")
    expected = [rows.js_numbers(rows.row(deal, set(), registry.Registry(path)))
                for deal in db.load_deals(path=path)]
    original = registry._read_table
    with patch.object(registry, "_read_table", wraps=original) as read:
        assert rows.build_rows(path=path) == expected
        assert read.call_count == 1
    conn = registry._connect(path)
    with conn:
        payload = json.loads(conn.execute("SELECT payload FROM sources").fetchone()[0])
        payload["short"] = "Updated eBay"
        conn.execute("UPDATE sources SET payload = ?", (json.dumps(payload),))
    conn.close()
    assert {row["source"] for row in rows.build_rows(path=path)} == {"Updated eBay"}


def test_snapshot_respects_alternate_database(tmp_path):
    first = _ledger(tmp_path, "first", "First")
    second = _ledger(tmp_path, "second", "Second")
    assert {row["source"] for row in rows.build_rows(path=first)} == {"First"}
    assert {row["source"] for row in rows.build_rows(path=second)} == {"Second"}


def test_snapshot_preserves_alias_and_unknown_source_contract(tmp_path):
    path = _ledger(tmp_path, "first", "eBay")
    snapshot = registry.Registry(path).snapshot()
    assert snapshot.entry("auction-market|123") == snapshot.entry("ebay")
    with pytest.raises(registry.UnknownEntry):
        snapshot.entry("not-registered|123")
    db.upsert_deals([{
        "listing_key": "not-registered|123", "source": "not-registered",
        "title": "LEGO bulk lot", "url": "https://example.invalid/123",
        "current_price": 25, "price_basis": "current_price", "status": "active",
    }], path=path)
    rendered = rows.build_rows(path=path)
    assert len(rendered) == 4
    assert "UnknownEntry" in rendered[-1]["rowError"]
    assert all("rowError" not in row for row in rendered[:3])
