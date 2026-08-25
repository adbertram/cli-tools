#!/usr/bin/env python3
"""Look up BrickLink sold-price summaries for one LEGO set."""

from __future__ import annotations

from .. import paths
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import json_cache  # noqa: E402  -- the one reader/writer of a JSON cache
from . import profit as profit_module  # noqa: E402

BRICKLINK_COMMAND = "bricklink"

CACHE = paths.BRICKLINK_CALL_CACHE

# Every BrickLink answer expires. The sibling .set_comp_cache.json does not
# record a fetch time at all, so it serves a six-month sold average from
# whenever it was first written, forever. That is a real defect and this cache
# does not copy it.
#
# The window is per call shape, because the two shapes age differently:
#   `catalog set`   -- name, year, weight. Fixed once a set is released.
#   `catalog price` -- a ROLLING six-month sold window. It moves every day.
# A 404 is the most stable answer of all: a set number that does not exist
# keeps not existing, and the range-scan in set-listing-analysis.md walks
# whole blocks of them.
_TTL_DAYS: dict[str, int] = {
    "catalog set": 30,
    "catalog price": 7,
}
_NOT_FOUND_TTL_DAYS = 30


class LookupErrorBase(Exception):
    pass


class LookupNotFound(LookupErrorBase):
    pass


class LookupFailed(LookupErrorBase):
    pass


Runner = Callable[[list[str]], dict[str, Any]]


def _shorten(text: str, limit: int = 1200) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "...[truncated]"


def run_bricklink_json(args: list[str]) -> dict[str, Any]:
    resolved = shutil.which(BRICKLINK_COMMAND)
    if resolved is None:
        raise LookupFailed(
            f"BrickLink CLI not on PATH: {BRICKLINK_COMMAND!r}. "
            "Install it from ~/Dropbox/GitRepos/cli-tools/bricklink."
        )

    result = subprocess.run(
        [resolved, *args],
        text=True,
        capture_output=True,
        check=False,
    )
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    if result.returncode != 0:
        if "RESOURCE_NOT_FOUND" in combined or "404" in combined:
            raise LookupNotFound(_shorten(combined))
        raise LookupFailed(
            f"bricklink {' '.join(args)} exited {result.returncode}: {_shorten(combined)}"
        )

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LookupFailed(
            f"bricklink {' '.join(args)} returned non-JSON stdout: {_shorten(result.stdout)}"
        ) from exc

    if not isinstance(parsed, dict):
        raise LookupFailed(
            f"bricklink {' '.join(args)} returned {type(parsed).__name__}; expected object"
        )
    return parsed


def _ttl_days(args: list[str]) -> int:
    shape = " ".join(args[:2])
    if shape not in _TTL_DAYS:
        raise LookupFailed(
            f"No cache lifetime is defined for the call shape {shape!r}. "
            f"Add it to _TTL_DAYS with a reason. Known shapes: "
            f"{', '.join(sorted(_TTL_DAYS))}. A new BrickLink call is not "
            "cached by guess -- how fast its answer goes stale is a decision."
        )
    return _TTL_DAYS[shape]


def _fresh(entry: dict[str, Any], ttl_days: int, now: datetime) -> bool:
    fetched = entry.get("fetched_at")
    if not fetched:
        # Written before this cache recorded times, or hand-edited. Refetch
        # rather than serve an answer of unknown age.
        return False
    return datetime.fromisoformat(fetched) + timedelta(days=ttl_days) > now


def cached_bricklink_json(
    args: list[str],
    runner: Runner = run_bricklink_json,
    cache_path: str = CACHE,
    now: datetime | None = None,
) -> dict[str, Any]:
    """`run_bricklink_json` with an expiring on-disk cache.

    Keyed on the full argument list, so the three calls `summarize_set` makes
    per set are cached separately and the block range-scan in
    set-listing-analysis.md reuses every `catalog set` it has already done.

    A LookupNotFound is cached: a set number that does not exist is a stable
    fact and re-asking costs a request against a 5,000/day quota. A
    LookupFailed is NOT cached -- a rate limit, a network error, or a missing
    CLI are all transient, and storing one would turn a blip into a lasting
    wrong answer.
    """
    now = now or datetime.now(timezone.utc)
    key = " ".join(args)
    ttl = _ttl_days(args)

    entry = json_cache.read(cache_path).get(key)
    if entry is not None:
        window = _NOT_FOUND_TTL_DAYS if entry.get("not_found") else ttl
        if _fresh(entry, window, now):
            if entry.get("not_found"):
                raise LookupNotFound(entry["message"])
            return entry["result"]

    stamp = now.isoformat()
    try:
        result = runner(args)
    except LookupNotFound as exc:
        json_cache.update(
            cache_path,
            {key: {"not_found": True, "message": str(exc), "fetched_at": stamp}},
        )
        raise
    json_cache.update(
        cache_path,
        {key: {"not_found": False, "result": result, "fetched_at": stamp}},
    )
    return result


def parse_number(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise LookupFailed(f"{field} must be numeric, got boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError as exc:
            raise LookupFailed(f"{field} must be numeric, got {value!r}") from exc
    raise LookupFailed(f"{field} must be numeric, got {type(value).__name__}")


def normalize_price_summary(condition: str, raw: dict[str, Any]) -> dict[str, Any]:
    price_detail = raw.get("price_detail")
    if price_detail is not None and not isinstance(price_detail, list):
        raise LookupFailed("price_detail must be an array when present")

    avg_price = parse_number(raw.get("avg_price"), f"{condition}.avg_price")
    return {
        "condition": condition,
        "guide_type": "sold",
        "sold_window": "bricklink_sold_guide_last_6_months",
        "six_month_avg_sold_price": avg_price,
        "avg_price": avg_price,
        "qty_avg_price": parse_number(raw.get("qty_avg_price"), f"{condition}.qty_avg_price"),
        "min_price": parse_number(raw.get("min_price"), f"{condition}.min_price"),
        "max_price": parse_number(raw.get("max_price"), f"{condition}.max_price"),
        "total_quantity": parse_number(raw.get("total_quantity"), f"{condition}.total_quantity"),
        "unit_quantity": parse_number(raw.get("unit_quantity"), f"{condition}.unit_quantity"),
        "currency_code": raw.get("currency_code"),
        "price_detail_count": len(price_detail) if price_detail is not None else None,
    }


_BARE_SET_NO_RE = re.compile(r"^\s*(\d+)\s*$")
_FULL_SET_NO_RE = re.compile(r"^\s*(\d+)-([1-9]\d*)\s*$")


def normalized_set_no(set_no: str) -> str:
    """BrickLink's item sequence number, which a bare set number is not.

    `bricklink catalog set 75192` and `bricklink catalog price SET 75192` both
    fail with `Bricklink API error 400: Invalid item sequence number: null`.
    Both need `75192-1`. Every appraiser on the 2026-08-06 run hit this and
    normalized by hand, so the caller does it once, here.
    """
    text = str(set_no)
    bare = _BARE_SET_NO_RE.fullmatch(text)
    if bare:
        return "%s-1" % bare.group(1)
    full = _FULL_SET_NO_RE.fullmatch(text)
    if full:
        return "%s-%s" % full.groups()
    raise LookupFailed(
        "set_no must be digits or a BrickLink item number with a positive "
        "sequence suffix, such as 75192 or 75192-1; got %r" % set_no)


def summarize_set(
    set_no: str,
    condition: str,
    purchase_price: float | None = None,
    fee_rate: float | None = None,
    runner: Runner = cached_bricklink_json,
) -> dict[str, Any]:
    """BrickLink catalog + used/new six-month sold summaries for one set.

    `purchase_price`/`fee_rate` are optional: a comps-only caller (no landed
    cost in hand) omits both and gets `potential_profit: None` with
    `selected_condition_priced` still reporting whether the comp itself is
    usable evidence. `condition` stays required and is never defaulted -- a
    `None` falling through to "not U" would silently price a USED lot at the
    NEW average, which is typically 2-4x too high.
    """
    if condition not in ("N", "U"):
        raise LookupFailed(
            "condition must be 'N' or 'U', got %r" % (condition,))
    if (purchase_price is None) != (fee_rate is None):
        raise LookupFailed(
            "purchase_price and fee_rate must be given together or omitted "
            "together -- got purchase_price=%r, fee_rate=%r. One without the "
            "other computes no profit but silently discards the one that was "
            "given." % (purchase_price, fee_rate))
    set_no = normalized_set_no(set_no)
    catalog = runner(["catalog", "set", set_no])
    used_raw = runner(["catalog", "price", "SET", set_no, "--condition", "U", "--sold"])
    new_raw = runner(["catalog", "price", "SET", set_no, "--condition", "N", "--sold"])

    used_summary = normalize_price_summary("U", used_raw)
    new_summary = normalize_price_summary("N", new_raw)
    selected = used_summary if condition == "U" else new_summary
    avg_price = selected["six_month_avg_sold_price"]
    price_detail_count = selected.get("price_detail_count")

    priced = profit_module.is_priced(avg_price, price_detail_count)
    potential_profit = None
    if priced and purchase_price is not None and fee_rate is not None:
        potential_profit = profit_module.net_profit(avg_price, purchase_price, fee_rate)

    return {
        "set_no": set_no,
        "lookup_status": "found",
        "catalog": catalog,
        "condition": condition,
        "purchase_price": purchase_price,
        "fee_rate": fee_rate,
        "used": used_summary,
        "new": new_summary,
        "selected_condition_summary": selected,
        "selected_condition_priced": priced,
        "potential_profit": potential_profit,
    }


def build_not_found_result(
    set_no: str,
    condition: str,
    purchase_price: float | None,
    fee_rate: float | None,
    message: str,
) -> dict[str, Any]:
    return {
        "set_no": set_no,
        "lookup_status": "not_found",
        "catalog": None,
        "condition": condition,
        "purchase_price": purchase_price,
        "fee_rate": fee_rate,
        "used": None,
        "new": None,
        "selected_condition_summary": None,
        "potential_profit": None,
        "error": {
            "source": "bricklink catalog lookup",
            "message": message,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Return BrickLink catalog metadata plus used/new six-month sold summaries for one set."
    )
    parser.add_argument("set_no", help="Normalized BrickLink set number, such as 75192-1.")
    parser.add_argument(
        "--purchase-price",
        type=float,
        default=None,
        help="Allocated purchase cost for this set. Omit for a comps-only lookup "
             "with no potential_profit -- pass it together with --fee-rate or not "
             "at all, never one without the other.",
    )
    parser.add_argument(
        "--condition",
        choices=["N", "U"],
        required=True,
        help="Inferred listing condition: N for sealed/new, U for used/opened.",
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=None,
        help="Active configured fee rate as a decimal, for example 0.13 for 13%%. "
             "Omit for a comps-only lookup with no potential_profit.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Call BrickLink directly, ignoring and not writing the call cache.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """`argv` defaults to the process argv, which is what `delegate.run` sets.

    Every other module behind a `legoscout` command defines `main()` with no
    required argument, and `delegate.run` calls `module.main()` with none. This
    one required `argv`, so `legoscout pricing set-sales` raised
    `main() missing 1 required positional argument: 'argv'` on every single
    invocation and no appraiser could reach the set-comp helper at all.
    """
    args = parse_args(argv)
    try:
        result = summarize_set(
            args.set_no,
            condition=args.condition,
            purchase_price=args.purchase_price,
            fee_rate=args.fee_rate,
            runner=run_bricklink_json if args.no_cache else cached_bricklink_json,
        )
    except LookupNotFound as exc:
        result = build_not_found_result(
            args.set_no,
            condition=args.condition,
            purchase_price=args.purchase_price,
            fee_rate=args.fee_rate,
            message=str(exc),
        )
    except LookupFailed as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
