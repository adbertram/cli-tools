"""BuyService resolve/fetch tests with mocked HTTP."""

import json
from pathlib import Path

from bricklink_cli.buy.service import BuyService
from bricklink_cli.buy.store import BuyStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeClient:
    def __init__(self):
        self.search_calls = 0
        self.catalog_calls = 0

    def search_product(self, *, query, item_type, page=1, rpp=25):
        self.search_calls += 1
        return json.loads((FIXTURES / "D1-searchproduct.body").read_text())

    def catalogifs(self, *, item_id, page=1, rpp=500, color_id=None, condition=None):
        self.catalog_calls += 1
        return json.loads((FIXTURES / "B1-catalogifs.json").read_text())


def test_resolve_and_fetch_lots(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")
    store = BuyStore(tmp_path / "buy.sqlite3")
    store.upsert_items(
        [{"item_type": "MINIFIG", "item_no": "sw0936", "name": "x", "category_id": 65}]
    )
    client = FakeClient()
    service = BuyService(store=store, client=client)

    id_item = service.resolve_id_item("MINIFIG", "sw0936")
    assert id_item == 166767
    assert client.search_calls == 1

    # SQLite id_map hit — no extra HTTP
    assert service.resolve_id_item("MINIFIG", "sw0936") == 166767
    assert client.search_calls == 1

    result = service.fetch_lots("MINIFIG", "sw0936")
    assert result["count"] > 0
    assert result["id_item"] == 166767
    assert client.catalog_calls >= 1

    listed = service.list_lots(item_type="MINIFIG", item_no="sw0936", max_price=100)
    assert len(listed) > 0
