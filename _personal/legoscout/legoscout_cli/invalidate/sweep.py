#!/usr/bin/env python3
"""Sweep the ledger for `active` listings and resolve every one of them,
every run, to available/unavailable/blocked -- never to a human hand-off.

Two rules make this tractable, both Adam's:

  1. A listing with a real `auction_end_date` needs NO live check once that
     date has passed -- the date alone is proof the bidding window is closed.
  2. A listing with no usable date (fixed-price `not-an-auction`, or a source
     whose date field is not yet captured, `unknown`) can only be resolved by
     an actual live check -- see `invalidate/checks.py`'s dispatch table.

Only `status == "active"` rows are touched. `inquired`, `bid_placed`,
`purchased`, `rejected`, `unavailable`, `blocked` are Adam's own decisions or
already-terminal states and are never re-evaluated here.

There is no `needs_manual_check` bucket. A 2026-08-08 run left a $400 Mercari
lot sitting sold for two days because it fell into that bucket and nothing
then actually checked it -- the hand-off from sweep to "an agent's crawl will
pick it up" was prose, not code, and depended on someone remembering to act
on the report. Every active row now resolves itself, every run.

Usage:
    legoscout deals expire            # dry run, prints JSON report
    legoscout deals expire --apply    # also writes confirmed rows back to
                                       # the ledger, batched in ONE
                                       # ledger_db.upsert_deals() call
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from multiprocessing.connection import Connection, wait
from typing import Any, Callable

# This module owns the sweep, not the ledger's access layer. Every read and
# write of the deal ledger goes through `legoscout_cli.ledger.db`; nothing
# here opens `found_deals.db` itself.
from ..ledger import db as ledger_db  # noqa: E402
from . import checks  # noqa: E402

LEDGER = ledger_db.DB_PATH

# `checks.py` owns the namespace parse; this module reuses it rather than
# keeping a second copy.
namespace = checks.namespace

# How long a row that was just confirmed still-active is trusted before the
# next run will spend a live check on it again. One named constant so it is
# easy to tune later, per Adam's instruction.
LIVE_CHECK_COOLDOWN_HOURS = 12

# A sweep used to have no wall-clock bound. On 2026-08-15, the concurrent
# scheduler completed 132 of 622 rows in six minutes across seven serialized
# source profiles. That measured workload projects to 28.3 minutes. Keep a
# finite 45-minute default, while the CLI option permits deliberate tuning.
DEFAULT_SWEEP_TIMEOUT_SECONDS = 45 * 60
DEFAULT_LISTING_TIMEOUT_SECONDS = 3 * 60
DEFAULT_MAX_CONCURRENT_CHECKS = 8
_WORKER_STOP_GRACE_SECONDS = 2.0

# These checks can all reach the same unnamed `playwright-cli` session. They
# must never overlap. Every namespace not present in `checks.CHECKS` routes to
# `check_generic`, which uses that same session too. Other source CLIs own
# separate saved profiles, so one check per namespace can run concurrently.
_PLAYWRIGHT_NAMESPACES = frozenset({
    "poshmark", "auctionninja", "liveauctioneers", "proxibid",
})
_PLAYWRIGHT_SERIALIZATION_KEY = "playwright-cli:default"


class Unreadable(ValueError):
    """An `auction_end_date` this sweep cannot compare against the clock."""


class SweepDeadlineExceeded(RuntimeError):
    """The sweep reached its hard deadline before every live check ran."""

    def __init__(
        self,
        report: dict[str, Any],
        changed: list[dict[str, Any]],
        processed_live_checks: int,
        total_live_checks: int,
        timeout_seconds: float,
        elapsed_seconds: float,
    ) -> None:
        super().__init__(
            "sweep deadline reached after %.1f seconds (%d/%d live checks completed)"
            % (elapsed_seconds, processed_live_checks, total_live_checks))
        self.report = report
        self.changed = changed
        self.processed_live_checks = processed_live_checks
        self.total_live_checks = total_live_checks
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds


class _BatchDeadlineExceeded(RuntimeError):
    """The concurrent live-check batch reached the sweep deadline."""

    def __init__(self, results: dict[str, checks.CheckResult]) -> None:
        super().__init__("live-check batch deadline reached")
        self.results = results


@dataclass
class _ActiveCheck:
    deals: list[dict[str, Any]]
    serialization_key: str
    process: multiprocessing.Process
    recv_conn: Connection
    start_event: Any
    started_at: float
    process_group_ready: bool = False


# The schema's own two answers for "there is no end date", plus the spellings
# the ledger held before the schema was enforced. These are ANSWERS, so they
# are not past and not unreadable -- they are exactly the rows that need a
# live check instead of a date comparison.
NO_END_DATE = ("unknown", "not-an-auction", "n/a", "none", "null", "")


_DATE_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?"
    r"(Z|[+-]\d{2}:?\d{2})?")

# Every source this project reads is a US site, and no US timezone sits more
# than this far from UTC (Hawaii is UTC-10). A stored timestamp with no
# explicit offset is read as if it were UTC and must clear this margin
# before `parse_past` calls it past -- otherwise a same-day close time
# stored in the site's own local clock (no offset) reads as already elapsed
# the instant the sweep's UTC clock crosses midnight, even though the real
# Pacific-time deadline is still hours away. This is not theoretical: live on
# 2026-08-09, a run at 00:12 UTC marked 8 ShopGoodwill and 7 Shop The
# Salvation Army rows `unavailable` this way, every one of them still open
# with real time left on the clock when independently re-checked minutes
# later. The bare `dt.date() < now.date()` comparison this replaced is what
# caused it -- it discarded whatever time-of-day the value carried.
_NAIVE_TIMEZONE_MARGIN = timedelta(hours=12)


def parse_past(auction_end_date: str | None, now: datetime) -> bool:
    """Whether the auction has already closed.

    Raises `Unreadable` for a value that is neither a sentinel nor an ISO
    date. It used to return False, which reads as "the auction has not
    ended" -- so a row whose date this cannot parse could NEVER expire. On
    2026-08-06 the ledger held 39 such rows, including 7 active
    LiveAuctioneers lots and 2 AuctionZip lots storing "August 3, 2026 4:00
    PM EDT". They were invisible to this sweep and stayed active
    indefinitely.

    A value carrying an explicit UTC offset (or `Z`) is compared as the
    exact instant it names. A value with a time-of-day but no offset, or
    with no time-of-day at all, is read at its LATEST plausible instant
    (end of that second, or end of that day) and must additionally clear
    `_NAIVE_TIMEZONE_MARGIN` -- see that constant for why.
    """
    if auction_end_date is None or str(auction_end_date).strip().lower() in NO_END_DATE:
        return False
    m = _DATE_RE.match(str(auction_end_date))
    if not m:
        raise Unreadable(
            "auction_end_date %r is neither an ISO date nor one of %s -- fix "
            "the source reader so it stores `YYYY-MM-DD...`, rather than "
            "leaving a row that can never expire"
            % (str(auction_end_date)[:120], "/".join(NO_END_DATE[:2])))
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    has_time = m.group(4) is not None
    hour = int(m.group(4)) if has_time else 23
    minute = int(m.group(5)) if has_time else 59
    second = int(m.group(6)) if m.group(6) else (59 if not has_time else 0)
    offset_raw = m.group(7)
    try:
        if offset_raw:
            offset_text = "+00:00" if offset_raw == "Z" else offset_raw
            if len(offset_text) == 5:  # "+0700" -> "+07:00"
                offset_text = offset_text[:3] + ":" + offset_text[3:]
            candidate = datetime.fromisoformat(
                "%04d-%02d-%02dT%02d:%02d:%02d%s"
                % (year, month, day, hour, minute, second, offset_text))
            return candidate < now
        candidate = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError as exc:
        raise Unreadable("auction_end_date %r is not a real date: %s"
                         % (str(auction_end_date)[:120], exc)) from None
    return (now - candidate) > _NAIVE_TIMEZONE_MARGIN


def _is_no_date(auction_end_date: str | None) -> bool:
    return auction_end_date is None or str(auction_end_date).strip().lower() in NO_END_DATE


def _parse_last_seen(value: str | None) -> datetime | None:
    """`last_seen_at` as an aware datetime, or None if absent/unparseable.

    A row with no readable `last_seen_at` has never been confirmed, so it is
    never in cooldown -- None means "check it", not "skip it".
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _in_cooldown(deal: dict[str, Any], now: datetime) -> bool:
    last_seen = _parse_last_seen(deal.get("last_seen_at"))
    if last_seen is None:
        return False
    return now - last_seen < timedelta(hours=LIVE_CHECK_COOLDOWN_HOURS)


#  Which top-level fields a changed row's write actually touches, keyed by
# the same shape every mutation branch below uses. `_prepare_write_batch`
# reads this off each `changed` entry (as `deal["_sweep_fields"]`) so its
# final merge onto a freshly re-fetched row copies ONLY what this sweep
# meant to change -- never a whole stale snapshot. Never a ledger field
# itself: stripped by construction, since `_prepare_write_batch` builds its
# merged row from the FRESH read, not from `deal`, and only ever copies
# these named keys onto it.
_STATUS_CHANGE_FIELDS = ("status", "last_status", "last_seen_at", "notes")
_STILL_ACTIVE_FIELDS = ("last_seen_at",)


def _check_worker(
    send_conn,
    start_event,
    deals: list[dict[str, Any]],
    dispatch_fn: Callable,
    batch_dispatch_fn: Callable | None,
) -> None:
    """Run one live check in an isolated process group."""
    try:
        os.setsid()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        send_conn.send(("ready",))
        start_event.wait()
        if batch_dispatch_fn is not None and len(deals) > 1:
            results = batch_dispatch_fn(deals)
        else:
            deal = deals[0]
            results = {deal["listing_key"]: dispatch_fn(deal)}
        send_conn.send((
            "results",
            [(key, result.status, result.detail, result.stop_source)
             for key, result in results.items()],
        ))
    except BaseException as exc:  # noqa: BLE001 - relay the exact child failure
        try:
            send_conn.send(("exception", type(exc).__name__, str(exc)))
        except (BrokenPipeError, OSError):
            pass
    finally:
        send_conn.close()


def _signal_worker(worker: _ActiveCheck, sig: int) -> None:
    """Signal one worker or its complete process group."""
    try:
        if worker.process_group_ready:
            os.killpg(worker.process.pid, sig)
        elif worker.process.is_alive():
            os.kill(worker.process.pid, sig)
    except ProcessLookupError:
        pass


def _signal_and_join(
    workers: list[_ActiveCheck], sig: int,
) -> list[_ActiveCheck]:
    for worker in workers:
        _signal_worker(worker, sig)
    deadline = time.monotonic() + _WORKER_STOP_GRACE_SECONDS
    for worker in workers:
        worker.process.join(max(0.0, deadline - time.monotonic()))
    return [worker for worker in workers if worker.process.is_alive()]


def _stop_workers(workers: list[_ActiveCheck]) -> None:
    """Stop every active process group within one shared grace period."""
    if not workers:
        return
    survivors = _signal_and_join(workers, signal.SIGTERM)
    remaining_workers = _signal_and_join(survivors, signal.SIGKILL)
    remaining = [worker.process.pid for worker in remaining_workers]
    if remaining:
        raise RuntimeError(
            "listing check processes did not stop: %s"
            % ", ".join(str(pid) for pid in remaining))


def _serialization_key(deal: dict[str, Any]) -> str:
    source_namespace = namespace(deal.get("listing_key", ""))
    if (source_namespace in _PLAYWRIGHT_NAMESPACES
            or source_namespace not in checks.CHECKS):
        return _PLAYWRIGHT_SERIALIZATION_KEY
    return "source:%s" % source_namespace


def _unchecked_after_source_wall(
    deal: dict[str, Any], blocker_key: str, blocker_detail: str,
) -> checks.CheckResult:
    return checks.CheckResult(
        "error",
        "unchecked after source wall at %s: %s"
        % (blocker_key, blocker_detail),
    )


def _raise_sigterm(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def _start_worker(
    context,
    deals: list[dict[str, Any]],
    serialization_key: str,
    dispatch_fn: Callable[[dict[str, Any]], checks.CheckResult],
    batch_dispatch_fn: Callable[[list[dict[str, Any]]], dict[str, checks.CheckResult]] | None,
    monotonic: Callable[[], float],
) -> _ActiveCheck:
    recv_conn, send_conn = context.Pipe(duplex=False)
    start_event = context.Event()
    process = context.Process(
        target=_check_worker,
        args=(send_conn, start_event, deals, dispatch_fn, batch_dispatch_fn),
    )
    process.start()
    send_conn.close()
    return _ActiveCheck(
        deals=deals,
        serialization_key=serialization_key,
        process=process,
        recv_conn=recv_conn,
        start_event=start_event,
        started_at=monotonic(),
    )


def _bounded_dispatch_batch(
    deals: list[dict[str, Any]],
    *,
    listing_timeout_seconds: float,
    total_deadline: float | None,
    max_workers: int,
    dispatch_fn: Callable[[dict[str, Any]], checks.CheckResult],
    batch_dispatch_fn: Callable[
        [list[dict[str, Any]]], dict[str, checks.CheckResult]
    ] | None = None,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, checks.CheckResult]:
    """Run bounded checks concurrently without sharing a source profile."""
    if listing_timeout_seconds <= 0:
        raise ValueError("listing timeout must be greater than zero")
    if max_workers <= 0:
        raise ValueError("max workers must be greater than zero")
    if not deals:
        return {}

    profile_deals: dict[str, list[dict[str, Any]]] = {}
    for deal in deals:
        key = _serialization_key(deal)
        profile_deals.setdefault(key, []).append(deal)
    queues: dict[str, deque[list[dict[str, Any]]]] = {}
    for key, items in profile_deals.items():
        source_namespace = namespace(items[0]["listing_key"])
        batch_size = (
            checks.BATCH_SIZES.get(source_namespace, 1)
            if batch_dispatch_fn is not None else 1
        )
        queues[key] = deque(
            items[start:start + batch_size]
            for start in range(0, len(items), batch_size)
        )
    context = multiprocessing.get_context("fork")
    active: dict[Connection, _ActiveCheck] = {}
    busy_keys: set[str] = set()
    results: dict[str, checks.CheckResult] = {}
    launched = 0
    previous_sigterm = signal.signal(signal.SIGTERM, _raise_sigterm)

    def launch_ready_profiles() -> None:
        nonlocal launched
        for serialization_key, queue in queues.items():
            if len(active) >= max_workers:
                break
            if serialization_key in busy_keys or not queue:
                continue
            task_deals = queue.popleft()
            worker = _start_worker(
                context, task_deals, serialization_key, dispatch_fn,
                batch_dispatch_fn, monotonic)
            active[worker.recv_conn] = worker
            busy_keys.add(serialization_key)
            for deal in task_deals:
                launched += 1
                if progress:
                    progress("check_start", {
                        "index": launched,
                        "total": len(deals),
                        "listing_key": deal["listing_key"],
                        "source": deal.get("source"),
                    })

    def finish(
        worker: _ActiveCheck,
        worker_results: dict[str, checks.CheckResult],
    ) -> None:
        if worker.process.is_alive():
            worker.process.join(_WORKER_STOP_GRACE_SECONDS)
        if worker.process.is_alive():
            _stop_workers([worker])
        worker.recv_conn.close()
        active.pop(worker.recv_conn, None)
        busy_keys.remove(worker.serialization_key)
        task_by_key = {deal["listing_key"]: deal for deal in worker.deals}
        unexpected = set(worker_results) - set(task_by_key)
        if unexpected:
            raise RuntimeError(
                "batch check returned unexpected rows: %s"
                % ", ".join(sorted(unexpected)))
        blockers = [
            (key, result) for key, result in worker_results.items()
            if result.stop_source
        ]
        if len(blockers) > 1:
            raise RuntimeError("batch check returned more than one source blocker")
        if blockers and len(worker_results) != 1:
            raise RuntimeError("source blocker must be the batch's only returned result")
        missing = set(task_by_key) - set(worker_results)
        if missing and not blockers:
            raise RuntimeError(
                "batch check omitted rows without a source blocker: %s"
                % ", ".join(sorted(missing)))
        blocker_key = None
        blocker_result = None
        if blockers:
            blocker_key, blocker_result = blockers[0]
            for key in missing:
                worker_results[key] = _unchecked_after_source_wall(
                    task_by_key[key], blocker_key, blocker_result.detail)
        for deal in worker.deals:
            listing_key = deal["listing_key"]
            result = worker_results[listing_key]
            results[listing_key] = result
            if progress:
                progress("check_done", {
                    "index": len(results),
                    "total": len(deals),
                    "listing_key": listing_key,
                    "status": result.status,
                    "detail": result.detail,
                })
        if blocker_result is None:
            return
        source_namespace = namespace(blocker_key)
        active_same_source = [
            deal["listing_key"]
            for item in active.values()
            for deal in item.deals
            if namespace(deal["listing_key"]) == source_namespace
        ]
        if active_same_source:
            raise RuntimeError(
                "source wall found with concurrent same-source checks: %s"
                % ", ".join(active_same_source))
        unchecked: list[dict[str, Any]] = []
        for queue in queues.values():
            retained = deque()
            while queue:
                pending_task = queue.popleft()
                if namespace(pending_task[0]["listing_key"]) == source_namespace:
                    unchecked.extend(pending_task)
                else:
                    retained.append(pending_task)
            queue.extend(retained)
        for pending in unchecked:
            results[pending["listing_key"]] = _unchecked_after_source_wall(
                pending, blocker_key, blocker_result.detail)
        if progress:
            progress("source_blocked", {
                "source": source_namespace,
                "blocker_listing_key": blocker_key,
                "unchecked_count": len(missing) + len(unchecked),
                "detail": blocker_result.detail,
            })

    try:
        while len(results) < len(deals):
            launch_ready_profiles()
            now_value = monotonic()
            if len(results) == len(deals):
                break
            if total_deadline is not None and now_value >= total_deadline:
                raise _BatchDeadlineExceeded(dict(results))
            if not active:
                raise RuntimeError("live-check scheduler has pending rows but no active worker")
            nearest_row_deadline = min(
                worker.started_at + listing_timeout_seconds
                for worker in active.values())
            next_deadline = nearest_row_deadline
            if total_deadline is not None:
                next_deadline = min(next_deadline, total_deadline)
            ready_connections = wait(
                list(active), timeout=max(0.0, next_deadline - now_value))

            for recv_conn in ready_connections:
                worker = active.get(recv_conn)
                if worker is None:
                    continue
                try:
                    message = recv_conn.recv()
                except EOFError:
                    raise RuntimeError(
                        "live check child exited without a result for %s"
                        % worker.deal["listing_key"]) from None
                if message == ("ready",):
                    worker.process_group_ready = True
                    worker.start_event.set()
                    continue
                if message[0] == "results":
                    finish(worker, {
                        key: checks.CheckResult(status, detail, stop_source)
                        for key, status, detail, stop_source in message[1]
                    })
                    continue
                if message[0] == "exception":
                    raise RuntimeError(
                        "live check child raised %s: %s"
                        % (message[1], message[2]))
                raise RuntimeError(
                    "live check child returned an unknown message: %r" % (message,))

            now_value = monotonic()
            if len(results) == len(deals):
                break
            if total_deadline is not None and now_value >= total_deadline:
                raise _BatchDeadlineExceeded(dict(results))
            expired = [
                worker for worker in list(active.values())
                if now_value - worker.started_at >= listing_timeout_seconds
            ]
            for worker in expired:
                _stop_workers([worker])
                finish(worker, {
                    deal["listing_key"]: checks.CheckResult(
                        "error",
                        "live check exceeded %.1f-second limit"
                        % listing_timeout_seconds,
                    )
                    for deal in worker.deals
                })
        return results
    finally:
        try:
            _stop_workers(list(active.values()))
        finally:
            for worker in active.values():
                worker.recv_conn.close()
            signal.signal(signal.SIGTERM, previous_sigterm)


def _bounded_dispatch(
    deal: dict[str, Any],
    timeout_seconds: float,
    dispatch_fn: Callable[[dict[str, Any]], checks.CheckResult],
) -> checks.CheckResult:
    """Run one check with a hard wall-clock limit and descendant cleanup."""
    return _bounded_dispatch_batch(
        [deal],
        listing_timeout_seconds=timeout_seconds,
        total_deadline=None,
        max_workers=1,
        dispatch_fn=dispatch_fn,
    )[deal["listing_key"]]


def _stderr_progress(event: str, fields: dict[str, Any]) -> None:
    """Write one stable progress record without corrupting JSON stdout."""
    values = " ".join(
        "%s=%s" % (key, json.dumps(value, ensure_ascii=True, separators=(",", ":")))
        for key, value in fields.items())
    sys.stderr.write("expire_progress event=%s%s\n" % (event, " " + values if values else ""))
    sys.stderr.flush()


def _record_live_result(
    deal: dict[str, Any],
    result: checks.CheckResult,
    now_iso: str,
    report: dict[str, list[dict[str, Any]]],
    changed: list[dict[str, Any]],
) -> None:
    key = deal["listing_key"]
    entry = {
        "listing_key": key,
        "source": deal.get("source"),
        "auction_end_date": deal.get("auction_end_date"),
        "status": result.status,
        "evidence": result.detail,
    }
    if result.status == "gone":
        report["confirmed_unavailable"].append(entry)
        deal["status"] = "unavailable"
        deal["last_status"] = "unavailable"
        deal["last_seen_at"] = now_iso
        deal["notes"] = (
            deal.get("notes", "")
            + " [Marked unavailable %s by invalidate/sweep.py: %s]"
            % (now_iso, result.detail)
        ).strip()
        deal["_sweep_fields"] = _STATUS_CHANGE_FIELDS
        changed.append(deal)
    elif result.status == "available":
        report["confirmed_still_active"].append(entry)
        deal["last_seen_at"] = now_iso
        deal["_sweep_fields"] = _STILL_ACTIVE_FIELDS
        changed.append(deal)
    elif result.status == "blocked":
        report["blocked"].append(entry)
        deal["status"] = "blocked"
        deal["last_status"] = "blocked"
        deal["last_seen_at"] = now_iso
        deal["notes"] = (
            deal.get("notes", "")
            + " [Marked blocked %s by invalidate/sweep.py: %s]"
            % (now_iso, result.detail)
        ).strip()
        deal["_sweep_fields"] = _STATUS_CHANGE_FIELDS
        changed.append(deal)
    else:
        report["check_failed"].append(entry)


def sweep(
    now: datetime,
    *,
    sweep_timeout_seconds: float | None = None,
    listing_timeout_seconds: float | None = None,
    max_workers: int = DEFAULT_MAX_CONCURRENT_CHECKS,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
    dispatch_fn: Callable[[dict[str, Any]], checks.CheckResult] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve every active row. Returns (report, changed_rows).

    `changed_rows` are the mutated deal dicts a caller writes back -- but
    NOT directly: a run can take many minutes (each live check costs up to
    ~45s HTTP + ~60s playwright-cli, across hundreds of candidate rows), so
    by the time a caller is ready to write, one of these rows may already
    have moved under it (Adam's own click on the deals page, a concurrent
    `update_status()`). Pass `changed_rows` through `_prepare_write_batch()`
    first -- see that function -- and write ONLY what it returns, via ONE
    `ledger_db.upsert_deals()` call. This function never writes the ledger
    itself, and never calls `ledger_db.mark_unavailable()` /
    `mark_blocked()` per row: those are the single-row primitives for an
    ad-hoc confirmation, and calling either in a loop here would be hundreds
    of separate transactions for one run instead of one.
    """
    if sweep_timeout_seconds is not None and sweep_timeout_seconds <= 0:
        raise ValueError("sweep timeout must be greater than zero")
    if listing_timeout_seconds is not None and listing_timeout_seconds <= 0:
        raise ValueError("listing timeout must be greater than zero")
    if max_workers <= 0:
        raise ValueError("max workers must be greater than zero")

    now_iso = now.isoformat()
    started = monotonic()
    deals = ledger_db.load_deals()
    live_candidates = [
        deal for deal in deals
        if deal.get("status") == "active"
        and _is_no_date(deal.get("auction_end_date"))
        and not _in_cooldown(deal, now)
    ]
    total_live_checks = len(live_candidates)
    dispatch_fn = dispatch_fn or checks.dispatch
    batch_dispatch_fn = checks.dispatch_batch if dispatch_fn is checks.dispatch else None
    if progress:
        progress("sweep_start", {
            "active_rows": sum(deal.get("status") == "active" for deal in deals),
            "live_checks": total_live_checks,
            "sweep_timeout_seconds": sweep_timeout_seconds,
            "listing_timeout_seconds": listing_timeout_seconds,
            "max_workers": max_workers,
        })
    report: dict[str, list[dict[str, Any]]] = {
        "confirmed_unavailable": [],
        "confirmed_still_active": [],
        "check_failed": [],
        "blocked": [],
        # A row whose end date this cannot read. It is REPORTED rather than
        # skipped: silently skipping it is what let 39 rows sit unexpirable.
        "unreadable_end_date": [],
    }
    changed: list[dict[str, Any]] = []

    for deal in deals:
        if deal.get("status") != "active":
            continue
        key = deal["listing_key"]
        source = deal.get("source")
        auction_end_date = deal.get("auction_end_date")

        try:
            past = parse_past(auction_end_date, now)
        except Unreadable as exc:
            report["unreadable_end_date"].append(
                {"listing_key": key, "source": source,
                 "auction_end_date": auction_end_date, "why": str(exc)})
            continue

        if not _is_no_date(auction_end_date):
            if not past:
                continue  # a real date still in the future: nothing to do
            # A real date already in the past is sufficient proof on its own
            # -- no live check runs.
            evidence = "Auction end date %s has passed (checked %s)" % (auction_end_date, now_iso)
            report["confirmed_unavailable"].append(
                {"listing_key": key, "source": source, "auction_end_date": auction_end_date,
                 "evidence": evidence})
            deal["status"] = "unavailable"
            deal["last_status"] = "unavailable"
            deal["last_seen_at"] = now_iso
            deal["notes"] = (deal.get("notes", "")
                             + " [Marked unavailable %s by invalidate/sweep.py: %s]" % (now_iso, evidence)).strip()
            deal["_sweep_fields"] = _STATUS_CHANGE_FIELDS
            changed.append(deal)
            continue

        # No usable date: `live_candidates` owns this row below.

    if listing_timeout_seconds is None:
        live_results: dict[str, checks.CheckResult] = {}
        source_blockers: dict[str, tuple[str, str]] = {}
        for position, deal in enumerate(live_candidates):
            elapsed = monotonic() - started
            if sweep_timeout_seconds is not None and elapsed >= sweep_timeout_seconds:
                if progress:
                    progress("deadline_exceeded", {
                        "processed_live_checks": len(live_results),
                        "total_live_checks": total_live_checks,
                    })
                for candidate in live_candidates:
                    result = live_results.get(candidate["listing_key"])
                    if result is not None:
                        _record_live_result(candidate, result, now_iso, report, changed)
                raise SweepDeadlineExceeded(
                    report, changed, len(live_results), total_live_checks,
                    sweep_timeout_seconds, elapsed)
            source_namespace = namespace(deal["listing_key"])
            blocker = source_blockers.get(source_namespace)
            if blocker is not None:
                live_results[deal["listing_key"]] = _unchecked_after_source_wall(
                    deal, blocker[0], blocker[1])
                continue
            if progress:
                progress("check_start", {
                    "index": len(live_results) + 1,
                    "total": total_live_checks,
                    "listing_key": deal["listing_key"],
                    "source": deal.get("source"),
                })
            result = dispatch_fn(deal)
            live_results[deal["listing_key"]] = result
            if progress:
                progress("check_done", {
                    "index": len(live_results),
                    "total": total_live_checks,
                    "listing_key": deal["listing_key"],
                    "status": result.status,
                    "detail": result.detail,
                })
            if result.stop_source:
                source_blockers[source_namespace] = (
                    deal["listing_key"], result.detail)
                if progress:
                    unchecked_count = sum(
                        namespace(candidate["listing_key"]) == source_namespace
                        for candidate in live_candidates[position + 1:])
                    progress("source_blocked", {
                        "source": source_namespace,
                        "blocker_listing_key": deal["listing_key"],
                        "unchecked_count": unchecked_count,
                        "detail": result.detail,
                    })
    else:
        total_deadline = (
            None if sweep_timeout_seconds is None
            else started + sweep_timeout_seconds
        )
        try:
            live_results = _bounded_dispatch_batch(
                live_candidates,
                listing_timeout_seconds=listing_timeout_seconds,
                total_deadline=total_deadline,
                max_workers=max_workers,
                dispatch_fn=dispatch_fn,
                batch_dispatch_fn=batch_dispatch_fn,
                progress=progress,
                monotonic=monotonic,
            )
        except _BatchDeadlineExceeded as exc:
            elapsed = monotonic() - started
            for deal in live_candidates:
                result = exc.results.get(deal["listing_key"])
                if result is not None:
                    _record_live_result(deal, result, now_iso, report, changed)
            if progress:
                progress("deadline_exceeded", {
                    "processed_live_checks": len(exc.results),
                    "total_live_checks": total_live_checks,
                })
            raise SweepDeadlineExceeded(
                report, changed, len(exc.results), total_live_checks,
                sweep_timeout_seconds, elapsed) from None

    processed_live_checks = len(live_results)
    for deal in live_candidates:
        result = live_results.get(deal["listing_key"])
        if result is not None:
            _record_live_result(deal, result, now_iso, report, changed)

    if progress:
        progress("sweep_done", {
            "processed_live_checks": processed_live_checks,
            "total_live_checks": total_live_checks,
        })
    return report, changed


def _prepare_write_batch(
    changed: list[dict[str, Any]], path: str = LEDGER
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconcile `sweep()`'s stale in-memory verdicts against the ledger's
    CURRENT state, right before the one batched write. Returns
    (rows_to_write, skipped).

    A run can sit open for many minutes, and `changed` was built from a
    `load_deals()` snapshot taken at the very start of it. If Adam acts on
    one of these listing_keys from the deals display page while the sweep
    is still mid-run -- a fast, single-column `update_status()` that
    commits immediately -- the sweep's later batched write would otherwise
    overwrite his decision back to whatever it computed from that stale
    snapshot, silently, with no error. Reproduced live: seed a row, run the
    sweep, apply a concurrent `update_status(..., "rejected", ...)` while
    the sweep's result sits unwritten, then run the old unconditional
    `upsert_deals(changed)` -- the row's status reverted from `rejected`
    back to whatever the sweep decided.

    For each row, this re-fetches the CURRENT ledger record with
    `ledger_db.get_deal()` and checks its live `status`:

      - No longer `active` (or the row is gone entirely) -> DROPPED from the
        write batch. Someone else already acted on it during this run;
        `skipped` names it so the caller can report it, but it is never
        overwritten.
      - Still `active` -> this sweep's verdict is still current. The row to
        write is the FRESH record (so any OTHER field a concurrent writer
        touched survives) with only `deal["_sweep_fields"]` copied on top --
        the exact set of fields this sweep's own branch changed, never a
        whole stale snapshot.
    """
    to_write: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for deal in changed:
        key = deal["listing_key"]
        fresh = ledger_db.get_deal(key, path=path)
        if fresh is None:
            skipped.append({"listing_key": key,
                            "why": "listing_key no longer exists in the ledger"})
            continue
        if fresh.get("status") != "active":
            skipped.append({
                "listing_key": key,
                "why": "status changed to %r during this run -- not overwritten"
                       % fresh.get("status"),
            })
            continue
        merged = dict(fresh)
        for field in deal.get("_sweep_fields", ()):
            merged[field] = deal.get(field)
        to_write.append(merged)
    return to_write, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write confirmed/blocked records back to the ledger, "
                             "batched in one upsert_deals() call")
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_SWEEP_TIMEOUT_SECONDS,
        help="hard limit for the complete sweep (default: %(default)s)")
    parser.add_argument(
        "--listing-timeout-seconds", type=float,
        default=DEFAULT_LISTING_TIMEOUT_SECONDS,
        help="hard limit for one live listing check (default: %(default)s)")
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    if args.listing_timeout_seconds <= 0:
        parser.error("--listing-timeout-seconds must be greater than zero")

    now = datetime.now(timezone.utc)
    try:
        report, changed = sweep(
            now,
            sweep_timeout_seconds=args.timeout_seconds,
            listing_timeout_seconds=args.listing_timeout_seconds,
            progress=_stderr_progress,
        )
    except SweepDeadlineExceeded as exc:
        report = exc.report
        report["deadline_exceeded"] = {
            "timeout_seconds": exc.timeout_seconds,
            "elapsed_seconds": round(exc.elapsed_seconds, 3),
            "processed_live_checks": exc.processed_live_checks,
            "total_live_checks": exc.total_live_checks,
        }
        report["applied"] = []
        if args.apply:
            report["apply_skipped"] = (
                "sweep deadline exceeded; no partial result was written")
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.stdout.flush()
        sys.stderr.write("expire_error %s\n" % exc)
        sys.stderr.flush()
        return 1

    if args.apply and changed:
        # Re-fetch each row's CURRENT ledger state right before the write --
        # see `_prepare_write_batch()` -- so a decision Adam made on the
        # deals page while this run was still checking other rows is never
        # overwritten by a stale in-memory snapshot.
        to_write, skipped = _prepare_write_batch(changed)
        if skipped:
            report["skipped_due_to_concurrent_change"] = skipped
        if to_write:
            counts = ledger_db.upsert_deals(to_write)
            report["applied"] = [d["listing_key"] for d in to_write]
            report["applied_counts"] = counts
        else:
            report["applied"] = []
    else:
        report["applied"] = []

    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
