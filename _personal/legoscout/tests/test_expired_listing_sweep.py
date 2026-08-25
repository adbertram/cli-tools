"""`invalidate/sweep.py` must resolve every active row itself, every run --
never park one in a human hand-off bucket.

Adam's two rules, each covered here:
  1. A real, already-past auction_end_date needs no live check.
  2. A row with no usable date can only be resolved by a live check, subject
     to a 12-hour freshness cooldown.

Only `status == "active"` rows are touched at all -- everything else (Adam's
own decisions, or an already-terminal state) is left exactly as it was.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import signal
import subprocess
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

from legoscout_cli.invalidate import checks, sweep
from legoscout_cli.ledger import db as ledger_db

_real_load_deals = ledger_db.load_deals
_real_upsert_deals = ledger_db.upsert_deals

NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def _sleeping_dispatch(_deal):
    time.sleep(60)
    return checks.CheckResult("available", "unreachable")


def _timed_dispatch(deal):
    started = time.monotonic()
    time.sleep(0.2)
    return checks.CheckResult(
        "available",
        json.dumps({"started": started, "ended": time.monotonic()}),
    )


def _source_wall_dispatch(deal):
    if deal["listing_key"] == "mercari|first":
        return checks.CheckResult(
            "blocked", "confirmed Cloudflare challenge", stop_source=True)
    return checks.CheckResult("available", "still active")


def _batch_dispatch(deals):
    return {
        deal["listing_key"]: checks.CheckResult(
            "available", "batch_size=%d" % len(deals))
        for deal in deals
    }


def _batch_source_wall_dispatch(deals):
    return {
        deals[0]["listing_key"]: checks.CheckResult(
            "blocked", "verified human challenge", stop_source=True)
    }


def _spawn_descendant_and_sleep(deal):
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    with open(deal["pid_path"], "w", encoding="utf-8") as handle:
        handle.write("%d %d\n" % (os.getpid(), child.pid))
    child.wait()
    return checks.CheckResult("available", "unreachable")


def _run_batch_until_sigterm(pid_path):
    sweep._bounded_dispatch_batch(
        [_seed_deal("mercari|signal", pid_path=pid_path)],
        listing_timeout_seconds=60.0,
        total_deadline=time.monotonic() + 60.0,
        max_workers=1,
        dispatch_fn=_spawn_descendant_and_sleep,
    )


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _corrupt_auction_end_date(ledger_path, listing_key, bad_value):
    """Write a value `deal_schema`'s pattern would refuse, below the
    validation layer -- simulating a legacy row written before the schema's
    `auction_end_date` pattern was tightened (the 39-row 2026-08-06 case this
    sweep's `Unreadable` bucket exists for). `upsert_deals()` itself refuses
    this value outright, so a normal seed cannot produce this fixture.
    """
    with sqlite3.connect(ledger_path) as conn:
        conn.execute("UPDATE deals SET auction_end_date = ? WHERE listing_key = ?",
                     (bad_value, listing_key))


def _seed_deal(key, **overrides):
    """The smallest record `deal_schema` accepts, keyed as caller asks."""
    deal = {
        "listing_key": key,
        "source": key.split("|")[0],
        "title": "LEGO bulk lot",
        "url": "https://example.invalid/%s" % key.split("|")[1],
        "current_price": 25.0,
        "price_basis": "current_price",
        "status": "active",
        "auction_end_date": "not-an-auction",
    }
    deal.update(overrides)
    return deal


@pytest.fixture
def ledger(tmp_path):
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    return path


# --- parse_past compares real instants, not calendar dates ------------------
#
# Live on 2026-08-09, the date-only comparison this replaced (`dt.date() <
# now.date()`) marked 8 ShopGoodwill and 7 Shop The Salvation Army rows
# `unavailable` -- every one of them still open with real bid time left --
# because a same-day close time with no UTC offset read as "past" the moment
# the sweep's UTC clock crossed midnight, discarding the time-of-day the
# value actually carried.

def test_naive_same_day_time_is_not_yet_past_across_a_utc_midnight_rollover():
    """The exact failure mode: ShopGoodwill stores '19:18:00' with no offset.
    Checked at 00:12 UTC the next day, the OLD comparison said "past" because
    the calendar date had rolled over; the real Pacific-time deadline (~7
    hours later in UTC) had not arrived."""
    now = datetime(2026, 8, 9, 0, 12, 50, tzinfo=timezone.utc)
    assert sweep.parse_past("2026-08-08T19:18:00", now) is False


def test_naive_time_well_over_12h_old_is_past():
    now = datetime(2026, 8, 9, 0, 12, 50, tzinfo=timezone.utc)
    assert sweep.parse_past("2026-08-06T17:00:00", now) is True


def test_explicit_offset_is_compared_as_the_exact_instant():
    now = datetime(2026, 8, 9, 0, 12, 50, tzinfo=timezone.utc)
    # 2026-08-08T10:00:00-07:00 == 2026-08-08T17:00:00 UTC -- already past.
    assert sweep.parse_past("2026-08-08T10:00:00-07:00", now) is True
    # 2026-08-09T20:21:00-05:00 == 2026-08-10T01:21:00 UTC -- still future.
    assert sweep.parse_past("2026-08-09T20:21:00-05:00", now) is False


def test_bare_date_with_no_time_needs_a_full_day_plus_margin():
    now = datetime(2026, 8, 9, 0, 0, 0, tzinfo=timezone.utc)
    assert sweep.parse_past("2026-08-08", now) is False  # today -- not yet
    assert sweep.parse_past("2026-08-01", now) is True  # long past


# --- rule 1: a real past date needs no live check ---------------------------

def test_past_real_date_confirms_without_a_live_check(ledger, monkeypatch):
    def _fail_if_called(deal):
        pytest.fail("checks.dispatch() was called for a row a date already resolved")

    monkeypatch.setattr(checks, "dispatch", _fail_if_called)
    ledger_db.upsert_deals(
        [_seed_deal("ebay|1001", auction_end_date="2026-08-01T00:00:00+00:00")],
        path=ledger)
    monkeypatch.setattr(ledger_db, "DB_PATH", ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert [e["listing_key"] for e in report["confirmed_unavailable"]] == ["ebay|1001"]
    assert "2026-08-01" in report["confirmed_unavailable"][0]["evidence"]
    assert [d["listing_key"] for d in changed] == ["ebay|1001"]
    assert changed[0]["status"] == "unavailable"


def test_future_real_date_is_left_alone(ledger, monkeypatch):
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: pytest.fail("dispatch called for a future date"))
    ledger_db.upsert_deals(
        [_seed_deal("ebay|2002", auction_end_date="2026-12-01T00:00:00+00:00")],
        path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert all(e["listing_key"] != "ebay|2002"
               for entries in report.values() for e in entries)
    assert changed == []


# --- rule 3: only active rows are touched ------------------------------------

@pytest.mark.parametrize("status", ["rejected", "inquired", "bid_placed", "purchased",
                                    "unavailable", "blocked"])
def test_non_active_rows_are_never_reevaluated(ledger, monkeypatch, status):
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: pytest.fail("dispatch called for a non-active row"))
    ledger_db.upsert_deals(
        [_seed_deal("ebay|3003", status=status,
                    auction_end_date="2026-08-01T00:00:00+00:00")],
        path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert all(e["listing_key"] != "ebay|3003"
               for entries in report.values() for e in entries)
    assert changed == []


# --- rule 2: no usable date -> live check, via the dispatch table -----------

@pytest.mark.parametrize("result_status,bucket,new_status", [
    ("gone", "confirmed_unavailable", "unavailable"),
    ("available", "confirmed_still_active", "active"),
    ("blocked", "blocked", "blocked"),
])
def test_no_date_dispatches_a_live_check(ledger, monkeypatch, result_status, bucket, new_status):
    monkeypatch.setattr(
        checks, "dispatch",
        lambda deal: checks.CheckResult(result_status, "fixture evidence for %s" % deal["listing_key"]))
    ledger_db.upsert_deals(
        [_seed_deal("mercari|4004", auction_end_date="not-an-auction")], path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert [e["listing_key"] for e in report[bucket]] == ["mercari|4004"]
    assert [d["listing_key"] for d in changed] == ["mercari|4004"]
    assert changed[0]["status"] == new_status
    assert changed[0]["last_seen_at"] == NOW.isoformat()


def test_no_date_check_failed_is_retried_next_run_with_no_write(ledger, monkeypatch):
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: checks.CheckResult("error", "network hiccup"))
    ledger_db.upsert_deals(
        [_seed_deal("stockx|5005", auction_end_date="not-an-auction")], path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert [e["listing_key"] for e in report["check_failed"]] == ["stockx|5005"]
    assert changed == []  # never written -- retried on its own next run


# --- freshness cooldown -------------------------------------------------------

def test_row_checked_recently_is_skipped_entirely(ledger, monkeypatch):
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: pytest.fail("dispatch called on a row in cooldown"))
    recent = (NOW - timedelta(hours=1)).isoformat()
    ledger_db.upsert_deals(
        [_seed_deal("poshmark|6006", auction_end_date="not-an-auction", last_seen_at=recent)],
        path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert all(e["listing_key"] != "poshmark|6006"
               for entries in report.values() for e in entries)
    assert changed == []


def test_row_checked_over_12h_ago_is_rechecked(ledger, monkeypatch):
    calls = []
    monkeypatch.setattr(
        checks, "dispatch",
        lambda deal: (calls.append(deal["listing_key"]),
                      checks.CheckResult("available", "still there"))[1])
    stale = (NOW - timedelta(hours=13)).isoformat()
    ledger_db.upsert_deals(
        [_seed_deal("poshmark|7007", auction_end_date="not-an-auction", last_seen_at=stale)],
        path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert calls == ["poshmark|7007"]
    assert [e["listing_key"] for e in report["confirmed_still_active"]] == ["poshmark|7007"]


# --- hard wall-clock bounds and progress ------------------------------------

def test_bounded_dispatch_stops_a_stalled_check_process():
    before = {process.pid for process in multiprocessing.active_children()}
    started = time.monotonic()

    result = sweep._bounded_dispatch(
        _seed_deal("mercari|stalled"), 0.05, _sleeping_dispatch)

    assert result.status == "error"
    assert "exceeded 0.1-second limit" in result.detail
    assert time.monotonic() - started < 1.0
    after = {process.pid for process in multiprocessing.active_children()}
    assert after == before


def test_bounded_batch_runs_profiles_concurrently_but_serializes_shared_profiles(
    ledger, monkeypatch,
):
    playwright_key = sweep._serialization_key(_seed_deal("poshmark|profile"))
    assert sweep._serialization_key(_seed_deal("auctionninja|profile")) == playwright_key
    assert sweep._serialization_key(_seed_deal("craigslist|generic")) == playwright_key
    assert sweep._serialization_key(_seed_deal("depop|profile")) != playwright_key
    assert sweep._serialization_key(_seed_deal("mercari|profile")) != playwright_key
    ledger_db.upsert_deals([
        _seed_deal("mercari|first"),
        _seed_deal("mercari|second"),
        _seed_deal("depop|first"),
        _seed_deal("poshmark|first"),
        _seed_deal("craigslist|second"),
    ], path=ledger)
    monkeypatch.setattr(
        sweep.ledger_db, "load_deals", lambda path=None: _real_load_deals(path=ledger))

    started = time.monotonic()
    report, _ = sweep.sweep(
        NOW,
        sweep_timeout_seconds=2.0,
        listing_timeout_seconds=1.0,
        max_workers=4,
        dispatch_fn=_timed_dispatch,
    )
    elapsed = time.monotonic() - started

    timing = {
        row["listing_key"]: json.loads(row["evidence"])
        for row in report["confirmed_still_active"]
    }
    assert timing["mercari|second"]["started"] >= timing["mercari|first"]["ended"]
    assert timing["craigslist|second"]["started"] >= timing["poshmark|first"]["ended"]
    assert timing["depop|first"]["started"] < timing["mercari|first"]["ended"]
    # Concurrent floor is ~0.4s (the longest two-check serialization chain);
    # fully serial would be >=1.0s (5 x 0.2). The bound must discriminate
    # those two while tolerating fork/scheduler jitter -- 0.7 was flaky by
    # ~10ms whenever process spawn landed slowly (observed 2026-08-22).
    assert elapsed < 0.9


def test_source_wall_skips_pending_source_rows_without_marking_them_blocked(
    ledger, monkeypatch,
):
    ledger_db.upsert_deals([
        _seed_deal("mercari|first"),
        _seed_deal("mercari|second"),
        _seed_deal("ebay|other"),
    ], path=ledger)
    monkeypatch.setattr(
        sweep.ledger_db, "load_deals", lambda path=None: _real_load_deals(path=ledger))
    events = []

    report, changed = sweep.sweep(
        NOW,
        sweep_timeout_seconds=2.0,
        listing_timeout_seconds=1.0,
        max_workers=2,
        dispatch_fn=_source_wall_dispatch,
        progress=lambda event, fields: events.append((event, fields)),
    )

    assert [row["listing_key"] for row in report["blocked"]] == ["mercari|first"]
    assert [row["listing_key"] for row in report["check_failed"]] == ["mercari|second"]
    assert "unchecked after source wall" in report["check_failed"][0]["evidence"]
    assert [row["listing_key"] for row in report["confirmed_still_active"]] == ["ebay|other"]
    assert {row["listing_key"] for row in changed} == {"mercari|first", "ebay|other"}
    started = [fields["listing_key"] for event, fields in events if event == "check_start"]
    assert "mercari|second" not in started
    source_events = [fields for event, fields in events if event == "source_blocked"]
    assert source_events == [{
        "source": "mercari",
        "blocker_listing_key": "mercari|first",
        "unchecked_count": 1,
        "detail": "confirmed Cloudflare challenge",
    }]


def test_bounded_batch_groups_mercari_rows_under_one_worker():
    deals = [_seed_deal("mercari|%02d" % index) for index in range(25)]

    results = sweep._bounded_dispatch_batch(
        deals,
        listing_timeout_seconds=1.0,
        total_deadline=time.monotonic() + 2.0,
        max_workers=2,
        dispatch_fn=_source_wall_dispatch,
        batch_dispatch_fn=_batch_dispatch,
    )

    assert [results[deal["listing_key"]].detail for deal in deals[:20]] \
        == ["batch_size=20"] * 20
    assert [results[deal["listing_key"]].detail for deal in deals[20:]] \
        == ["batch_size=5"] * 5


def test_source_wall_inside_batch_skips_batch_and_pending_source_rows():
    deals = [_seed_deal("mercari|%02d" % index) for index in range(25)]
    events = []

    results = sweep._bounded_dispatch_batch(
        deals,
        listing_timeout_seconds=1.0,
        total_deadline=time.monotonic() + 2.0,
        max_workers=2,
        dispatch_fn=_source_wall_dispatch,
        batch_dispatch_fn=_batch_source_wall_dispatch,
        progress=lambda event, fields: events.append((event, fields)),
    )

    assert results["mercari|00"].status == "blocked"
    assert all(results["mercari|%02d" % index].status == "error"
               for index in range(1, 25))
    assert all("unchecked after source wall" in results["mercari|%02d" % index].detail
               for index in range(1, 25))
    source_event = next(fields for event, fields in events if event == "source_blocked")
    assert source_event["unchecked_count"] == 24
    started = [fields["listing_key"] for event, fields in events if event == "check_start"]
    assert "mercari|20" not in started


def test_sequential_source_wall_does_not_dispatch_remaining_source_rows(
    ledger, monkeypatch,
):
    ledger_db.upsert_deals([
        _seed_deal("mercari|first"),
        _seed_deal("mercari|second"),
        _seed_deal("ebay|other"),
    ], path=ledger)
    monkeypatch.setattr(
        sweep.ledger_db, "load_deals", lambda path=None: _real_load_deals(path=ledger))
    calls = []

    def dispatch(deal):
        calls.append(deal["listing_key"])
        return _source_wall_dispatch(deal)

    report, _ = sweep.sweep(NOW, dispatch_fn=dispatch)

    assert calls == ["mercari|first", "ebay|other"]
    assert [row["listing_key"] for row in report["check_failed"]] == ["mercari|second"]


def test_total_deadline_stops_every_active_check_process(ledger, monkeypatch):
    before = {process.pid for process in multiprocessing.active_children()}
    ledger_db.upsert_deals([
        _seed_deal("mercari|first"),
        _seed_deal("ebay|second"),
        _seed_deal("stockx|third"),
    ], path=ledger)
    monkeypatch.setattr(
        sweep.ledger_db, "load_deals", lambda path=None: _real_load_deals(path=ledger))

    started = time.monotonic()
    with pytest.raises(sweep.SweepDeadlineExceeded) as caught:
        sweep.sweep(
            NOW,
            sweep_timeout_seconds=0.05,
            listing_timeout_seconds=60.0,
            max_workers=3,
            dispatch_fn=_sleeping_dispatch,
        )

    assert caught.value.processed_live_checks == 0
    assert time.monotonic() - started < 1.0
    assert {process.pid for process in multiprocessing.active_children()} == before


def test_external_sigterm_stops_worker_and_descendant(tmp_path):
    pid_path = tmp_path / "expiry-worker-pids.txt"
    context = multiprocessing.get_context("fork")
    process = context.Process(target=_run_batch_until_sigterm, args=(str(pid_path),))
    process.start()
    deadline = time.monotonic() + 3.0
    while not pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_path.exists()
    worker_pid, descendant_pid = map(int, pid_path.read_text().split())

    os.kill(process.pid, signal.SIGTERM)
    process.join(3.0)

    assert process.exitcode == 128 + signal.SIGTERM
    stopped_deadline = time.monotonic() + 2.0
    while (_pid_alive(worker_pid) or _pid_alive(descendant_pid)) \
            and time.monotonic() < stopped_deadline:
        time.sleep(0.01)
    assert not _pid_alive(worker_pid)
    assert not _pid_alive(descendant_pid)


def test_main_default_deadline_covers_observed_622_row_seven_profile_workload(
    monkeypatch, capsys,
):
    observed_rows = 132
    observed_seconds = 6 * 60
    workload_rows = 622
    active_profiles = 7
    rows_per_profile_second = observed_rows / observed_seconds / active_profiles
    projected_seconds = workload_rows / (rows_per_profile_second * active_profiles)
    captured_timeout = []

    def completed_sweep(_now, **kwargs):
        captured_timeout.append(kwargs["sweep_timeout_seconds"])
        return {}, []

    monkeypatch.setattr(sweep, "sweep", completed_sweep)
    monkeypatch.setattr(sys, "argv", ["sweep"])

    assert sweep.main() == 0
    capsys.readouterr()
    assert captured_timeout == [sweep.DEFAULT_SWEEP_TIMEOUT_SECONDS]
    assert sweep.DEFAULT_SWEEP_TIMEOUT_SECONDS > projected_seconds


def test_sweep_deadline_returns_partial_evidence_and_stops_before_next_check(
    ledger, monkeypatch,
):
    ledger_db.upsert_deals([
        _seed_deal("mercari|first"),
        _seed_deal("mercari|second"),
    ], path=ledger)
    monkeypatch.setattr(
        sweep.ledger_db, "load_deals", lambda path=None: _real_load_deals(path=ledger))
    events = []
    clock_values = iter((0.0, 0.5, 2.0))

    def dispatch(_deal):
        return checks.CheckResult("available", "still active")

    with pytest.raises(sweep.SweepDeadlineExceeded) as caught:
        sweep.sweep(
            NOW,
            sweep_timeout_seconds=1.5,
            progress=lambda event, fields: events.append((event, fields)),
            dispatch_fn=dispatch,
            monotonic=lambda: next(clock_values),
        )

    error = caught.value
    assert error.processed_live_checks == 1
    assert error.total_live_checks == 2
    completed = [row["listing_key"] for row in error.report["confirmed_still_active"]]
    assert len(completed) == 1
    assert [row["listing_key"] for row in error.changed] == completed
    assert events[1][1]["listing_key"] == completed[0]
    assert [event for event, _ in events] == [
        "sweep_start", "check_start", "check_done", "deadline_exceeded"]


def test_main_deadline_emits_json_and_never_applies_partial_results(monkeypatch, capsys):
    partial_report = {
        "confirmed_unavailable": [],
        "confirmed_still_active": [{"listing_key": "mercari|first"}],
        "check_failed": [],
        "blocked": [],
        "unreadable_end_date": [],
    }
    partial_changed = [_seed_deal("mercari|first", last_seen_at=NOW.isoformat())]

    def deadline(*_args, **_kwargs):
        raise sweep.SweepDeadlineExceeded(
            partial_report, partial_changed, 1, 633, 900.0, 900.1)

    monkeypatch.setattr(sweep, "sweep", deadline)
    monkeypatch.setattr(
        sweep.ledger_db, "upsert_deals",
        lambda *_args, **_kwargs: pytest.fail("partial sweep result was written"))
    monkeypatch.setattr(sys, "argv", ["sweep", "--apply"])

    assert sweep.main() == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["deadline_exceeded"]["processed_live_checks"] == 1
    assert payload["deadline_exceeded"]["total_live_checks"] == 633
    assert payload["applied"] == []
    assert payload["apply_skipped"] == (
        "sweep deadline exceeded; no partial result was written")
    assert "expire_error sweep deadline reached" in captured.err


# --- the report shape itself --------------------------------------------------

def test_report_never_carries_a_needs_manual_check_key(ledger, monkeypatch):
    monkeypatch.setattr(checks, "dispatch", lambda deal: checks.CheckResult("gone", "x"))
    ledger_db.upsert_deals(
        [_seed_deal("mercari|8008", auction_end_date="not-an-auction"),
         _seed_deal("ebay|9009", auction_end_date="2026-08-01T00:00:00+00:00"),
         _seed_deal("k-bid|1010", auction_end_date="unknown")],
        path=ledger)
    _corrupt_auction_end_date(ledger, "k-bid|1010", "not-a-real-date")
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert "needs_manual_check" not in report
    assert set(report.keys()) == {
        "confirmed_unavailable", "confirmed_still_active",
        "check_failed", "blocked", "unreadable_end_date"}
    assert [e["listing_key"] for e in report["unreadable_end_date"]] == ["k-bid|1010"]


def test_unreadable_date_lands_in_its_own_bucket_untouched(ledger, monkeypatch):
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: pytest.fail("dispatch called for an unreadable date"))
    ledger_db.upsert_deals(
        [_seed_deal("auctionzip|1111", auction_end_date="unknown")],
        path=ledger)
    _corrupt_auction_end_date(ledger, "auctionzip|1111", "August 3, 2026 4:00 PM EDT")
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    assert [e["listing_key"] for e in report["unreadable_end_date"]] == ["auctionzip|1111"]
    assert changed == []


# --- --apply writes one batched upsert_deals(), never save() ----------------

def test_apply_writes_one_batched_upsert_never_a_whole_ledger_save(ledger, monkeypatch):
    monkeypatch.setattr(ledger_db, "save",
                        lambda *a, **k: pytest.fail("save() called -- must be upsert_deals()"))
    monkeypatch.setattr(checks, "dispatch", lambda deal: checks.CheckResult("gone", "gone"))
    ledger_db.upsert_deals(
        [_seed_deal("mercari|1212", auction_end_date="not-an-auction")], path=ledger)
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    upsert_calls = []

    def _spy_upsert(deals, path=ledger_db.DB_PATH):
        upsert_calls.append(deals)
        return _real_upsert_deals(deals, path=ledger)

    monkeypatch.setattr(sweep.ledger_db, "upsert_deals", _spy_upsert)

    report, changed = sweep.sweep(NOW)
    if changed:
        sweep.ledger_db.upsert_deals(changed, path=ledger)

    assert len(upsert_calls) == 1
    assert [d["listing_key"] for d in upsert_calls[0]] == ["mercari|1212"]
    assert ledger_db.get_deal("mercari|1212", path=ledger)["status"] == "unavailable"


# --- _prepare_write_batch: the final write reconciles against the LIVE
# ledger, never the stale in-memory snapshot ------------------------------
#
# A run can sit open for many minutes -- each live check costs up to ~45s
# HTTP + ~60s playwright-cli, across hundreds of candidate rows -- so the
# `changed` list `sweep()` returns may be stale by the time a caller is
# ready to write it. Reproduced here exactly as a reviewer did live: seed a
# row, let the sweep decide it is gone, apply a concurrent status change
# (Adam clicking "rejected" on the deals page) while the sweep's result
# still sits unwritten, then run the final-write step and confirm Adam's
# decision survives instead of being silently reverted.

def test_final_write_skips_a_row_changed_concurrently_during_the_run(ledger, monkeypatch):
    ledger_db.upsert_deals(
        [_seed_deal("mercari|9999", auction_end_date="not-an-auction")], path=ledger)
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: checks.CheckResult("gone", "gone per sweep"))
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)
    assert [d["listing_key"] for d in changed] == ["mercari|9999"]
    assert changed[0]["status"] == "unavailable"

    # Adam rejects the listing from the deals page WHILE the sweep's stale
    # verdict is still sitting in `changed`, unwritten -- a fast, isolated
    # single-column update that commits immediately.
    ledger_db.update_status("mercari|9999", "rejected", NOW.isoformat(), path=ledger)

    to_write, skipped = sweep._prepare_write_batch(changed, path=ledger)

    assert to_write == []
    assert [s["listing_key"] for s in skipped] == ["mercari|9999"]
    # The row is untouched by the (skipped) write -- Adam's decision stands.
    assert ledger_db.get_deal("mercari|9999", path=ledger)["status"] == "rejected"


def test_final_write_applies_a_still_active_rows_sweep_result(ledger, monkeypatch):
    ledger_db.upsert_deals(
        [_seed_deal("mercari|8888", auction_end_date="not-an-auction")], path=ledger)
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: checks.CheckResult("gone", "gone per sweep"))
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    # Nobody touched the row during the run -- its live status is still
    # `active`, so the sweep's verdict is still current and must write
    # through.
    to_write, skipped = sweep._prepare_write_batch(changed, path=ledger)

    assert skipped == []
    assert [d["listing_key"] for d in to_write] == ["mercari|8888"]
    assert to_write[0]["status"] == "unavailable"
    counts = ledger_db.upsert_deals(to_write, path=ledger)
    assert counts == {"inserted": 0, "updated": 1}
    assert ledger_db.get_deal("mercari|8888", path=ledger)["status"] == "unavailable"


def test_final_write_preserves_other_fields_changed_concurrently(ledger, monkeypatch):
    """The merge is built on the FRESH row, not the stale snapshot, so a
    field a concurrent writer touched (anything other than what this sweep
    itself changed) survives too."""
    ledger_db.upsert_deals(
        [_seed_deal("mercari|7777", auction_end_date="not-an-auction")], path=ledger)
    monkeypatch.setattr(checks, "dispatch",
                        lambda deal: checks.CheckResult("available", "still there"))
    monkeypatch.setattr(sweep.ledger_db, "load_deals",
                        lambda path=None: _real_load_deals(path=ledger))

    report, changed = sweep.sweep(NOW)

    concurrent = ledger_db.get_deal("mercari|7777", path=ledger)
    concurrent["current_price"] = 19.99
    ledger_db.upsert_deals([concurrent], path=ledger)

    to_write, skipped = sweep._prepare_write_batch(changed, path=ledger)

    assert skipped == []
    assert to_write[0]["current_price"] == 19.99
    assert to_write[0]["last_seen_at"] == NOW.isoformat()
