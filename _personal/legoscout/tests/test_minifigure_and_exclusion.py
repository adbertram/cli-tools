"""The three-plus-one classification universe: bulk, set, minifigure, excluded.

Every downstream layer reads the classifier's `listing_category`, so a new tag
must be accepted end to end -- comps dispatch, comps-result validation, record
building, scoring, and validation -- and an `excluded` tag must always build as
`status: rejected` with a reason, never as an active deal.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from legoscout_cli.ledger import build_record
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.ledger import validate as ledger_validate
from legoscout_cli.orchestrator import (
    _is_classifier_exclusion,
    synthesis_coverage,
    validate_comps_result,
)
from legoscout_cli.pricing import comps, comps_batch, ebay_comps
from legoscout_cli.scoring import score
from legoscout_cli.main import app


# ---------------------------------------------------------------------------
# Minifigure eBay $/fig retirement
# ---------------------------------------------------------------------------


def test_pricing_comps_rejects_minifigure_option_and_help_omits_it():
    runner = CliRunner()
    rejected = runner.invoke(app, ["pricing", "comps", "--minifigure"])
    assert rejected.exit_code == 2
    assert "No such option" in rejected.output
    help_result = runner.invoke(app, ["pricing", "comps", "--help"])
    assert help_result.exit_code == 0
    assert "minifigure" not in help_result.stdout.lower()


def test_pricing_modules_expose_no_executable_minifigure_dispatch():
    assert not hasattr(ebay_comps, "search_minifigure_comps")
    assert not hasattr(ebay_comps, "_minifig_count")
    assert not hasattr(comps, "minifigure_comps")
    assert not hasattr(comps_batch.comps_module, "minifigure_comps")
    blocked = comps_batch.price_one({
        "listing_key": "ebay|1",
        "listing_category": "minifigure",
        "description": "star wars",
    }, limit=50)
    assert blocked["blocked"] is True
    assert "legoscout minifig" in blocked["blocker"]


def test_no_new_path_ebay_per_figure_execution_surface_remains():
    package = Path(comps.__file__).parents[1]
    paths = [
        package / "pricing" / "ebay_comps.py",
        package / "pricing" / "comps.py",
        package / "pricing" / "comps_batch.py",
        package / "commands" / "pricing.py",
        package / "ledger" / "build_record.py",
        package / "scoring" / "score.py",
    ]
    forbidden = (
        "search_minifigure_comps",
        "_minifig_count",
        "minifigure_comps",
        "_apply_minifigure_comps",
        "avg_price_per_fig",
        "ebay_avg_price_per_fig",
        "--minifigure",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path


def test_excluded_comps_is_a_blocked_result():
    result = comps.excluded_comps("LEGO storage head -- no pieces")

    assert result["mode"] == "excluded"
    assert result["blocked"] is True
    assert result["blocker"] == "LEGO storage head -- no pieces"


# ---------------------------------------------------------------------------
# Batch dispatch
# ---------------------------------------------------------------------------


def test_price_one_dispatches_excluded_with_reason():
    result = comps_batch.price_one(
        {"listing_key": "ebay|1", "listing_category": "excluded",
         "exclusion_reason": "LEGO book -- no pieces"}, limit=50)

    assert result["blocked"] is True
    assert result["blocker"] == "LEGO book -- no pieces"


def test_price_one_excluded_without_reason_is_blocked_with_that_defect():
    result = comps_batch.price_one(
        {"listing_key": "ebay|1", "listing_category": "excluded"}, limit=50)

    assert result["blocked"] is True
    assert "no exclusion_reason" in result["blocker"]


# ---------------------------------------------------------------------------
# Comps-result validation
# ---------------------------------------------------------------------------


def test_validate_comps_result_rejects_retired_minifigure_mode():
    with pytest.raises(Exception, match="must be 'set', 'bulk'"):
        validate_comps_result(
            {"listing_key": "ebay|1", "mode": "minifigure",
             "bricklink": None, "ebay": {"available": True}},
            "retired minifigure result")


def test_validate_comps_result_blocked_excluded_is_exempt_from_mode_check():
    # An excluded candidate's comps result is blocked: true -- no mode shape to
    # cross-check, same exemption the unpriceable-set path already has.
    validate_comps_result(
        {"listing_key": "ebay|1", "mode": "excluded", "blocked": True,
         "blocker": "LEGO book -- no pieces"},
        "excluded result", expected_category="excluded")


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def _candidate(key="ebay|1", **over):
    base = {
        "listing_key": key,
        "title": "test lot",
        "url": "https://example.com/lot",
        "direct_url": "https://example.com/lot",
        "buy_now_price": 40.0,
        "price_basis": "buy_now",
        "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
        "item_location": "Evansville, IN",
        "weight_lbs": 5.0,
        "seller_id": "s1",
        "seller_name": "seller",
        "image_urls": [],
        "first_seen_at": "2026-08-01T00:00:00Z",
        "last_seen_at": "2026-08-01T00:00:00Z",
    }
    base.update(over)
    return base


def _appraisal(category, **over):
    base = {
        "listing_key": "ebay|1",
        "listing_category": category,
        "title": "test lot",
        "available_fulfillment": ["shipping"],
        "fee_breakdown": {
            "hammer": 40.0,
            "premium_pct": 0.0,
            "sales_tax_pct": 0.0,
            "shipping_handling": 0.0,
        },
        "weight_lbs": 5.0,
        "set_completeness": "unknown",
        "set_condition": "unknown",
        "cost_per_lb_note": "unknown",
        "per_lb_price_basis": "unknown",
        "zero_comp_note": "unknown",
        "observations": {
            "vision": {"status": "not_observed"},
            "description": "test",
            "model_score": 50,
            "model_rationale": "test",
        },
        "estimated_total": 40.0,
    }
    base.update(over)
    return base


def test_build_excluded_record_as_active_raises():
    with pytest.raises(ValueError, match="classified as excluded"):
        build_record.build_deal_record(
            _candidate(), _appraisal("excluded",
                                     exclusion_reason="LEGO book -- no pieces"),
            first_seen_at="2026-08-01T00:00:00Z",
            last_seen_at="2026-08-01T00:00:00Z",
            status="active")


def test_build_excluded_record_as_rejected_carries_reason():
    record = build_record.build_deal_record(
        _candidate(), _appraisal("excluded",
                                 exclusion_reason="LEGO book -- no pieces"),
        first_seen_at="2026-08-01T00:00:00Z",
        last_seen_at="2026-08-01T00:00:00Z",
        status="rejected")

    assert record["status"] == "rejected"
    assert record["listing_category"] == "excluded"
    assert "LEGO book" in record["notes"]
    assert record["score"] is None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_record_excluded_is_unscorable_with_reason():
    record = {
        "listing_key": "ebay|1", "listing_category": "excluded",
        "exclusion_reason": "LEGO book -- no pieces",
        "observations": {}, "title": "book",
    }
    result = score.score_record(record)

    assert result["scoring"]["score"] is None
    assert "excluded at classification" in result["scoring"]["unscorable"]
    assert "LEGO book" in result["scoring"]["unscorable"]


def test_score_record_still_rejects_unknown_categories():
    record = {
        "listing_key": "ebay|1", "listing_category": "clothing",
        "observations": {}, "title": "shirt",
    }
    with pytest.raises(ValueError, match="listing_category"):
        score.score_record(record)


# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------


def test_validate_excluded_requires_rejected_and_reason():
    _, errors, _ = ledger_validate.check({
        "listing_key": "ebay|1", "listing_category": "excluded",
        "exclusion_reason": "", "status": "active",
        "listing_type": "fixed", "price_basis": "buy_now",
        "buy_now_price": 10.0,
        "available_fulfillment": ["shipping"],
    })
    joined = "\n".join(errors)
    assert "status" in joined
    assert "exclusion_reason" in joined


def test_validate_rejects_unknown_category():
    _, errors, _ = ledger_validate.check({
        "listing_key": "ebay|1", "listing_category": "clothing",
        "listing_type": "fixed", "price_basis": "buy_now",
        "buy_now_price": 10.0,
        "available_fulfillment": ["shipping"],
    })
    assert any("listing_category" in e for e in errors)


# ---------------------------------------------------------------------------
# Synthesis coverage
# ---------------------------------------------------------------------------


def test_synthesis_coverage_accepts_excluded_pair_as_gate_rejected():
    report = synthesis_coverage(
        [_candidate()],
        [_appraisal("excluded", exclusion_reason="LEGO book -- no pieces")],
        comps_results=[{"listing_key": "ebay|1", "mode": "excluded",
                        "blocked": True, "blocker": "LEGO book -- no pieces"}],
        fee_rate=0.13,
    )

    assert report["complete"] is True
    assert report["buildable_count"] == 1
    assert report["gate_rejected_count"] == 1
    assert report["build_errors"] == []


def test_is_classifier_exclusion_matches_the_gate_message():
    assert _is_classifier_exclusion(
        ValueError("classified as excluded: 'LEGO book' -- ..."))
    assert not _is_classifier_exclusion(ValueError("some other error"))


# ---------------------------------------------------------------------------
# Storage affinity
# ---------------------------------------------------------------------------


def test_minifigure_numeric_columns_round_trip_integers(tmp_path):
    # figure_count and ebay_avg_price_per_fig are numeric columns; a TEXT-affinity
    # column stores integer 20 as '20' and the display row reads figCount: None
    # (isinstance(int) fails on the string). They must be in db._NUMERIC so they
    # get BLOB affinity and round-trip their storage class verbatim.
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()

    deal = {
        "listing_key": "ebay|fig1", "source": "ebay",
        "title": "minifig lot", "url": "https://example.invalid/fig1",
        "buy_now_price": 40.0, "price_basis": "buy_now",
        "listing_category": "minifigure",
        "figure_count": 20,
        "ebay_avg_price_per_fig": 5.0,
        "status": "active",
    }
    ledger_db.upsert_deals([deal], path=path)
    loaded = ledger_db.get_deal("ebay|fig1", path=path)

    assert isinstance(loaded["figure_count"], int), repr(loaded["figure_count"])
    assert loaded["figure_count"] == 20
    assert isinstance(loaded["ebay_avg_price_per_fig"], float)
    assert loaded["ebay_avg_price_per_fig"] == 5.0


# --- legacy read freeze (Phase A): retirement must never eat the evidence ----


def test_legacy_ebay_avg_price_per_fig_survives_connect_and_roundtrip(tmp_path):
    """A stored pre-identification minifigure row stays readable through the
    canonical write/read path. The positive twin of Phase F's negative
    retirement contract: code may retire, the stored evidence may not.
    """
    import legoscout_cli.ledger.db as ledger_db
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    deal = {
        "listing_key": "shopgoodwill|900001",
        "source": "shopgoodwill",
        "status": "active",
        "url": "https://www.shopgoodwill.com/Listing/900001",
        "title": "Star Wars minifigure lot",
        "listing_type": "fixed",
        "price_basis": "current_price",
        "current_price": 40.0,
        "listing_category": "minifigure",
        "available_fulfillment": ["shipping"],
        "observations": {},
        "figure_count": 8,
        "figure_count_source": "stated",
        "ebay_avg_price_per_fig": 5.25,
    }
    ledger_db.upsert_deals([deal], path=path)
    back = ledger_db.get_deal("shopgoodwill|900001", path=path)
    assert back["ebay_avg_price_per_fig"] == 5.25
