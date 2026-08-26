#!/usr/bin/env python3
"""Filter, categorize and optionally detail a batch of raw eBay candidates.

    legoscout triage candidates.json
    legoscout triage candidates.json --min-price 25
    legoscout triage candidates.json --fetch-details --run-key 20260806T120000Z

This absorbs three ad-hoc root scripts that ran once each and left their state
in files beside them: `filter_items.py` (bad words, a price floor, a ledger
dedupe), `categorize.py` (bulk/set/other tagging) and `process_candidates.py`
(the per-listing detail fetch and the run artifact). The rules they hardcoded
ship as DATA in `triage_rules.json`; this module is the engine.

Three things the old trio got wrong are fixed here, because the crawl contract
they wrote against has since been enforced:

  * `listing_key` is `ebay|<item_id>`, with a pipe. `eBay_<id>` matched no
    reader, so every record it wrote was invisible to the ledger.
  * `available_fulfillment` is a normalized LIST through `ledger.fulfillment`,
    and an unreadable one RAISES. The old default of `"shipping"` is the exact
    bug `available_fulfillment` exists to prevent.
  * `price_basis` comes from the `validate.PRICE_BASES` vocabulary
    (`buy_now` / `current_price` / `static_price`). `current_bid` and `static`
    are not values; a row carrying one silently matches no price-basis rule.

The dead Antigravity log-parsing input path is NOT carried over. The input is a
JSON array of eBay candidate dicts.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent import futures
from datetime import datetime, timezone

from .. import paths
from ..ledger import db as ledger_db
from ..ledger import fulfillment
from ..ledger import shipping as shipping_estimate
from ..ledger import source_names
from ..ledger import validate as vdr
from . import listing

NAMESPACE = "ebay"
# The source CLI asks eBay to rate-limit us rather than the other way round.
DETAIL_DELAY_SECONDS = 8
# Concurrent `ebay listings get` calls. One is the old serial behaviour.
DEFAULT_JOBS = 4


@functools.lru_cache(maxsize=1)
def rules():
    """The filter and category rules, read once."""
    with open(paths.TRIAGE_RULES_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def is_plausible(item, min_price):
    """(kept, why). A dropped candidate always states which rule dropped it."""
    config = rules()
    title = str(item.get("title") or "").lower()
    exceptions = config["bad_word_exceptions"]
    for word in config["bad_words"]:
        if word not in title:
            continue
        if any(token in title for token in exceptions.get(word, [])):
            continue
        return False, "bad word %r in the title" % word
    price = item.get("price")
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False, "price %r is not a number" % (price,)
    if price < min_price:
        return False, "price %.2f is below the %.2f floor" % (price, min_price)
    return True, "kept"


def categorize(item):
    """`bulk` / `set` / `other`, first rule that matches."""
    config = rules()
    title = str(item.get("title") or "").lower()
    for category in config["categories"]:
        if any(re.search(pattern, title) for pattern in category["regexes"]):
            return category["name"]
        if any(keyword in title for keyword in category["keywords"]):
            return category["name"]
    return config["default_category"]


def listing_key(item):
    return "%s|%s" % (NAMESPACE, item["item_id"])


def known_keys(path=None):
    """Every eBay listing_key already in the ledger, through the access layer."""
    sql = "SELECT listing_key FROM deals WHERE listing_key LIKE ?"
    rows = (ledger_db.query(sql, ("%s|%%" % NAMESPACE,), path) if path
            else ledger_db.query(sql, ("%s|%%" % NAMESPACE,)))
    return {row["listing_key"] for row in rows}


def triage(candidates, min_price=None, path=None):
    """Filter, dedupe against the ledger, and tag. Returns a report dict."""
    if min_price is None:
        min_price = rules()["min_price_default"]
    seen = known_keys(path)
    kept, dropped = [], []
    for item in candidates:
        ok, why = is_plausible(item, min_price)
        if not ok:
            dropped.append({"item_id": item.get("item_id"), "why": why})
            continue
        key = listing_key(item)
        if key in seen:
            dropped.append({"item_id": item.get("item_id"),
                            "why": "%s is already in the ledger" % key})
            continue
        kept.append(dict(item, listing_key=key, category=categorize(item)))

    counts = {"bulk": 0, "set": 0, "minifigure": 0, "other": 0}
    for item in kept:
        counts[item["category"]] += 1
    return {"considered": len(candidates), "kept": len(kept),
            "dropped": len(dropped), "categories": counts,
            "min_price": min_price, "dropped_records": dropped,
            "candidates": kept}


# ---------------------------------------------------------------------------
# --fetch-details: one `ebay listings get` per kept candidate.
# ---------------------------------------------------------------------------

_BASIS_BY_FORMAT = (("Buy It Now", "buy_now"), ("Best Offer", "buy_now"),
                    ("Auction", "current_price"))

# eBay's own `format` strings, as `ebay listings search` and `ebay listings
# get` return them (checked live 2026-08-06: 'Auction', 'Buy It Now',
# 'Best Offer'). A listing that is both carries both tokens.
_TYPE_BY_FORMAT = (("Auction", "auction"), ("Buy It Now", "fixed"),
                   ("Best Offer", "fixed"))


def _price_basis(item):
    """One of `validate.PRICE_BASES`, never the retired `current_bid`/`static`.

    An unrecognised `format` RAISES. It used to return `static_price`, which is
    a fallback: a format eBay renamed would have priced every one of its
    listings off a field the payload never fills, and nothing would have said
    so.
    """
    listing_format = str(item.get("format") or "")
    for token, basis in _BASIS_BY_FORMAT:
        if token in listing_format:
            return basis
    raise ValueError(
        "%s: eBay format %r matches none of %s -- read the listing rather than "
        "pricing it off a guessed basis"
        % (listing_key(item), listing_format,
           "/".join(token for token, _ in _BASIS_BY_FORMAT)))


def _listing_type(item):
    """`auction` / `auction_with_buy_now` / `fixed`, from eBay's `format`.

    `listing_type` is the field the deals page raises on, so an illegal value
    takes the whole page down. `_record` used not to emit it at all, which left
    `build_deal_record` to write the schema default for every eBay row.
    """
    listing_format = str(item.get("format") or "")
    matched = [name for token, name in _TYPE_BY_FORMAT if token in listing_format]
    if not matched:
        raise ValueError(
            "%s: eBay format %r names no listing type" % (listing_key(item),
                                                          listing_format))
    if "auction" in matched and "fixed" in matched:
        return "auction_with_buy_now"
    return matched[0]


def _detail(item_id):
    """`ebay listings get <id>`, argv list, never a shell string."""
    proc = subprocess.run(["ebay", "listings", "get", item_id],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ebay listings get %s exited %d: %s"
                           % (item_id, proc.returncode, proc.stderr.strip()[:200]))
    return json.loads(proc.stdout)


def _number(value):
    """A float, or None. A price eBay did not publish is not a zero."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record(item, detail):
    """One crawl-contract candidate record. Raises rather than defaulting.

    Every crawl-phase column the eBay payload can answer is written here. This
    used to emit 13 of the 24 and leave the rest to `build_deal_record`'s
    schema defaults -- including `listing_type`, which is the field
    `display.rows` raises on, and `item_location`, which decides whether a lot
    is drivable. `ebay listings get` has exposed `item_location` since at least
    2026-08-06 ('Atlanta, Georgia, United States'), so there was never a reason
    to drop it.

    A column eBay does not publish is written as the SCHEMA's own sentinel --
    `unknown` for a string, `null` for a number -- never as a plausible value.
    """
    key = listing_key(item)
    basis = _price_basis(item)
    kind = _listing_type(item)
    is_auction = kind.startswith("auction")
    price = _number(item.get("price"))
    if price is None:
        raise ValueError("%s: price %r is not a number" % (key, item.get("price")))

    options = []
    if detail.get("local_pickup"):
        options.append(fulfillment.LOCAL_PICKUP)
    if detail.get("ships"):
        options.append(fulfillment.SHIPPING)
    if not options:
        raise ValueError(
            "%s: `ebay listings get` reports neither ships nor local_pickup. "
            "Read the listing rather than defaulting to shipping." % key)

    quoted = _number(item.get("shipping_price"))
    if quoted is None:
        quoted = _number(detail.get("shipping_price"))
    if quoted is None:
        # Absent BOTH when the listing is pickup-only and when eBay computes
        # the rate at checkout. `unquoted` records which, so a later reader
        # does not read the blank as free delivery -- see the module's
        # `NEEDS_PAGE_READ['shipping_estimate']` entry.
        estimate = shipping_estimate.unquoted(
            "`ebay listings get` published no shipping_price; eBay leaves it "
            "blank for a pickup-only listing and for a seller-calculated rate "
            "it computes at checkout")
    else:
        estimate = shipping_estimate.quoted(shipping_price=quoted)

    images = []
    if item.get("image_url"):
        images.append(item["image_url"])
    images.extend(detail.get("images") or [])

    location = detail.get("item_location") or item.get("item_location")
    ended = bool(detail.get("ended"))

    record = {
        "listing_key": key,
        # The NAMESPACE, not the display name. `source_names.check` rejects
        # 'eBay' outright: the display name is derived at render time and is
        # never stored.
        "source": NAMESPACE,
        "title": item["title"],
        "url": item["url"],
        "direct_url": item["url"],
        "posted_date": "unknown",
        "listing_type": kind,
        "price_basis": basis,
        "current_price": None,
        "buy_now_price": None,
        "static_price": None,
        "weight_lbs": None,
        "item_location": listing.tidy(str(location)) if location else "unknown",
        "origin_zip": None,
        "available_fulfillment": fulfillment.normalize(options),
        "shipping_estimate": estimate,
        "seller_name": item.get("seller") or detail.get("seller"),
        "seller_id": item.get("seller") or detail.get("seller"),
        "image_urls": sorted(set(images)),
        # eBay publishes `time_left` as a RELATIVE string ('Ended', '3d 5h')
        # and no absolute timestamp, so the dates stay `unknown` on an auction
        # and take the schema's non-auction value on a fixed listing.
        "auction_start_date": "unknown" if is_auction else "not-an-auction",
        "auction_end_date": "unknown" if is_auction else "not-an-auction",
        "bidding_open": (not ended) if is_auction else None,
        "winning_bid": _number(detail.get("current_bid")) if (
            is_auction and ended) else None,
    }
    if basis not in vdr.PRICE_BASES:
        raise ValueError("%s: price_basis %r is not one of %s"
                         % (key, basis, "/".join(vdr.PRICE_BASES)))
    record["buy_now_price" if basis == "buy_now" else
           "current_price" if basis == "current_price" else
           "static_price"] = price
    return record


def artifact_path(run_key=None, out_dir=None):
    """Where the run artifact goes. The name comes from the REGISTRY.

    It was the literal `eBay.json`. The orchestrator looks the artifact up by
    the source's registered display name, so a rename in the registry silently
    orphaned the file this module wrote.
    """
    stamp = run_key or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = out_dir or os.path.join(paths.SOURCE_RUNS, stamp)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "%s.json" % source_names.DISPLAY[NAMESPACE])


def _artifact(records, failures, kept_count, done_count):
    """The run artifact, at whatever completeness the fetch has reached."""
    complete = done_count == kept_count and not failures
    blocker = None
    if failures:
        blocker = "%d of %d kept candidates failed detail fetch" % (
            len(failures), kept_count)
    elif done_count != kept_count:
        blocker = "detail fetch stopped after %d of %d kept candidates" % (
            done_count, kept_count)
    return {
        "source": source_names.DISPLAY[NAMESPACE],
        "checked": complete,
        "blocked": not complete,
        "blocker": blocker,
        "candidate_records": records,
        "unavailable_updates": [],
        "unchanged_duplicate_keys": [],
        "learning_notes": "legoscout triage --fetch-details: filtered, "
                          "deduped and detailed through `ebay listings get`.",
        "actions_requiring_approval": [],
        "evidence_summary": "%d of %d kept candidates returned a detail "
                            "payload; %d could not be read; %d of %d attempted."
                            % (len(records), kept_count, len(failures),
                               done_count, kept_count),
        "completed_at": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"),
    }


def fetch_details(kept, run_key=None, out_dir=None, jobs=DEFAULT_JOBS):
    """Build the run artifact every source worker writes.

    Two changes from the serial version, both measured on the 2026-08-06 run:

      * `jobs` concurrent `ebay listings get` calls. 34 items at one call every
        8 seconds took about 20 minutes.
      * the artifact is written after EVERY completed listing, not once at the
        end. A kill at item 33 of 34 used to discard all 32 finished calls.

    The delay is per WORKER, so `--jobs 4` still paces each thread at
    `DETAIL_DELAY_SECONDS`; the rate limit eBay applies is what that protects.
    """
    artifact = artifact_path(run_key, out_dir)
    records, failures = [], []
    lock = threading.Lock()
    done = 0

    def one(index_item):
        index, item = index_item
        # Stagger the openers so `jobs` threads do not all call at t=0, then
        # pace each thread at the same per-call delay the serial loop used.
        if index >= jobs:
            time.sleep(DETAIL_DELAY_SECONDS)
        item_id = item["item_id"]
        try:
            return item_id, _record(item, _detail(item_id)), None
        except Exception as exc:  # noqa: BLE001 -- one listing, reported not guessed
            return item_id, None, "%s: %s" % (type(exc).__name__, str(exc)[:200])

    with futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for item_id, record, why in pool.map(one, enumerate(kept)):
            with lock:
                done += 1
                if record is None:
                    failures.append({"item_id": item_id, "why": why})
                else:
                    records.append(record)
                print("[%d/%d] %s %s" % (done, len(kept), item_id,
                                         "ok" if record else why or ""),
                      file=sys.stderr, flush=True)
                with open(artifact, "w", encoding="utf-8") as fh:
                    json.dump(_artifact(records, failures, len(kept), done),
                              fh, indent=2)

    result = _artifact(records, failures, len(kept), done)
    with open(artifact, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    return artifact, result, failures


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidates",
                    help="PATH to a JSON file holding an array of eBay "
                         "candidate dicts")
    ap.add_argument("--min-price", type=float,
                    help="price floor; the rules file states the default")
    ap.add_argument("--fetch-details", action="store_true",
                    help="run `ebay listings get` per kept candidate and write "
                         "the run artifact (live eBay calls)")
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help="concurrent `ebay listings get` calls (default %d); "
                         "each worker still waits %d seconds between its own "
                         "calls" % (DEFAULT_JOBS, DETAIL_DELAY_SECONDS))
    ap.add_argument("--run-key", help="the source-runs directory name to write into")
    ap.add_argument("--out", help="write the artifact under this directory instead")
    a = ap.parse_args()

    with open(a.candidates, encoding="utf-8") as fh:
        candidates = json.load(fh)
    report = triage(candidates, a.min_price)

    failures = []
    if a.fetch_details:
        artifact, _, failures = fetch_details(report["candidates"], a.run_key,
                                              a.out, jobs=a.jobs)
        report["artifact"] = artifact
        report["detail_failures"] = failures
    print(json.dumps(report, indent=1, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
