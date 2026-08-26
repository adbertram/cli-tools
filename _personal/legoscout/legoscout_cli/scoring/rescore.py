#!/usr/bin/env python3
"""Rescore ledger records with the deterministic scorer.

Scoring is pure: given the same record and the same observations it always
returns the same number, so this can be re-run at any time without a single
model call. Vision observations are whatever is already on the record -- this
does not fetch images, and a record that was never image-checked is scored
without a colour or visible-theme signal rather than being guessed at.

Defaults to the live rows only. `rejected` rows were disqualified or judged by
the old scorer and are deliberately left frozen; pass --include-rejected to
override that.

Run with --dry-run first.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter


from ..ledger import db as ledger_db  # noqa: E402
from . import score as score_deal  # noqa: E402
from ..ledger import sellers as sellers_db  # noqa: E402

# Rows worth a current number: live listings and anything Adam has acted on.
LIVE_STATUSES = {"active", "inquired", "bid_placed", "purchased"}

# A dead listing's score is history, not a recommendation.
FROZEN_STATUSES = {"rejected", "unavailable", "blocked"}


def _scored_or_failed(record, is_favorite_seller, failures):
    """Score one record, or record WHY that one record could not be scored.

    The blast radius of a corrupt record is that record. One row holding an
    infinite `estimated_total` used to abort the whole run on a bare
    `AssertionError` naming no listing, so a 2000-row ledger got zero new
    scores and no way to find the culprit.

    This is isolation, not suppression: the failed record is NOT written, NOT
    counted as scored, keeps whatever score it already had, and is reported by
    listing_key both on stderr and in the summary's `failed` list.
    """
    try:
        return score_deal.score_record(record, is_favorite_seller=is_favorite_seller)
    except Exception as exc:
        failure = {"listing_key": record.get("listing_key"),
                   "error": "%s: %s" % (type(exc).__name__, exc)}
        failures.append(failure)
        print("rescore FAILED for %s -- %s" % (failure["listing_key"], failure["error"]),
              file=sys.stderr)
        return None


def rescore(
    apply: bool,
    include_rejected: bool,
    limit: int | None,
    path: str = ledger_db.DB_PATH,
) -> dict:
    doc = ledger_db.load_document(path)
    # One query for every favorited seller, rather than one per record -- see
    # sellers_db.favorite_set(). This is what keeps a routine full-ledger
    # rescore honest about current favorite status even for a seller nobody
    # just toggled.
    favorites = sellers_db.favorite_set(path=path)
    stats = Counter()
    moves: list[dict] = []
    failures: list[dict] = []
    written: list[dict] = []

    for record in doc["deals"]:
        status = record.get("status")
        if status not in LIVE_STATUSES:
            if not (include_rejected and status in FROZEN_STATUSES):
                stats[f"skipped_{status}"] += 1
                continue

        if record.get("listing_category") not in ("bulk", "set", "minifigure"):
            stats["skipped_uncategorised"] += 1
            continue

        is_favorite_seller = (record.get("source"), record.get("seller_id")) in favorites
        result = _scored_or_failed(record, is_favorite_seller, failures)
        if result is None:
            stats["failed"] += 1
            continue
        scoring = result["scoring"]
        before = record.get("score")

        record["observations"] = result["observations"]
        record["scoring"] = scoring
        record["score"] = scoring["score"]
        record["last_score"] = scoring["score"]
        record["quality_score"] = scoring.get("quality")
        record["max_price"] = scoring.get("max_price")
        record["model_score"] = scoring.get("model_score")
        written.append(record)

        if scoring["score"] is None:
            stats["unscorable"] += 1
            stats[f"unscorable_{record['listing_category']}"] += 1
        else:
            stats["scored"] += 1
            stats[f"scored_{record['listing_category']}"] += 1

        moves.append(
            {
                "listing_key": record.get("listing_key"),
                "category": record.get("listing_category"),
                "title": (record.get("title") or "")[:60],
                "before": before,
                "after": scoring["score"],
                "quality": scoring.get("quality"),
                "max_price": scoring.get("max_price"),
                "price": scoring.get("price_scored"),
                "reason": scoring.get("unscorable"),
            }
        )

    if apply and written:
        # The records this run actually SCORED, not the whole document.
        # `save()` re-validates every deal it is handed, so one already-stored
        # corrupt record made the write refuse the entire ledger and the 2000
        # good scores went nowhere -- the same blast radius the per-record guard
        # above exists to remove, moved down one layer. `upsert_deals()`
        # validates and touches only these keys, and is what ledger/db.py names
        # as the correct call for a partial update.
        ledger_db.upsert_deals(written, path=path)

    moves.sort(key=lambda m: (m["after"] is None, -(m["after"] or 0)))
    return {
        "applied": apply,
        "stats": dict(stats),
        # Never truncated by --limit. A failure list that a report cap can hide
        # is a failure list nobody reads.
        "failed": failures,
        "rows": moves[:limit] if limit else moves,
    }


def rescore_seller(
    source: str,
    seller_id: str,
    apply: bool = True,
    path: str = ledger_db.DB_PATH,
) -> dict:
    """Rescore one seller's deals immediately after a favorite toggle.

    Scoped to LIVE_STATUSES, same as `rescore()` -- a rejected/unavailable/
    blocked deal's score is history, not a recommendation, so a favorite
    toggle must not resurrect one. This is what `serve_deals.py`'s POST
    /favorite calls: a full-ledger rescore is correct too, but scoping it to
    the one seller that just changed is what makes the star feel instant.
    """
    doc = ledger_db.load_document(path)
    is_favorite_seller = sellers_db.is_favorite(source, seller_id, path=path)
    stats = Counter()
    moves: list[dict] = []
    failures: list[dict] = []
    written: list[dict] = []

    for record in doc["deals"]:
        if record.get("source") != source or record.get("seller_id") != seller_id:
            continue
        if record.get("status") not in LIVE_STATUSES:
            stats[f"skipped_{record.get('status')}"] += 1
            continue
        if record.get("listing_category") not in ("bulk", "set", "minifigure"):
            stats["skipped_uncategorised"] += 1
            continue

        result = _scored_or_failed(record, is_favorite_seller, failures)
        if result is None:
            stats["failed"] += 1
            continue
        scoring = result["scoring"]
        before = record.get("score")

        record["observations"] = result["observations"]
        record["scoring"] = scoring
        record["score"] = scoring["score"]
        record["last_score"] = scoring["score"]
        record["quality_score"] = scoring.get("quality")
        record["max_price"] = scoring.get("max_price")
        record["model_score"] = scoring.get("model_score")
        written.append(record)

        stats["scored" if scoring["score"] is not None else "unscorable"] += 1
        moves.append({
            "listing_key": record.get("listing_key"),
            "before": before,
            "after": scoring["score"],
        })

    if apply and written:
        # Only this seller's rescored rows -- see the note in `rescore()`. A
        # favorite toggle must not be refused by an unrelated corrupt record
        # somewhere else in the ledger.
        ledger_db.upsert_deals(written, path=path)

    return {
        "applied": apply,
        "is_favorite_seller": is_favorite_seller,
        "stats": dict(stats),
        "failed": failures,
        "rows": moves,
    }


def main() -> int:
    """The argparse surface, lifted out of the `__main__` guard so the CLI
    can reach it. A guarded block never runs on import, so the ported module
    had no entry point at all."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the new scores")
    parser.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument(
        "--include-rejected",
        action="store_true",
        help="also rescore rejected/unavailable/blocked rows",
    )
    parser.add_argument("--limit", type=int, help="cap the rows listed in the report")
    # `rescore()` has always taken a path; only the CLI withheld it. Without
    # this option the closest thing LegoScout has to a scoring regression check
    # could only be aimed at the live ledger, so "dry-run it against a copy"
    # was not a runnable instruction.
    parser.add_argument("--ledger", default=ledger_db.DB_PATH,
                        help="score against this ledger instead of the live one")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run are mutually exclusive")
    summary = rescore(
        apply=args.apply,
        include_rejected=args.include_rejected,
        limit=args.limit,
        path=args.ledger,
    )
    # allow_nan=False: `NaN` and `Infinity` are Python-only JSON tokens that no
    # other parser reads. A summary a caller cannot parse is not a summary.
    print(json.dumps(summary, indent=2, allow_nan=False))
    # A run that could not score a record did not fully succeed, and a shell
    # that only reads the exit status must be told so.
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
