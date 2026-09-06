"""Replays real Phase-4 source-run fixtures through `build_deal_record`/`validate.check`.

These fixtures live under `agent_workspaces/source-runs/<timestamp>/`, which
AGENTS.md marks "Per-run source worker artifacts. Disposable." When a fixture's
run directory has been cleaned up, the affected test is skipped with the exact
restore instructions rather than failing or fabricating data -- restore the run
(Dropbox version history, an adam-server release, or a fresh crawl) and it runs
again automatically. This module replaces `legoscout_cli/orchestrator/replay_fixtures.py`
and the `legoscout deals replay` leaf: the four cases below are the same
assertions, run directly as pytest tests instead of a print-and-exit-code driver.
"""
from __future__ import annotations

import json
import os

import pytest

from legoscout_cli import paths
from legoscout_cli.ledger import build_record as bdr
from legoscout_cli.ledger import shipping as shipping_estimate
from legoscout_cli.ledger import validate as vdr
from legoscout_cli.pricing import pickup_area

FIXTURES = paths.SOURCE_RUNS
FIRST_SEEN = "2026-08-04T12:00:00+00:00"
LAST_SEEN = "2026-08-04T12:00:00+00:00"

SHOPGOODWILL_FIXTURE = "2026-08-03T15-23-22/ShopGoodwill.json"
EBAY_FIXTURE = "2026-08-03T15-23-22/eBay.json"
PROXIBID_FIXTURE = "20260802T143701Z/proxibid.json"


def _require_fixture(rel):
    path = os.path.join(FIXTURES, rel)
    if not os.path.isfile(path):
        pytest.skip(
            "replay fixture missing at %s -- the disposable per-run "
            "source-worker artifacts `test_replay_fixtures.py` depends on were "
            "deleted; restore that run from Dropbox version history / "
            "adam-server releases or re-crawl, then this test runs again"
            % path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_pickup_miles(location):
    try:
        return pickup_area.resolve(location)["miles"]
    except (ValueError, TypeError):
        return None


def _neutral_vision(**overrides):
    vision = {
        "status": "no_images", "image_count": None, "target_colors": "unknown",
        "color_families": [], "themes": [], "minifigs": "not_visible",
        "contamination": [], "retired_sets_visible": None,
        "weight_estimate_lbs": None, "weight_confidence": None,
        "notes": "replay fixture",
    }
    vision.update(overrides)
    return vision


def test_replay_crawl_through_build_deal_record_passes_validate():
    """All 53 real ShopGoodwill.json candidates assemble and validate cleanly."""
    fixture = _require_fixture(SHOPGOODWILL_FIXTURE)
    source = fixture["source"]
    records = fixture["candidate_records"]
    assert len(records) == 53, (
        "expected 53 ShopGoodwill.json candidate_records, found %d -- "
        "the fixture on disk changed" % len(records))

    failures = []
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
            "pickup_miles": _resolve_pickup_miles(candidate.get("item_location")),
            "fee_breakdown": {
                "hammer": price, "premium_pct": 0.0, "premium_amount": 0.0,
                "sales_tax_pct": 0.0, "sales_tax_amount": 0.0,
                "shipping_handling": shipping_total,
                "shipping_estimated": False, "shipping_unknown": shipping_total is None,
                "landed_is_floor": False, "landed_total": landed,
            },
            "observations": {
                "description": "",
                "vision": _neutral_vision(notes="replay fixture carries no image_urls"),
                "model_score": 50,
                "model_rationale": "The replay fixture has neutral deal evidence.",
            },
        }
        record = bdr.build_deal_record(
            candidate, appraisal, first_seen_at=FIRST_SEEN, last_seen_at=LAST_SEEN)
        _, errors, _ = vdr.check(record)
        if errors:
            failures.append((record.get("listing_key"), errors))

    assert not failures, (
        "%d of 53 assembled records failed validate.check(): %r"
        % (len(failures), failures))


def test_replay_ebay_image_urls_survive_assembly():
    """Real eBay.json image_urls arrays survive build_deal_record unchanged."""
    fixture = _require_fixture(EBAY_FIXTURE)
    records = [r for r in fixture["candidate_records"] if r.get("image_urls")]
    assert records, "no eBay.json candidate carries image_urls -- the fixture changed"

    for raw in records:
        image_urls = list(raw["image_urls"])
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
                "vision": _neutral_vision(
                    status="checked", image_count=len(image_urls),
                    notes="replay of real eBay image_urls"),
                "model_score": 50,
                "model_rationale": "The replay fixture has neutral deal evidence.",
            },
        }
        record = bdr.build_deal_record(
            candidate, appraisal, first_seen_at=FIRST_SEEN, last_seen_at=LAST_SEEN)
        assert record.get("image_urls") == image_urls, (
            "%s: image_urls did not survive assembly -- got %r, expected the "
            "real captured %r"
            % (raw["listing_key"], record.get("image_urls"), image_urls))
        _, errors, _ = vdr.check(record)
        assert not errors, (
            "%s: image_urls survived but check() reported errors: %s"
            % (raw["listing_key"], errors))


def test_replay_blocked_source_contributes_zero_not_empty_success():
    """A real `blocked: true` artifact is evidenced, not an empty success."""
    fixture = _require_fixture(PROXIBID_FIXTURE)

    required_keys = (
        "source", "checked", "blocked", "blocker", "candidate_records",
        "unavailable_updates", "unchanged_duplicate_keys", "learning_notes",
        "actions_requiring_approval", "evidence_summary", "completed_at",
    )
    missing = [k for k in required_keys if k not in fixture]
    assert not missing, "proxibid.json is missing required top-level keys: %s" % missing
    assert fixture["blocked"] is True
    assert fixture["checked"] is True, (
        "a blocked source is still 'checked' -- it was reached and positively "
        "identified as blocked")
    assert fixture["candidate_records"] == [], (
        "blocked source should contribute zero candidates, got %d"
        % len(fixture["candidate_records"]))
    assert isinstance(fixture["blocker"], str) and fixture["blocker"].strip(), (
        "blocker evidence string is empty -- a block with no evidence is "
        "indistinguishable from a worker that produced nothing")


def test_replay_no_images_is_a_valid_terminal_state():
    """A seller who posts no photos assembles and validates cleanly."""
    fixture = _require_fixture(SHOPGOODWILL_FIXTURE)
    source = fixture["source"]
    candidate = dict(fixture["candidate_records"][0])
    candidate["source"] = source
    assert "image_urls" not in candidate, (
        "test fixture assumption broken: ShopGoodwill.json candidate already "
        "carries image_urls")

    appraisal = {
        "listing_category": "bulk",
        "estimated_total": candidate["buy_now_price"],
        "per_lb_price": None,
        "per_lb_price_basis": "unknown",
        "confidence": "low",
        "pickup_miles": _resolve_pickup_miles(candidate.get("item_location")),
        "fee_breakdown": {
            "hammer": candidate["buy_now_price"], "premium_pct": 0.0, "premium_amount": 0.0,
            "sales_tax_pct": 0.0, "sales_tax_amount": 0.0,
            "shipping_handling": shipping_estimate.total_of(candidate),
            "shipping_estimated": False, "shipping_unknown": False,
            "landed_is_floor": False, "landed_total": candidate["buy_now_price"],
        },
        "observations": {
            "description": "",
            "vision": _neutral_vision(notes="seller posted no photos"),
            "model_score": 50,
            "model_rationale": "The replay fixture has neutral deal evidence.",
        },
    }
    record = bdr.build_deal_record(
        candidate, appraisal, first_seen_at=FIRST_SEEN, last_seen_at=LAST_SEEN)
    assert record.get("image_urls") == [], (
        "expected image_urls == [] on a record with no captured images, got %r"
        % record.get("image_urls"))
    assert (record.get("observations") or {}).get("vision", {}).get("status") == "no_images"
    _, errors, _ = vdr.check(record)
    assert not errors, (
        "no_images with empty image_urls should pass check() cleanly, got "
        "errors: %s" % errors)
