"""The ledger's read and write APIs must mean what their names say.

Three defects, all hit on live runs, all closed here.

READ NAME. `db.load()` returned the whole ledger DOCUMENT. A caller wrote the
obvious `for deal in db.load(): deal.get(...)`, iterated a dict, got its KEY
STRINGS, and died on `AttributeError: 'str' object has no attribute 'get'`. The
document reader is now `load_document()` and the deal reader is `load_deals()`.
Neither takes a flag to behave as the other.

READ-ONLY. `db.query()` is documented as SELECT/WITH only and enforced that with
`sql.startswith(...)`. SQLite accepts `WITH x AS (SELECT 1) DELETE FROM deals`,
which passed the test and committed -- a live check took a copy of the ledger
from 2314 deals to 0 while `query()` returned `[]` and raised nothing. The guard
is now the engine (`mode=ro`), which no statement form can talk its way past.

CONCURRENT SAVE. `save()` deletes every deal and re-inserts the caller's list.
Two processes that each loaded, appended one deal, and saved both reported
success and the table kept only the second one's row. `save()` now carries a
revision from `load_document()` and RAISES on a stale write, and `upsert_deals()`
gives a run a way to store records without overwriting the whole file.
"""
from __future__ import annotations

import copy
import json
import multiprocessing
import sqlite3
import time

import pytest

from legoscout_cli.ledger import db as ledger_db


def _seed_deal(key):
    """The smallest record `deal_schema` accepts, keyed as caller asks."""
    return {
        "listing_key": key,
        "source": key.split("|")[0],
        "title": "LEGO bulk lot",
        "url": "https://example.invalid/%s" % key.split("|")[1],
        "current_price": 25.0,
        "price_basis": "current_price",
        "status": "active",
    }


def _invalid_deal():
    """A record `deal_schema` rejects: `price_basis` is a closed enum."""
    bad = _seed_deal("broken|9999")
    bad["price_basis"] = "not_a_real_basis"
    return bad


@pytest.fixture
def ledger(tmp_path):
    """An empty ledger at the current schema, seeded with two deals.

    `connect()` refuses to create the file on purpose, so this builds it the way
    the migration does, then seeds through the per-record path.
    """
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    ledger_db.upsert_deals(
        [_seed_deal("shopgoodwill|1001"), _seed_deal("ebay|2002")], path=path)
    return path


# --- the read API says which of the two shapes it returns -------------------

def test_load_deals_returns_records_a_caller_can_use(ledger):
    """The documented deal read must survive the obvious loop.

    This is the exact loop that raised AttributeError against the old `load()`.
    """
    deals = ledger_db.load_deals(path=ledger)

    assert isinstance(deals, list)
    assert len(deals) == 2
    for deal in deals:
        assert isinstance(deal, dict), (
            "load_deals() yielded %r; a caller writing `deal.get(...)` needs a "
            "mapping, not a key string" % type(deal).__name__)
        assert deal.get("listing_key")
        assert deal.get("nonexistent_field", "fallback") == "fallback"
    assert {d.get("listing_key") for d in deals} == {
        "shopgoodwill|1001", "ebay|2002"}


def test_load_document_returns_the_document_save_takes_back(ledger):
    doc = ledger_db.load_document(path=ledger)

    assert isinstance(doc, dict)
    assert isinstance(doc["deals"], list)
    assert all(isinstance(d, dict) for d in doc["deals"])
    # Iterating the document yields key strings. That is correct for a document
    # and is exactly why it must not be the function called `load`.
    assert all(isinstance(k, str) for k in doc)


def test_readonly_document_loader_never_opens_a_migration_connection(ledger, monkeypatch):
    """A display refresh cannot run schema migration work while it reads."""
    monkeypatch.setattr(
        ledger_db, "connect",
        lambda *args, **kwargs: pytest.fail("read-only loader opened connect()"),
    )

    doc = ledger_db.load_document_readonly(path=ledger)

    assert {deal["listing_key"] for deal in doc["deals"]} == {
        "shopgoodwill|1001", "ebay|2002"}


def test_the_misleading_name_is_gone(ledger):
    """`load` must not exist at all -- not as an alias, not behind a flag."""
    assert not hasattr(ledger_db, "load"), (
        "db.load still exists. One name, one meaning: the two reads are "
        "load_document() and load_deals().")


def test_the_two_reads_agree(ledger):
    assert ledger_db.load_deals(path=ledger) == ledger_db.load_document(
        path=ledger)["deals"]


# --- query() is read-only because the engine says so ------------------------

@pytest.mark.parametrize("sql", [
    "WITH x AS (SELECT 1) DELETE FROM deals",
    "WITH x AS (SELECT 1) UPDATE deals SET status = 'wiped'",
    "WITH x AS (SELECT 1) INSERT INTO deals (listing_key, _key_order) "
    "VALUES ('x|1', '[]')",
])
def test_cte_prefixed_writes_cannot_reach_the_ledger(ledger, sql):
    """Every CTE write form passes the string test. None may reach the file."""
    before = ledger_db.load_deals(path=ledger)

    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ledger_db.query(sql, path=ledger)

    assert ledger_db.load_deals(path=ledger) == before


def test_query_still_reads(ledger):
    rows = ledger_db.query(
        "SELECT listing_key FROM deals WHERE source = ?", ("ebay",), path=ledger)
    assert [r["listing_key"] for r in rows] == ["ebay|2002"]


def test_query_still_rejects_a_bare_write_early(ledger):
    with pytest.raises(ValueError, match="SELECT/WITH"):
        ledger_db.query("DELETE FROM deals", path=ledger)


# --- a stale whole-ledger save raises ---------------------------------------

def test_save_refuses_a_document_it_did_not_stamp(ledger):
    with pytest.raises(ledger_db.StaleWrite, match="_revision"):
        ledger_db.save({"deals": [_seed_deal("ebay|2002")]}, path=ledger)


def test_stale_save_raises_instead_of_deleting_the_other_writer(ledger):
    """The reproduced lost update, as a test.

    Both documents are loaded at the same revision. The first save wins; the
    second must RAISE rather than delete the row the first one added.
    """
    stale = ledger_db.load_document(path=ledger)
    fresh = ledger_db.load_document(path=ledger)

    fresh["deals"] = fresh["deals"] + [_seed_deal("hibid|3003")]
    ledger_db.save(fresh, path=ledger)

    stale["deals"] = stale["deals"] + [_seed_deal("craigslist|4004")]
    with pytest.raises(ledger_db.StaleWrite, match="revision"):
        ledger_db.save(stale, path=ledger)

    keys = {d["listing_key"] for d in ledger_db.load_deals(path=ledger)}
    assert "hibid|3003" in keys, "the winning writer's deal was lost"
    assert "craigslist|4004" not in keys


def test_a_fresh_save_still_works_and_moves_the_revision(ledger):
    doc = ledger_db.load_document(path=ledger)
    first = doc["_revision"]

    doc["deals"] = doc["deals"] + [_seed_deal("hibid|3003")]
    ledger_db.save(doc, path=ledger)

    after = ledger_db.load_document(path=ledger)
    assert after["_revision"] == first + 1
    assert len(after["deals"]) == 3
    # `_revision` is bookkeeping, not a ledger field, so it must not come back
    # as part of the stored document order.
    with sqlite3.connect(ledger) as conn:
        order = json.loads(conn.execute(
            "SELECT value FROM meta WHERE key = '_top_level_order'"
        ).fetchone()[0])
    assert "_revision" not in order


def test_a_failed_save_does_not_move_the_revision(ledger):
    """A rejected write must leave the ledger exactly as it was."""
    doc = ledger_db.load_document(path=ledger)
    before = doc["_revision"]
    doc["deals"] = doc["deals"] + [_invalid_deal()]

    with pytest.raises(Exception):
        ledger_db.save(doc, path=ledger)

    assert ledger_db.load_document(path=ledger)["_revision"] == before
    assert len(ledger_db.load_deals(path=ledger)) == 2


# --- the per-record path a run should use instead ---------------------------

def test_upsert_deals_touches_only_the_records_it_is_given(ledger):
    counts = ledger_db.upsert_deals([_seed_deal("hibid|3003")], path=ledger)
    assert counts == {"inserted": 1, "updated": 0}

    keys = {d["listing_key"] for d in ledger_db.load_deals(path=ledger)}
    assert keys == {"shopgoodwill|1001", "ebay|2002", "hibid|3003"}


def test_upsert_deals_updates_in_place(ledger):
    changed = _seed_deal("ebay|2002")
    changed["current_price"] = 99.0
    assert ledger_db.upsert_deals([changed], path=ledger) == {
        "inserted": 0, "updated": 1}

    rows = ledger_db.query(
        "SELECT current_price FROM deals WHERE listing_key = 'ebay|2002'",
        path=ledger)
    assert rows[0]["current_price"] == 99.0
    assert len(ledger_db.load_deals(path=ledger)) == 2


def test_upsert_deals_writes_nothing_when_any_record_is_invalid(ledger):
    with pytest.raises(Exception):
        ledger_db.upsert_deals(
            [_seed_deal("hibid|3003"), _invalid_deal()], path=ledger)

    keys = {d["listing_key"] for d in ledger_db.load_deals(path=ledger)}
    assert "hibid|3003" not in keys, "a rejected batch wrote part of itself"


def _upsert_worker(path, key, delay):
    time.sleep(delay)
    ledger_db.upsert_deals([_seed_deal(key)], path=path)


def test_concurrent_upserts_both_land(ledger):
    """The case that silently lost a write under save(), now safe.

    Two processes each add a distinct deal at the same time. Both must survive:
    an upsert never deletes a row it was not handed.
    """
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_upsert_worker, args=(ledger, key, delay))
             for key, delay in (("hibid|3003", 0.0), ("craigslist|4004", 0.2))]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)

    assert [p.exitcode for p in procs] == [0, 0]
    keys = {d["listing_key"] for d in ledger_db.load_deals(path=ledger)}
    assert {"hibid|3003", "craigslist|4004"} <= keys
