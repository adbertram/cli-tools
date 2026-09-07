"""Availability checks cannot erase a user decision or a concurrent observation."""
import sqlite3
from datetime import datetime, timezone

import pytest

from legoscout_cli.deploy import availability as remote_availability, config
from legoscout_cli.invalidate import checks, sweep
from legoscout_cli.ledger import availability, db
from test_expired_listing_sweep import _seed_deal


@pytest.fixture
def ledger(tmp_path):
    path = str(tmp_path / "ledger.db")
    db.init(path).close()
    db.upsert_deals([_seed_deal("ebay|1"), _seed_deal("ebay|2")], path=path)
    return path


def _change(key):
    return {
        "listing_key": key, "status": "unavailable", "last_status": "unavailable",
        "last_seen_at": "2026-09-07T12:00:00Z", "notes": "Stale notes",
        "_sweep_fields": availability.STATUS_FIELDS,
        "_sweep_basis": availability.evidence_basis(_seed_deal(key)),
        "_sweep_note": "[Auction ended: verified evidence]",
    }


def test_apply_preserves_rejection_price_and_new_notes(ledger):
    stale = db.load_document(path=ledger)
    changed = [_change("ebay|1"), _change("ebay|2")]
    db.update_status("ebay|1", "rejected", "2026-09-07T11:00:00Z", path=ledger)
    fresh = db.get_deal("ebay|2", path=ledger)
    fresh.update(current_price=99.0, notes="New note from concurrent observation")
    db.upsert_deals([fresh], path=ledger)
    applied, skipped = availability.apply(changed, path=ledger)
    assert [row["listing_key"] for row in applied] == ["ebay|2"]
    assert [row["listing_key"] for row in skipped] == ["ebay|1"]
    assert db.get_deal("ebay|1", path=ledger)["status"] == "rejected"
    current = db.get_deal("ebay|2", path=ledger)
    assert current["current_price"] == 99.0
    assert current["notes"] == "New note from concurrent observation [Auction ended: verified evidence]"
    with pytest.raises(db.StaleWrite):
        db.save(stale, path=ledger)


def test_availability_holds_writer_lock_during_validation(ledger, monkeypatch):
    validate = db._validate_deals
    attempted = []

    def competing_writer(rows):
        other = db.connect(ledger)
        try:
            other.execute("PRAGMA busy_timeout=0")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
            attempted.append(True)
        finally:
            other.close()
        validate(rows)

    monkeypatch.setattr(db, "_validate_deals", competing_writer)
    availability.apply([_change("ebay|1")], path=ledger)
    assert attempted == [True]
    db.update_status("ebay|1", "rejected", "2026-09-07T12:01:00Z", path=ledger)
    assert db.get_deal("ebay|1", path=ledger)["status"] == "rejected"


def test_bad_sibling_rolls_back_entire_availability_write(ledger):
    before = db.load_document(path=ledger)
    bad = _change("ebay|2")
    bad["_sweep_note"] = ""
    with pytest.raises(ValueError, match="evidence"):
        availability.apply([_change("ebay|1"), bad], path=ledger)
    assert db.load_document(path=ledger) == before


def test_no_applied_availability_does_not_advance_revision(ledger):
    db.update_status("ebay|1", "rejected", "2026-09-07T12:01:00Z", path=ledger)
    before = db.load_document(path=ledger)
    applied, skipped = availability.apply([_change("ebay|1")], path=ledger)
    assert not applied and len(skipped) == 1
    assert db.load_document(path=ledger) == before


def test_server_expiration_targets_authoritative_database(monkeypatch):
    calls = []
    monkeypatch.setattr(remote_availability.ssh, "run_remote", lambda argv: calls.append(argv) or '{"applied": []}')
    assert remote_availability.expire() == {"applied": []}
    assert calls == [[
        "env", "LEGOSCOUT_DB_PATH=" + config.REMOTE_SHARED_DB,
        config.REMOTE_TOOL_PYTHON, "-m", "legoscout_cli.deploy.availability", "--apply",
    ]]


@pytest.mark.parametrize("field,value", [
    ("url", "https://example.invalid/relisted"),
    ("direct_url", "https://example.invalid/relisted-direct"),
    ("auction_end_date", "2026-10-01T12:00:00Z"),
    ("last_seen_at", "2026-09-07T12:01:00Z"),
])
@pytest.mark.parametrize("result_status", ["gone", "available", "blocked"])
def test_stale_availability_evidence_cannot_update_changed_listing(ledger, field, value, result_status):
    checked = db.get_deal("ebay|1", path=ledger)
    report = {key: [] for key in (
        "confirmed_unavailable", "confirmed_still_active", "blocked", "check_failed",
    )}
    changed = []
    sweep._record_live_result(checked, checks.CheckResult(result_status, "Checked original listing"),
                              "2026-09-07T12:00:00Z", report, changed)
    fresh = db.get_deal("ebay|1", path=ledger)
    fresh[field] = value
    db.upsert_deals([fresh], path=ledger)
    before = db.load_document(path=ledger)
    applied, skipped = availability.apply(changed, path=ledger)
    assert applied == []
    assert skipped[0]["listing_key"] == "ebay|1"
    assert "evidence" in skipped[0]["why"]
    assert db.load_document(path=ledger) == before


def test_expired_auction_evidence_cannot_close_extended_auction(ledger, monkeypatch):
    checked = db.get_deal("ebay|1", path=ledger)
    checked["auction_end_date"] = "2026-09-01T12:00:00Z"
    db.upsert_deals([checked], path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals", lambda: [dict(checked)])
    report, changed = sweep.sweep(datetime(2026, 9, 7, tzinfo=timezone.utc))
    assert len(report["confirmed_unavailable"]) == 1
    fresh = db.get_deal("ebay|1", path=ledger)
    fresh["auction_end_date"] = "2026-10-01T12:00:00Z"
    db.upsert_deals([fresh], path=ledger)
    before = db.load_document(path=ledger)
    applied, skipped = availability.apply(changed, path=ledger)
    assert applied == [] and len(skipped) == 1
    assert db.load_document(path=ledger) == before
