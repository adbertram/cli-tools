#!/usr/bin/env python3
"""Fixture-replay driver: `legoscout deals replay`.

Replays real Phase-4-relevant source-run fixtures through
`legoscout_cli.ledger.build_record` and `legoscout_cli.ledger.validate`, the two
modules that glue a `legoscout-source-worker` crawl candidate and a
`legoscout-appraiser` appraisal result into one ledger-ready record. Prints one
`CASE ok`/`CASE FAIL` line per case and exits 1 if any case failed.
"""
from .. import paths
import json
import os
import sys

from ..ledger import build_record as bdr  # noqa: E402
from ..pricing import pickup_area  # noqa: E402
from ..ledger import shipping as shipping_estimate  # noqa: E402
from ..ledger import validate as vdr  # noqa: E402

FIXTURES = paths.SOURCE_RUNS
FIRST_SEEN = "2026-08-04T12:00:00+00:00"
LAST_SEEN = "2026-08-04T12:00:00+00:00"

# Every fixture file a replay case loads, keyed off `paths.SOURCE_RUNS`. These
# live under `agent_workspaces/source-runs/<timestamp>/`, which AGENTS.md marks
# "Per-run source worker artifacts. Disposable." -- so the directory they came
# from can legitimately be gone. Replay must never fabricate them; when they are
# absent it reports exactly which run to restore instead of raising an opaque
# `[Errno 2] No such file or directory` mid-case.
REQUIRED_FIXTURES = (
    "2026-08-03T15-23-22/ShopGoodwill.json",
    "2026-08-03T15-23-22/eBay.json",
    "20260802T143701Z/proxibid.json",
)

FAILURES = []


def missing_fixtures():
    """Return the required fixture paths that are absent on disk.

    `paths.SOURCE_RUNS` points at `agent_workspaces/source-runs/`, the
    disposable per-run source-worker artifact tree. The replay cases replay real
    crawl output from specific historical runs; when a run's directory has been
    cleaned up, replay cannot run at all. Callers use this to either restore the
    run or report a loud, reasoned skip -- never to silently load nothing.
    """
    return [rel for rel in REQUIRED_FIXTURES
            if not os.path.isfile(os.path.join(FIXTURES, rel))]


def fail(case, detail):
    FAILURES.append((case, detail))
    print("%s FAIL: %s" % (case, detail))


def ok(case, detail):
    print("%s ok: %s" % (case, detail))


def load(rel):
    with open(os.path.join(FIXTURES, rel), encoding="utf-8") as f:
        return json.load(f)


def resolve_pickup_miles(location):
    try:
        return pickup_area.resolve(location)["miles"]
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# replay_crawl_through_build_deal_record
#
# All 53 ShopGoodwill.json candidates (real crawl-worker output, crawl-phase
# shape only) get a synthetic-but-consistent appraisal built around their own
# real fields, run through build_deal_record(), and every assembled record
# must pass validate_deal_records.check() with zero errors.
# ---------------------------------------------------------------------------
def case_crawl_through_build_deal_record():
    case = "replay_crawl_through_build_deal_record"
    fixture = load("2026-08-03T15-23-22/ShopGoodwill.json")
    source = fixture["source"]
    records = fixture["candidate_records"]
    if len(records) != 53:
        fail(case, "expected 53 ShopGoodwill.json candidate_records, found %d -- "
                    "the fixture on disk changed" % len(records))
        return

    error_count = 0
    for candidate in records:
        candidate = dict(candidate)
        candidate["source"] = source
        weight = candidate.get("weight_lbs")
        price = candidate.get("buy_now_price")
        shipping_total = shipping_estimate.total_of(candidate)
        landed = price + shipping_total if isinstance(shipping_total, (int, float)) else price

        appraisal = {
            "listing_category": "bulk",
            "estimated_total": landed,
            "handling_fee": 0.0,
            "per_lb_price": round(landed / weight, 2) if weight else None,
            "per_lb_price_basis": "landed" if weight else "unknown",
            "confidence": "medium",
            "shipping_estimated": False,
            "pickup_miles": resolve_pickup_miles(candidate.get("item_location")),
            "fee_breakdown": {
                "hammer": price, "premium_pct": 0.0, "premium_amount": 0.0,
                "sales_tax_pct": 0.0, "sales_tax_amount": 0.0,
                "shipping_handling": shipping_total,
                "shipping_estimated": False, "shipping_unknown": shipping_total is None,
                "landed_is_floor": False, "landed_total": landed,
            },
            "observations": {
                "description": "",
                "vision": {
                    "status": "no_images", "image_count": None, "target_colors": "unknown",
                    "color_families": [], "themes": [], "minifigs": "not_visible",
                    "contamination": [], "retired_sets_visible": None,
                    "weight_estimate_lbs": None, "weight_confidence": None,
                    "notes": "replay fixture carries no image_urls",
                },
                "model_score": 50,
                "model_rationale": "The replay fixture has neutral deal evidence.",
            },
        }
        record = bdr.build_deal_record(
            candidate, appraisal, first_seen_at=FIRST_SEEN, last_seen_at=LAST_SEEN)
        _, errors, _ = vdr.check(record)
        if errors:
            error_count += 1
            print("  %s: %s" % (record.get("listing_key"), errors))

    if error_count:
        fail(case, "%d of 53 assembled records failed validate_deal_records.check()"
                    % error_count)
    else:
        ok(case, "all 53 ShopGoodwill.json records assembled and passed check() "
                 "with zero errors")


# ---------------------------------------------------------------------------
# replay_ebay_image_urls_survive
#
# eBay.json's candidates carry real crawl-captured image_urls in a legacy
# shape (available_fulfillment as a bare string, not the crawl-contract
# list). Build a crawl candidate that honors the CURRENT contract around
# those same real image_urls, and prove they survive assembly unchanged.
# ---------------------------------------------------------------------------
def case_ebay_image_urls_survive():
    case = "replay_ebay_image_urls_survive"
    fixture = load("2026-08-03T15-23-22/eBay.json")
    records = [r for r in fixture["candidate_records"] if r.get("image_urls")]
    if not records:
        fail(case, "no eBay.json candidate carries image_urls -- the fixture changed")
        return

    survived = 0
    for raw in records:
        image_urls = list(raw["image_urls"])
        # The fixture predates the pipe-delimited listing_key convention
        # (`namespace|item_id`) -- it stores "eBay_<item_id>". Rebuild a
        # contract-compliant key around the same real item id so
        # source_names.check() resolves the namespace, rather than replaying
        # the fixture's own drifted key verbatim.
        item_id = raw["listing_key"].split("_", 1)[-1]
        candidate = {
            "listing_key": "ebay|%s" % item_id,
            "source": "eBay",
            "title": raw["title"],
            "url": raw["url"],
            "direct_url": raw["url"],
            "buy_now_price": raw["buy_now_price"],
            "current_price": None,
            "static_price": None,
            "price_basis": raw["price_basis"],
            "listing_type": "fixed",
            "auction_start_date": "not-an-auction",
            "auction_end_date": "not-an-auction",
            "posted_date": "unknown",
            "weight_lbs": 5.0,
            "item_location": "unknown",
            "available_fulfillment": ["shipping"],
            "image_urls": image_urls,
            "shipping_estimate": (
                shipping_estimate.quoted(shipping_price=raw["shipping_cost"],
                                         handling_price=0.0, service="fixture")
                if raw.get("shipping_cost") is not None else None),
        }
        appraisal = {
            "listing_category": "bulk",
            "estimated_total": raw["buy_now_price"] + (raw.get("shipping_cost") or 0.0),
            "per_lb_price": None,
            "per_lb_price_basis": "unknown",
            "confidence": "low",
            "pickup_miles": None,
            "fee_breakdown": {
                "hammer": raw["buy_now_price"], "premium_pct": 0.0, "premium_amount": 0.0,
                "sales_tax_pct": 0.0, "sales_tax_amount": 0.0,
                "shipping_handling": raw.get("shipping_cost"),
                "shipping_estimated": False, "shipping_unknown": False,
                "landed_is_floor": False,
                "landed_total": raw["buy_now_price"] + (raw.get("shipping_cost") or 0.0),
            },
            "observations": {
                "description": "",
                "vision": {
                    "status": "checked", "image_count": len(image_urls),
                    "target_colors": "unknown", "color_families": [], "themes": [],
                    "minifigs": "not_visible", "contamination": [],
                    "retired_sets_visible": None, "weight_estimate_lbs": None,
                    "weight_confidence": None, "notes": "replay of real eBay image_urls",
                },
                "model_score": 50,
                "model_rationale": "The replay fixture has neutral deal evidence.",
            },
        }
        record = bdr.build_deal_record(
            candidate, appraisal, first_seen_at=FIRST_SEEN, last_seen_at=LAST_SEEN)
        if record.get("image_urls") != image_urls:
            fail(case, "%s: image_urls did not survive assembly -- got %r, "
                        "expected the real captured %r"
                        % (raw["listing_key"], record.get("image_urls"), image_urls))
            continue
        _, errors, _ = vdr.check(record)
        if errors:
            fail(case, "%s: image_urls survived but check() reported errors: %s"
                        % (raw["listing_key"], errors))
            continue
        survived += 1

    if survived == len(records):
        ok(case, "all %d real eBay image_urls arrays survived build_deal_record "
                 "unchanged and passed check()" % survived)


# ---------------------------------------------------------------------------
# blocked_source_contributes_zero_not_empty_success
#
# proxibid.json (2026-08-02 run) is a real blocked:true artifact -- current
# on-disk 2026-08-03T15-23-22/Facebook.json actually carries `blocked: false`
# (a plain zero-candidate success, not a block), so proxibid.json is used
# here instead; see the session report for that judgment call.
# ---------------------------------------------------------------------------
def case_blocked_source_contributes_zero():
    case = "blocked_source_contributes_zero_not_empty_success"
    fixture = load("20260802T143701Z/proxibid.json")

    required_keys = (
        "source", "checked", "blocked", "blocker", "candidate_records",
        "unavailable_updates", "unchanged_duplicate_keys", "learning_notes",
        "actions_requiring_approval", "evidence_summary", "completed_at",
    )
    missing = [k for k in required_keys if k not in fixture]
    if missing:
        fail(case, "proxibid.json is missing required top-level keys: %s" % missing)
        return
    if fixture["blocked"] is not True:
        fail(case, "proxibid.json blocked is %r, expected True" % fixture["blocked"])
        return
    if fixture["checked"] is not True:
        fail(case, "a blocked source is still 'checked' -- it was reached and "
                    "positively identified as blocked, got checked=%r" % fixture["checked"])
        return
    if fixture["candidate_records"] != []:
        fail(case, "blocked source should contribute zero candidates, got %d"
                    % len(fixture["candidate_records"]))
        return
    if not isinstance(fixture["blocker"], str) or not fixture["blocker"].strip():
        fail(case, "blocker evidence string is empty -- a block with no evidence "
                    "is indistinguishable from a worker that produced nothing")
        return
    ok(case, "proxibid.json is checked=True, blocked=True, candidate_records=[], "
             "with a non-empty blocker evidence string -- zero candidates as a "
             "reported, evidenced success, not a missing/empty artifact")


# ---------------------------------------------------------------------------
# no_images_is_a_valid_terminal_state
#
# A seller who posts no photos is a real listing. `vision.status: "no_images"`
# with `image_urls: []` must pass validate_deal_records.check() cleanly --
# there is deliberately NO "never no_images" assertion here.
# ---------------------------------------------------------------------------
def case_no_images_is_valid():
    case = "no_images_is_a_valid_terminal_state"
    fixture = load("2026-08-03T15-23-22/ShopGoodwill.json")
    source = fixture["source"]
    candidate = dict(fixture["candidate_records"][0])
    candidate["source"] = source
    if "image_urls" in candidate:
        fail(case, "test fixture assumption broken: ShopGoodwill.json candidate "
                    "already carries image_urls")
        return

    appraisal = {
        "listing_category": "bulk",
        "estimated_total": candidate["buy_now_price"],
        "per_lb_price": None,
        "per_lb_price_basis": "unknown",
        "confidence": "low",
        "pickup_miles": resolve_pickup_miles(candidate.get("item_location")),
        "fee_breakdown": {
            "hammer": candidate["buy_now_price"], "premium_pct": 0.0, "premium_amount": 0.0,
            "sales_tax_pct": 0.0, "sales_tax_amount": 0.0,
            "shipping_handling": shipping_estimate.total_of(candidate),
            "shipping_estimated": False, "shipping_unknown": False,
            "landed_is_floor": False, "landed_total": candidate["buy_now_price"],
        },
        "observations": {
            "description": "",
            "vision": {
                "status": "no_images", "image_count": None, "target_colors": "unknown",
                "color_families": [], "themes": [], "minifigs": "not_visible",
                "contamination": [], "retired_sets_visible": None,
                "weight_estimate_lbs": None, "weight_confidence": None,
                "notes": "seller posted no photos",
            },
            "model_score": 50,
            "model_rationale": "The replay fixture has neutral deal evidence.",
        },
    }
    record = bdr.build_deal_record(
        candidate, appraisal, first_seen_at=FIRST_SEEN, last_seen_at=LAST_SEEN)
    if record.get("image_urls") != []:
        fail(case, "expected image_urls == [] on a record with no captured "
                    "images, got %r" % record.get("image_urls"))
        return
    if (record.get("observations") or {}).get("vision", {}).get("status") != "no_images":
        fail(case, "vision.status did not survive assembly as 'no_images'")
        return
    _, errors, _ = vdr.check(record)
    if errors:
        fail(case, "no_images with empty image_urls should pass check() cleanly, "
                    "got errors: %s" % errors)
        return
    ok(case, "image_urls=[] with vision.status='no_images' assembled cleanly and "
             "passed check() with zero errors -- a legitimate terminal state, "
             "not a failure")


def main():
    """Run every case. Module-level runs would fire on import."""
    FAILURES.clear()
    missing = missing_fixtures()
    if missing:
        print("replay fixtures missing at %s:" % FIXTURES)
        for rel in missing:
            print("  %s" % rel)
        print("agent_workspaces/source-runs/<timestamp>/ is disposable per-run "
              "source-worker output, and the run these fixtures replay has been "
              "deleted. Restore that run's fixtures -- from Dropbox version "
              "history, an adam-server release that still carries them, or a "
              "fresh crawl -- before replaying. Replay refuses to fabricate "
              "fixtures.")
        return 1

    case_crawl_through_build_deal_record()
    case_ebay_image_urls_survive()
    case_blocked_source_contributes_zero()
    case_no_images_is_valid()

    if FAILURES:
        print("\n%d CASE(S) FAILED" % len(FAILURES))
        return 1
    print("\nall 4 replay cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
