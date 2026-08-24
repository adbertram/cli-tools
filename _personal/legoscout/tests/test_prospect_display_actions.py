"""The Prospects view's Reject/Restore and ★ actions must persist.

Adam's clicks on the Prospects view go through two new routes,
POST /prospect_status and POST /prospect_favorite, backed by
prospects_db.update_prospect_status / prospects_db.set_favorite. These tests
close both halves: the access layer's favorite flag (insert default, flip,
error cases, the ALTER migration for databases written before the column),
and the HTTP surface itself -- including the gate contract that POST
/prospects.json STAYS a 404 even though prospect writes now exist.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from legoscout_cli.display import server as display_server
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.ledger import prospects as prospects_db


@pytest.fixture
def db_path(tmp_path):
    """An empty ledger at the current schema with one active prospect."""
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    prospect_id = prospects_db.insert_prospect(
        {
            "name": "Display Action Resale",
            "hypothesis_type": "kids_resale_stores",
            "citation_url": "https://example.invalid/display-action",
            "location": "Evansville, IN",
            "distance_miles": 5.0,
            "available_fulfillment": ["local_pickup"],
        },
        [{"person_name": "store", "email": "action@example.invalid"}],
        path=path,
    )
    return path, prospect_id


# --- access layer ------------------------------------------------------------


def test_insert_defaults_is_favorite_to_zero(db_path):
    path, prospect_id = db_path
    assert prospects_db.is_favorite(prospect_id, path=path) is False


def test_set_favorite_round_trips(db_path):
    path, prospect_id = db_path
    prospects_db.set_favorite(prospect_id, True, path=path)
    assert prospects_db.is_favorite(prospect_id, path=path) is True
    row = prospects_db.list_prospects(path=path)[0]
    assert row["is_favorite"] == 1
    prospects_db.set_favorite(prospect_id, False, path=path)
    assert prospects_db.is_favorite(prospect_id, path=path) is False
    assert prospects_db.list_prospects(path=path)[0]["is_favorite"] == 0


def test_set_favorite_rejects_missing_prospect(db_path):
    path, _ = db_path
    with pytest.raises(prospects_db.ProspectError, match="no prospect"):
        prospects_db.set_favorite(9999, True, path=path)


def test_set_favorite_rejects_non_bool(db_path):
    path, prospect_id = db_path
    # Deliberately wrong type -- the refusal IS the contract under test.
    with pytest.raises(prospects_db.ProspectError, match="must be a bool"):
        prospects_db.set_favorite(
            prospect_id, 1, path=path)  # pyright: ignore[reportArgumentType]


def test_legacy_database_gets_the_column_via_alter(tmp_path):
    """A database written before is_favorite existed must converge, not crash:
    the ALTER leaves existing rows NULL, and both the reader and the flag treat
    that as not-favorited until Adam stars the row."""
    path = str(tmp_path / "legacy.db")
    conn = ledger_db.init(path)
    # The OLD shape of the prospects table -- everything _SCHEMA had before
    # is_favorite was added.
    conn.executescript("""
        CREATE TABLE prospects (
            prospect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_normalized TEXT NOT NULL,
            hypothesis_type TEXT NOT NULL,
            citation_url TEXT NOT NULL,
            location TEXT NOT NULL,
            location_normalized TEXT NOT NULL,
            distance_miles,
            available_fulfillment TEXT,
            domain TEXT,
            event_date TEXT,
            status TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO prospects (name, name_normalized, hypothesis_type, "
        "citation_url, location, location_normalized, distance_miles, "
        "status, created_at, updated_at) VALUES "
        "('Legacy Co', 'legacy co', 'kids_resale_stores', "
        "'https://example.invalid/legacy', 'Evansville IN', 'evansville in', "
        "5.0, 'active', '2026-01-01', '2026-01-01')")
    conn.commit()
    conn.close()

    # Any access-layer entry point migrates on connect.
    assert prospects_db.is_favorite(1, path=path) is False
    prospects_db.set_favorite(1, True, path=path)
    assert prospects_db.is_favorite(1, path=path) is True
    check = sqlite3.connect(path)
    try:
        cols = [row[1] for row in check.execute("PRAGMA table_info(prospects)")]
    finally:
        check.close()
    assert "is_favorite" in cols


# --- HTTP surface -------------------------------------------------------------


class _Page:
    """A live display server bound to an ephemeral loopback port, pointed at
    one scratch ledger, with the origin/host guards filled the way main()
    fills them."""

    def __init__(self, db_path: str):
        self._origins = set(display_server.ALLOWED_ORIGINS)
        self._hosts = set(display_server.ALLOWED_HOSTS)
        self._db_override = display_server.DB_OVERRIDE
        self.host = "127.0.0.1"
        display_server.DB_OVERRIDE = db_path
        self.srv = display_server.QuietServer(
            (self.host, 0), display_server.Handler)
        self.port = self.srv.server_address[1]
        hostport = "%s:%d" % (self.host, self.port)
        display_server.ALLOWED_HOSTS.add(hostport)
        display_server.ALLOWED_ORIGINS.add("http://" + hostport)
        self.thread = threading.Thread(
            target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def post(self, route: str, payload: dict, *, origin: str | None = None):
        headers = {"Content-Type": "application/json"}
        base = "http://%s:%d" % (self.host, self.port)
        if origin is None:
            origin = base
        if origin != "suppress":
            headers["Origin"] = origin
        req = urllib.request.Request(
            base + route, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)
        display_server.ALLOWED_ORIGINS.clear()
        display_server.ALLOWED_ORIGINS |= self._origins
        display_server.ALLOWED_HOSTS.clear()
        display_server.ALLOWED_HOSTS |= self._hosts
        display_server.DB_OVERRIDE = self._db_override


@pytest.fixture
def page(db_path):
    path, _ = db_path
    p = _Page(path)
    yield p
    p.close()


def test_prospect_status_reject_then_restore(page, db_path):
    _, prospect_id = db_path
    status, body = page.post("/prospect_status",
                             {"prospect_id": prospect_id, "status": "rejected"})
    assert status == 200 and body["ok"] is True
    status, body = page.post("/prospect_status",
                             {"prospect_id": prospect_id, "status": "active"})
    assert status == 200 and body["ok"] is True


def test_prospect_status_refuses_dead_and_unknown(page, db_path):
    path, prospect_id = db_path
    status, body = page.post("/prospect_status",
                             {"prospect_id": prospect_id, "status": "dead"})
    assert status == 400 and "not allowed" in body["error"]
    status, body = page.post("/prospect_status",
                             {"prospect_id": 9999, "status": "rejected"})
    assert status == 400 and "not found" in body["error"]
    # And the stored status never moved.
    stored = prospects_db.get_prospect(prospect_id, path=path)
    assert stored is not None and stored["status"] == "active"


def test_prospect_favorite_flips_both_ways(page, db_path):
    path, prospect_id = db_path
    status, body = page.post("/prospect_favorite",
                             {"prospect_id": prospect_id, "is_favorite": True})
    assert status == 200 and body["ok"] is True
    assert prospects_db.is_favorite(prospect_id, path=path) is True
    status, _ = page.post("/prospect_favorite",
                          {"prospect_id": prospect_id, "is_favorite": False})
    assert status == 200
    assert prospects_db.is_favorite(prospect_id, path=path) is False


def test_prospect_favorite_validates_its_inputs(page, db_path):
    path, prospect_id = db_path
    status, body = page.post("/prospect_favorite",
                             {"prospect_id": prospect_id, "is_favorite": "yes"})
    assert status == 400 and "boolean" in body["error"]
    status, body = page.post("/prospect_favorite",
                             {"prospect_id": "seven", "is_favorite": True})
    assert status == 400 and "integer" in body["error"]
    assert prospects_db.is_favorite(prospect_id, path=path) is False


def test_post_prospects_json_is_still_a_404(page):
    """The read route has no POST twin: writes live on the two named routes."""
    status, _ = page.post("/prospects.json", {})
    assert status == 404


def test_prospect_writes_require_the_page_origin(page, db_path):
    _, prospect_id = db_path
    status, body = page.post(
        "/prospect_status", {"prospect_id": prospect_id, "status": "rejected"},
        origin="http://evil.example:99")
    assert status == 403 and "origin" in body["error"]
