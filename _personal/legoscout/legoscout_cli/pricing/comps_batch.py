"""`legoscout pricing comps-batch`: the whole appraiser batch in ONE command.

The appraiser used to loop `legoscout pricing comps` once per candidate, serially,
inside the agent's own reasoning. Each call is a fresh Typer process doing 3
BrickLink subprocess round-trips plus an eBay browser-session scrape -- and the
agent sat between calls doing nothing but deciding what to type next. A
25-candidate batch is therefore 25 serial process launches plus 25 serial
network waits for work that is entirely independent per candidate.

This module owns the loop instead: one process, candidates priced concurrently
on a thread pool (the caches are lock-safe for concurrent writers --
`json_cache.update` holds an exclusive flock across re-read/merge/write), each
result exactly what `pricing comps` would have printed for that candidate, with
`listing_key` attached.

The agent still owns nothing numeric: it passes the classifier's hand-off
through verbatim and returns this command's JSON verbatim.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import comps as comps_module

# eBay's comps search is a browser-session scrape, not a token API. A wide
# parallel fan-out against it invites throttling or a bot check, which would
# cost far more time than parallelism saves -- so the pool is deliberately
# narrow. BrickLink is a token API behind its own CLI and tolerates this width
# comfortably; both lookups for one candidate run inside the same worker, so
# this bound caps the eBay concurrency directly.
DEFAULT_WORKERS = 4


def parse_handoff(raw: str, label: str = "hand-off") -> list[dict[str, Any]]:
    """Parse the batch hand-off file into candidate dicts, loudly."""
    try:
        with open(raw, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ValueError("%s is not readable: %s" % (label, exc)) from None
    except json.JSONDecodeError as exc:
        raise ValueError("%s is not valid JSON: %s" % (label, exc)) from None
    if not isinstance(data, list):
        raise ValueError(
            "%s root must be an array of hand-off objects, got %s"
            % (label, type(data).__name__))
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError("%s[%d] must be an object, got %s"
                             % (label, index, type(entry).__name__))
        key = entry.get("listing_key")
        if not isinstance(key, str) or not key:
            raise ValueError("%s[%d] has no non-empty listing_key" % (label, index))
    keys = [entry["listing_key"] for entry in data]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError("%s has duplicate listing_key values: %s"
                         % (label, ", ".join(duplicates)))
    return data


def price_one(handoff: dict[str, Any], limit: int) -> dict[str, Any]:
    """Price exactly one candidate: the same decision `comps.main` makes.

    Calls the same functions the `pricing comps` command calls -- never a
    reimplementation -- and attaches `listing_key`. A failure pricing one
    candidate becomes that candidate's own blocked result; it never fails the
    batch, because every other candidate priced independently around it.
    """
    key = handoff.get("listing_key")
    category = handoff.get("listing_category")
    try:
        if category == "set":
            set_numbers = handoff.get("set_numbers")
            condition = handoff.get("condition")
            if not isinstance(set_numbers, list) or not set_numbers:
                return {
                    "listing_key": key, "mode": "set", "blocked": True,
                    "blocker": ("classifier handed off no set_numbers -- the "
                                "candidate was never identified"),
                }
            if condition not in ("N", "U"):
                return {
                    "listing_key": key, "mode": "set", "blocked": True,
                    "blocker": "condition must be 'N' or 'U', got %r" % (condition,),
                }
            result = comps_module.set_comps(
                set_numbers, condition, description=handoff.get("description"),
                limit=limit)
        elif category == "bulk":
            description = handoff.get("description")
            if not isinstance(description, str) or not description.strip():
                return {
                    "listing_key": key, "mode": "bulk", "blocked": True,
                    "blocker": "--description is required in bulk mode",
                }
            result = comps_module.bulk_comps(
                description, dollars_per_lb=handoff.get("dollars_per_lb"), limit=limit)
        elif category == "minifigure":
            return {
                "listing_key": key,
                "mode": "minifigure",
                "blocked": True,
                "blocker": (
                    "minifigure pricing moved to legoscout minifig "
                    "detect|identify|price"),
            }
        elif category == "excluded":
            blocker = handoff.get("exclusion_reason")
            if not isinstance(blocker, str) or not blocker.strip():
                return {
                    "listing_key": key, "mode": "excluded", "blocked": True,
                    "blocker": ("excluded at classification but no exclusion_reason "
                                "handed off -- the classifier must state why"),
                }
            result = comps_module.excluded_comps(blocker)
        else:
            return {
                "listing_key": key, "mode": None, "blocked": True,
                "blocker": ("listing_category must be 'set', 'bulk', 'minifigure', "
                            "or 'excluded', got %r -- never guess the mode"
                            % (category,)),
            }
    except Exception as exc:  # noqa: BLE001 -- one candidate's defect, reported by key
        return {
            "listing_key": key, "mode": None, "blocked": True,
            "blocker": "%s: %s" % (type(exc).__name__, exc),
        }
    result["listing_key"] = key
    return result


def run_batch(candidates: list[dict[str, Any]], workers: int, limit: int,
              executor_factory: Callable[[int], Any] = ThreadPoolExecutor,
              clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Price every candidate concurrently; preserve input order throughout.

    Results come back in input order no matter how the pool schedules them, so
    the output array satisfies the same order-preservation rule as every other
    legoscout batch agent. Timing is measured here, at the boundary, because it
    is the only place the whole batch is in scope: `wall_seconds` is what the
    concurrent run cost, and `serial_equivalent_seconds` is the sum of the
    candidates' own prices -- roughly what the appraiser's old serial loop
    paid, before its per-call process-launch overhead. A run relays both so
    batch sizing stays a measurement instead of a guess.
    """
    batch_started = clock()
    started_times: dict[int, float] = {}

    class _TimedPool:
        """Wraps map() so each candidate's own price duration is recorded."""

        def __init__(self, pool: Any) -> None:
            self._pool = pool

        def map(self, fn: Callable[[Any], Any], entries: list[Any]) -> list[Any]:
            def timed(index_entry: tuple[int, Any]) -> Any:
                index, entry = index_entry
                began = clock()
                try:
                    return fn(entry)
                finally:
                    started_times[index] = clock() - began

            return list(self._pool.map(timed, list(enumerate(entries))))

    with executor_factory(workers) as pool:
        results = _TimedPool(pool).map(lambda entry: price_one(entry, limit),
                                       candidates)
    wall = round(clock() - batch_started, 6)

    durations = [started_times[i] for i in range(len(results)) if i in started_times]
    serial_equivalent = round(sum(durations), 6)
    speedup = round(serial_equivalent / wall, 2) if wall > 0 else None
    aggregate: dict[str, Any] = {
        "candidates": len(results),
        "blocked_count": sum(1 for r in results if r.get("blocked") is True),
        "workers": workers,
        "wall_seconds": wall,
        # The candidates' own price durations summed -- roughly what the
        # appraiser's old serial loop paid for the same lookups, before its
        # per-call process-launch overhead. Includes blocked results: their
        # failed lookups cost wall time too.
        "serial_equivalent_seconds": serial_equivalent,
        "speedup_vs_serial": speedup,
    }
    return {
        "mode": "batch",
        "timings": aggregate,
        "results": results,
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Price a whole appraiser batch of classified candidates in one "
                    "call: BrickLink + eBay sold comps per candidate, concurrent, "
                    "each result identical to `pricing comps` plus listing_key.")
    parser.add_argument("--input", required=True,
                        help="JSON array file of the classifier's comps hand-offs "
                             "(listing_key/listing_category/set_numbers/condition/"
                             "description or description/dollars_per_lb)")
    parser.add_argument("--output", required=True,
                        help="Write the full batch JSON here")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="Concurrent candidates (default %d). Keep narrow: "
                             "eBay is a browser-session scrape." % DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.workers < 1:
        print("--workers must be >= 1", file=sys.stderr)
        return 1
    if args.limit < 1:
        print("--limit must be >= 1", file=sys.stderr)
        return 1
    try:
        candidates = parse_handoff(args.input, "--input")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    report = run_batch(candidates, args.workers, args.limit)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "output": args.output,
        "candidates": report["timings"]["candidates"],
        "blocked": report["timings"]["blocked_count"],
        "wall_seconds": report["timings"]["wall_seconds"],
        "speedup_vs_serial": report["timings"]["speedup_vs_serial"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(None))
