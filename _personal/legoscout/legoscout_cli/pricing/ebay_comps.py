#!/usr/bin/env python3
"""eBay completed/sold-listing comps for one LEGO set or one bulk lot.

Mirrors `set_sales.py`'s subprocess + `json_cache` caching pattern, with one
deliberate difference: BrickLink failures RAISE (`set_sales.LookupFailed`) and a
caller that does not catch one gets a non-zero exit. eBay's completed/sold search
is a browser-session scrape (`ebay auth login --credential-type browser_session`),
not an API call, and an expired or never-authenticated session is the ordinary
case, not an exceptional one. So every public function here ALWAYS returns a
result dict with `"available": bool` -- it never raises past this module's
boundary. A caller combining this with a BrickLink lookup (`pricing comps`) must
not have the eBay half's auth lapse take the BrickLink half down with it.

Matching is deliberately narrow and fully deterministic, per the exact-token
matching rule in the `legoscout-comps` skill:
  - SET mode keeps only listings whose title contains the exact set number as a
    standalone token (`\\b75192\\b`), then drops obvious non-comp listings via a
    small denylist (parts lots, incomplete sets, box/manual-only listings).
  - BULK mode has no target set number to match against, so it extracts a
    stated weight from each title instead (`\\d+(\\.\\d+)?\\s*(lbs?|pounds?)`)
    and keeps only listings where one parsed -- an unweighted bulk listing has
    no comparable $/lb and would silently drag the average toward whatever
    random price/weight ratio a caller assumed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import json_cache  # noqa: E402
from .. import paths  # noqa: E402

EBAY_COMMAND = "ebay"
CACHE = paths.EBAY_COMP_CALL_CACHE

# eBay's own resolved category for "LEGO (R) Complete Sets & Packs"
# (`ebay categories list "lego"`, 2026-08-20). There is no equivalent bulk-lot
# category -- bulk lots scatter across this one, "Bricks, Pieces & Parts"
# (183448), and "Other Wholesale Toy Lots" (26424) -- so bulk search runs with
# no --category filter at all and relies on the weight regex instead.
SET_CATEGORY_ID = "19006"

# Sold comps are a rolling window, not a fixed catalog fact -- keep the TTL
# shorter than BrickLink's 7-day `catalog price` TTL, since an individual
# eBay search result set turns over faster than a guide average.
_TTL_DAYS = 3

_DENYLIST = [
    ("parts only", r"\bparts?\s*(only|lot)\b"),
    ("incomplete", r"\bincomplete\b"),
    ("no box", r"\bno\s+box\b"),
    ("instructions only", r"\binstructions?\s+only\b"),
    ("for parts", r"\bfor\s+parts\b"),
    ("missing pieces", r"\bmissing\s+pieces?\b"),
    ("manual only", r"\bmanual\s+only\b"),
    ("box only", r"\bbox\s+only\b"),
]
_DENYLIST_COMPILED = [(label, re.compile(pattern, re.I)) for label, pattern in _DENYLIST]

_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.I)

_BARE_SET_NO_RE = re.compile(r"^\s*(\d+)(?:-[1-9]\d*)?\s*$")


class LookupFailed(Exception):
    """An eBay call could not complete for a reason other than "not authenticated"."""


Runner = Callable[[list[str]], list]


def _shorten(text: str, limit: int = 1200) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "...[truncated]"


def _is_auth_failure(combined_output: str) -> bool:
    lowered = combined_output.lower()
    return "browser session" in lowered or "auth login" in lowered or "not authenticated" in lowered


def run_ebay_json(args: list[str]) -> list:
    """One `ebay` subprocess call, parsed as a JSON array.

    Raises `LookupFailed` for anything unexpected. An auth failure is NOT
    raised here -- callers check `_is_auth_failure` on the raw stderr this
    function attaches to the exception message, but the public `search_*`
    functions are what actually decide to degrade rather than propagate; see
    the module docstring.
    """
    resolved = shutil.which(EBAY_COMMAND)
    if resolved is None:
        raise LookupFailed(
            f"eBay CLI not on PATH: {EBAY_COMMAND!r}. "
            "Install it from ~/Dropbox/GitRepos/cli-tools/ebay.")

    result = subprocess.run([resolved, *args], text=True, capture_output=True, check=False)
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    if result.returncode != 0:
        raise LookupFailed(f"ebay {' '.join(args)} exited {result.returncode}: {_shorten(combined)}")

    try:
        import json
        parsed = json.loads(result.stdout)
    except Exception as exc:  # noqa: BLE001 -- reported with the raw stdout
        raise LookupFailed(
            f"ebay {' '.join(args)} returned non-JSON stdout: {_shorten(result.stdout)}") from exc

    if not isinstance(parsed, list):
        raise LookupFailed(f"ebay {' '.join(args)} returned {type(parsed).__name__}; expected an array")
    return parsed


def _fresh(entry: dict, now: datetime) -> bool:
    fetched = entry.get("fetched_at")
    if not fetched:
        return False
    return datetime.fromisoformat(fetched) + timedelta(days=_TTL_DAYS) > now


def cached_ebay_json(
    args: list[str],
    runner: Runner = run_ebay_json,
    cache_path: str = CACHE,
    now: datetime | None = None,
) -> list:
    now = now or datetime.now(timezone.utc)
    key = " ".join(args)
    entry = json_cache.read(cache_path).get(key)
    if entry is not None and _fresh(entry, now):
        return entry["result"]
    result = runner(args)
    json_cache.update(cache_path, {key: {"result": result, "fetched_at": now.isoformat()}})
    return result


def _parse_price(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.replace(",", "").replace("$", ""))
        except ValueError:
            return None
    return None


def _matched_terms(text: str, patterns) -> list[str]:
    return [label for label, rx in patterns if rx.search(text)]


def _bare_set_no(set_no: str) -> str:
    """The number as a seller writes it: `75192-1` -> `75192`, `75192` -> `75192`."""
    match = _BARE_SET_NO_RE.match(str(set_no))
    if not match:
        raise LookupFailed(
            "set_no must be digits, optionally with a BrickLink -N sequence "
            "suffix, got %r" % (set_no,))
    return match.group(1)


def _unavailable(query: str, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "query": query,
        "reason": reason,
        "matched_count": 0,
        "excluded_count": 0,
        "excluded_reasons": [],
        "avg_sold_price": None,
        "min_sold_price": None,
        "max_sold_price": None,
        "listings": [],
    }


def search_set_comps(
    set_no: str,
    condition: str,
    description: str | None = None,
    limit: int = 50,
    runner: Runner = cached_ebay_json,
) -> dict[str, Any]:
    """eBay sold comps for one LEGO set, matched by exact set-number token.

    `condition` is the same `N`/`U` vocabulary as `set_sales.summarize_set` --
    mapped here to eBay's `new`/`used`.
    """
    if condition not in ("N", "U"):
        raise LookupFailed("condition must be 'N' or 'U', got %r" % (condition,))
    bare = _bare_set_no(set_no)
    ebay_condition = "new" if condition == "N" else "used"
    query = "lego %s" % bare
    if description:
        query = "%s %s" % (query, description.strip())

    args = [
        "listings", "search", query,
        "--sold", "--us-only",
        "--condition", ebay_condition,
        "--category", SET_CATEGORY_ID,
        "--limit", str(limit),
    ]
    try:
        raw_listings = runner(args)
    except LookupFailed as exc:
        reason = "ebay_auth_required" if _is_auth_failure(str(exc)) else "ebay_lookup_failed: %s" % exc
        return _unavailable(query, reason)

    token_re = re.compile(r"\b%s\b" % re.escape(bare))
    matched: list[dict] = []
    excluded_reasons: list[str] = []
    for listing in raw_listings:
        if not isinstance(listing, dict):
            continue
        title = listing.get("title") or ""
        if not token_re.search(title):
            continue
        denylist_hits = _matched_terms(title, _DENYLIST_COMPILED)
        if denylist_hits:
            excluded_reasons.extend(denylist_hits)
            continue
        price = _parse_price(listing.get("price"))
        if price is None:
            excluded_reasons.append("no parseable price")
            continue
        matched.append({
            "item_id": listing.get("item_id"),
            "title": title,
            "price": price,
            "url": listing.get("url"),
        })

    prices = [row["price"] for row in matched]
    return {
        "available": True,
        "query": query,
        "category_id": SET_CATEGORY_ID,
        "condition": ebay_condition,
        "reason": None,
        "matched_count": len(matched),
        "excluded_count": len(raw_listings) - len(matched),
        "excluded_reasons": sorted(set(excluded_reasons)),
        "avg_sold_price": round(sum(prices) / len(prices), 2) if prices else None,
        "min_sold_price": min(prices) if prices else None,
        "max_sold_price": max(prices) if prices else None,
        "listings": matched,
    }


def search_minifigure_comps(
    description: str,
    limit: int = 50,
    runner: Runner = cached_ebay_json,
) -> dict[str, Any]:
    """eBay sold $/fig comps for one minifigure or a lot of minifigures.

    The bulk analogue: bulk extracts a stated weight from each title because
    $/lb is the only comparable unit, and minifigure lots do the same with a
    stated FIGURE COUNT -- a 50-fig lot priced against a 3-fig lot's listing
    price is fiction, exactly like an unweighted bulk listing. Titles that
    state no count are excluded from the $/fig average, not guessed at; a
    bare single-fig title (\"boba fett minifigure\") counts as one figure, and
    \"lot of N\" / \"N minifigs\" / \"N figs\" forms are parsed explicitly.

    No `--category`: like bulk lots, minifigure lots scatter across eBay's
    LEGO categories, so this searches on keywords alone.
    """
    query = "lego minifigure"
    if description:
        query = "%s %s" % (query, description.strip())

    args = [
        "listings", "search", query,
        "--sold", "--us-only",
        "--condition", "used",
        "--limit", str(limit),
    ]
    try:
        raw_listings = runner(args)
    except LookupFailed as exc:
        reason = "ebay_auth_required" if _is_auth_failure(str(exc)) else "ebay_lookup_failed: %s" % exc
        result = _unavailable(query, reason)
        result["avg_price_per_fig"] = None
        return result

    matched: list[dict] = []
    excluded_reasons: list[str] = []
    for listing in raw_listings:
        if not isinstance(listing, dict):
            continue
        title = listing.get("title") or ""
        denylist_hits = _matched_terms(title, _DENYLIST_COMPILED)
        if denylist_hits:
            excluded_reasons.extend(denylist_hits)
            continue
        price = _parse_price(listing.get("price"))
        if price is None:
            excluded_reasons.append("no parseable price")
            continue
        figure_count = _minifig_count(title)
        if figure_count is None:
            excluded_reasons.append("no parseable figure count")
            continue
        if figure_count <= 0:
            excluded_reasons.append("no parseable figure count")
            continue
        matched.append({
            "item_id": listing.get("item_id"),
            "title": title,
            "price": price,
            "figure_count": figure_count,
            "price_per_fig": round(price / figure_count, 4),
            "url": listing.get("url"),
        })

    per_fig_values = [row["price_per_fig"] for row in matched]
    avg_per_fig = round(sum(per_fig_values) / len(per_fig_values), 4) if per_fig_values else None

    return {
        "available": True,
        "query": query,
        "category_id": None,
        "condition": "used",
        "reason": None,
        "matched_count": len(matched),
        "excluded_count": len(raw_listings) - len(matched),
        "excluded_reasons": sorted(set(excluded_reasons)),
        "avg_sold_price": round(sum(row["price"] for row in matched) / len(matched), 2) if matched else None,
        "min_sold_price": min((row["price"] for row in matched), default=None),
        "max_sold_price": max((row["price"] for row in matched), default=None),
        "avg_price_per_fig": avg_per_fig,
        "listings": matched,
    }


def _minifig_count(title: str) -> int | None:
    """Figure count stated in an eBay minifig-lot title, or 1 for a bare
    single-figure title. `None` when the title states no count at all (\"lego
    minifigure lot\"), which is ambiguous between 2 and 200 -- that listing
    cannot price a $/fig average and is excluded, never assumed.

    Forms parsed, in order:
      \"lot of N\"                          -> N
      \"N x minifigure(s)\", \"Nx minifigs\"  -> N
      \"N minifigures/figs\"                  -> N
      bare single-fig title                  -> 1
    """
    text = title.lower()
    lot_match = re.search(r"\blot\s+of\s+(\d+)", text)
    if lot_match:
        return int(lot_match.group(1))
    times_match = re.search(r"(\d+)\s*x\s*(?:lego\s+)?mini\s?-?fig", text)
    if times_match:
        return int(times_match.group(1))
    n_match = re.search(r"(\d+)\s*(?:mini\s?-?figs?|mini\s?-?figures?|figs?)\b", text)
    if n_match:
        return int(n_match.group(1))
    if re.search(r"mini\s?-?fig", text) and not re.search(r"\blots?\b|\bsets?\b", text):
        return 1
    return None


def search_bulk_comps(
    description: str,
    dollars_per_lb: float | None = None,
    limit: int = 50,
    runner: Runner = cached_ebay_json,
) -> dict[str, Any]:
    """eBay sold $/lb comps for one bulk LEGO lot.

    No `--category`: eBay has no dedicated bulk-lot category, so this searches
    on keywords alone. Each matched listing's own $/lb is `price / weight`,
    from a weight this function extracts from the title -- a listing with no
    stated weight cannot be compared and is excluded, not guessed at.
    """
    query = "lego bulk lot"
    if description:
        query = "%s %s" % (query, description.strip())

    args = [
        "listings", "search", query,
        "--sold", "--us-only",
        "--condition", "used",
        "--limit", str(limit),
    ]
    try:
        raw_listings = runner(args)
    except LookupFailed as exc:
        reason = "ebay_auth_required" if _is_auth_failure(str(exc)) else "ebay_lookup_failed: %s" % exc
        result = _unavailable(query, reason)
        result["avg_price_per_lb"] = None
        result["target_vs_comp_delta_pct"] = None
        return result

    matched: list[dict] = []
    excluded_reasons: list[str] = []
    for listing in raw_listings:
        if not isinstance(listing, dict):
            continue
        title = listing.get("title") or ""
        denylist_hits = _matched_terms(title, _DENYLIST_COMPILED)
        if denylist_hits:
            excluded_reasons.extend(denylist_hits)
            continue
        price = _parse_price(listing.get("price"))
        if price is None:
            excluded_reasons.append("no parseable price")
            continue
        weight_match = _WEIGHT_RE.search(title)
        if not weight_match:
            excluded_reasons.append("no parseable weight")
            continue
        weight_lbs = float(weight_match.group(1))
        if weight_lbs <= 0:
            excluded_reasons.append("no parseable weight")
            continue
        matched.append({
            "item_id": listing.get("item_id"),
            "title": title,
            "price": price,
            "weight_lbs": weight_lbs,
            "price_per_lb": round(price / weight_lbs, 4),
            "url": listing.get("url"),
        })

    per_lb_values = [row["price_per_lb"] for row in matched]
    avg_per_lb = round(sum(per_lb_values) / len(per_lb_values), 4) if per_lb_values else None
    delta_pct = None
    if avg_per_lb is not None and dollars_per_lb is not None and avg_per_lb:
        delta_pct = round((dollars_per_lb - avg_per_lb) / avg_per_lb * 100, 2)

    return {
        "available": True,
        "query": query,
        "category_id": None,
        "condition": "used",
        "reason": None,
        "matched_count": len(matched),
        "excluded_count": len(raw_listings) - len(matched),
        "excluded_reasons": sorted(set(excluded_reasons)),
        "avg_sold_price": round(sum(row["price"] for row in matched) / len(matched), 2) if matched else None,
        "min_sold_price": min((row["price"] for row in matched), default=None),
        "max_sold_price": max((row["price"] for row in matched), default=None),
        "avg_price_per_lb": avg_per_lb,
        "target_vs_comp_delta_pct": delta_pct,
        "listings": matched,
    }


def parse_args(argv: list[str] | None):
    import argparse

    parser = argparse.ArgumentParser(
        description="eBay sold comps for one LEGO set, one bulk lot with --bulk, "
                    "or one minifigure lot with --minifigure.")
    parser.add_argument("set_no", nargs="?", default=None,
                        help="A LEGO set number. Required unless --bulk or --minifigure.")
    parser.add_argument("--bulk", action="store_true",
                        help="Bulk-lot mode: match by weight, not a set number.")
    parser.add_argument("--minifigure", action="store_true",
                        help="Minifigure-lot mode: match by figure count, not a set number.")
    parser.add_argument("--condition", choices=["N", "U"], default=None,
                        help="N or U. Required unless --bulk or --minifigure.")
    parser.add_argument("--description", default=None,
                        help="Extra search keywords -- set name/theme, bulk lot description, "
                             "or minifigure theme/name.")
    parser.add_argument("--dollars-per-lb", type=float, default=None,
                        help="Bulk mode only: the target listing's own $/lb, for comparison.")
    parser.add_argument("--limit", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import json

    args = parse_args(argv)
    if args.bulk:
        result = search_bulk_comps(args.description, dollars_per_lb=args.dollars_per_lb,
                                   limit=args.limit)
    elif args.minifigure:
        if not args.description:
            return "--description is required in --minifigure mode"
        result = search_minifigure_comps(args.description, limit=args.limit)
    else:
        if not args.set_no or not args.condition:
            return "set_no and --condition are required unless --bulk or --minifigure"
        result = search_set_comps(args.set_no, args.condition,
                                  description=args.description, limit=args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(None))
