"""`mark_unavailable()` / `mark_blocked()` share one internal writer,
`_write_pipeline_status()`, and both stay single-row primitives for an
ad-hoc confirmation -- never a per-row loop inside a bulk sweep."""
from __future__ import annotations

import pytest

from legoscout_cli.ledger import db as ledger_db


def _seed_deal(key, **overrides):
    deal = {
        "listing_key": key,
        "source": key.split("|")[0],
        "title": "LEGO bulk lot",
        "url": "https://example.invalid/%s" % key.split("|")[1],
        "current_price": 25.0,
        "price_basis": "current_price",
        "status": "active",
    }
    deal.update(overrides)
    return deal


@pytest.fixture
def ledger(tmp_path):
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    ledger_db.upsert_deals([_seed_deal("proxibid|1")], path=path)
    return path


def test_mark_blocked_sets_status_and_evidence_note(ledger):
    ok = ledger_db.mark_blocked(
        "proxibid|1", "Imperva Error 15 - access denied", "2026-08-08T12:00:00+00:00", path=ledger)

    assert ok is True
    deal = ledger_db.get_deal("proxibid|1", path=ledger)
    assert deal["status"] == "blocked"
    assert deal["last_status"] == "blocked"
    assert deal["last_seen_at"] == "2026-08-08T12:00:00+00:00"
    assert "Imperva Error 15" in deal["notes"]
    assert "blocked" in deal["notes"]


def test_mark_blocked_returns_false_for_a_missing_listing(ledger):
    assert ledger_db.mark_blocked("proxibid|999", "x", "2026-08-08T12:00:00+00:00", path=ledger) is False


def test_mark_unavailable_unchanged_signature_and_behavior(ledger):
    ok = ledger_db.mark_unavailable("proxibid|1", "confirmed gone", "2026-08-08T12:00:00+00:00", path=ledger)

    assert ok is True
    deal = ledger_db.get_deal("proxibid|1", path=ledger)
    assert deal["status"] == "unavailable"
    assert deal["last_status"] == "unavailable"
    assert "confirmed gone" in deal["notes"]


def test_mark_unavailable_and_mark_blocked_write_through_upsert_not_save(ledger, monkeypatch):
    monkeypatch.setattr(ledger_db, "save", lambda *a, **k: pytest.fail("save() must never be called"))
    assert ledger_db.mark_unavailable("proxibid|1", "x", "2026-08-08T12:00:00+00:00", path=ledger)


def test_blocked_and_unavailable_stay_outside_settable_status():
    assert "blocked" not in ledger_db.SETTABLE_STATUS
    assert "unavailable" not in ledger_db.SETTABLE_STATUS


def test_update_status_refuses_blocked_and_unavailable_and_names_both_writers(ledger):
    with pytest.raises(ledger_db.UnknownStatus, match="mark_unavailable"):
        ledger_db.update_status("proxibid|1", "unavailable", "2026-08-08T12:00:00+00:00", path=ledger)
    with pytest.raises(ledger_db.UnknownStatus, match="mark_blocked"):
        ledger_db.update_status("proxibid|1", "blocked", "2026-08-08T12:00:00+00:00", path=ledger)


def test_shared_writer_produces_the_same_mutation_shape_for_both_statuses(ledger):
    ledger_db.upsert_deals([_seed_deal("proxibid|2")], path=ledger)

    ledger_db._write_pipeline_status("proxibid|1", "unavailable", "ev1", "2026-08-08T12:00:00+00:00", path=ledger)
    ledger_db._write_pipeline_status("proxibid|2", "blocked", "ev2", "2026-08-08T12:00:00+00:00", path=ledger)

    unavailable = ledger_db.get_deal("proxibid|1", path=ledger)
    blocked = ledger_db.get_deal("proxibid|2", path=ledger)
    for deal, status in ((unavailable, "unavailable"), (blocked, "blocked")):
        assert deal["status"] == status
        assert deal["last_status"] == status
        assert deal["last_seen_at"] == "2026-08-08T12:00:00+00:00"
        assert "Marked %s" % status in deal["notes"]
