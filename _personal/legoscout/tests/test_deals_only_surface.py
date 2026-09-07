"""Retired prospect actions disappear without erasing historical ledger data."""
import json
import threading
import urllib.error
import urllib.request

import pytest
from typer.testing import CliRunner

from legoscout_cli.display import server
from legoscout_cli.ledger import db
from legoscout_cli.main import app


@pytest.fixture
def ledger(tmp_path):
    path = str(tmp_path / "deals.db")
    conn = db.init(path)
    # Historical tables are independent data; current code must leave them intact.
    with conn:
        for table in ("prospects", "contacts", "outreach", "prospect_runs"):
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, evidence TEXT)")
            conn.execute(f"INSERT INTO {table} VALUES (42, 'historical evidence')")
    conn.close()
    db.upsert_deals([{
        "listing_key": "ebay|123", "source": "ebay", "title": "LEGO bulk lot",
        "url": "https://www.ebay.com/itm/123", "current_price": 25,
        "price_basis": "current_price", "status": "active", "prospect_id": 42,
    }], path=path)
    return path


def test_deal_writes_preserve_legacy_associations_and_tables(ledger):
    document = db.load_document(path=ledger)
    assert document["deals"][0]["prospect_id"] == 42
    document["deals"][0]["status"] = "rejected"
    db.save(document, path=ledger)
    assert db.load_deals(path=ledger)[0]["prospect_id"] == 42
    for table in ("prospects", "contacts", "outreach", "prospect_runs"):
        assert db.query(f"SELECT * FROM {table}", path=ledger) == [
            {"id": 42, "evidence": "historical evidence"}]


def test_prospects_command_is_removed():
    result = CliRunner().invoke(app, ["prospects", "--help"])
    assert result.exit_code == 2
    assert "No such command" in result.output


@pytest.mark.parametrize("method,route", [
    ("GET", "/prospects.json"), ("POST", "/prospects.json"),
    ("POST", "/prospect_status"), ("POST", "/prospect_favorite"),
])
def test_retired_routes_return_404(method, route, ledger, monkeypatch):
    monkeypatch.setattr(server, "DB_OVERRIDE", ledger)
    with server.QuietServer(("127.0.0.1", 0), server.Handler) as httpd:
        host = "127.0.0.1:%d" % httpd.server_address[1]
        monkeypatch.setattr(server, "ALLOWED_HOSTS", {host})
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                "http://" + host + route,
                data=b'{}' if method == "POST" else None, method=method,
                headers={"Content-Type": "application/json"})
            with pytest.raises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)
            assert raised.value.code == 404
            assert json.loads(raised.value.read()) == {"error": "not found"}
        finally:
            httpd.shutdown()
            thread.join(timeout=5)


def test_deals_page_has_no_prospect_view():
    assert "prospect" not in server.PAGE.lower()
    assert 'fetch("/rows.json' in server.PAGE
