from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from legoscout_cli.commands import deals as deals_command
from legoscout_cli.main import app


runner = CliRunner()
FIRST_SEEN = "2026-08-25T00:00:00Z"
LISTING_KEY = "k-bid|phase-k"


def _candidate(key: str = LISTING_KEY) -> dict:
    return {
        "listing_key": key,
        "source": "k-bid",
        "title": "Star Wars minifigure lot",
        "url": "https://example.invalid/phase-k",
        "direct_url": "https://example.invalid/phase-k",
        "current_price": 40.0,
        "price_basis": "current_price",
        "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
        "item_location": "Evansville, IN 47725",
        "seller_id": "phase-k-seller",
        "seller_name": "Phase K Seller",
        "image_urls": [],
    }


def _appraisal(key: str = LISTING_KEY) -> dict:
    return {
        "listing_key": key,
        "listing_category": "minifigure",
        "estimated_total": 40.0,
        "figure_count": 99,
        "figure_count_source": "stated",
        "fee_breakdown": {
            "hammer": 40.0,
            "premium_pct": 0.0,
            "sales_tax_pct": 0.0,
            "shipping_handling": 0.0,
        },
        "observations": {
            "vision": {
                "stated_figure_count": 99,
                "photo_figure_count": 98,
                "status": "observed",
            },
            "description": "seller-stated count intentionally differs",
            "model_score": 50,
            "model_rationale": "Phase K deterministic fixture",
        },
    }


def _detection() -> dict:
    crop_id = "figcrop-v1-phase-k"
    return {
        "crop_id": crop_id,
        "source_photo_sha256": "a" * 64,
        "photo_relative_id": "photo-0001",
        "box": [0.1, 0.1, 0.4, 0.8],
        "detector_name": "grounding-dino-tiny",
        "detector_version": "v1",
        "detector_confidence": 0.9,
        "crop_ref": "aa/%s.jpg" % crop_id,
    }


def _identification(key: str = LISTING_KEY) -> dict:
    analysis = [{
        "match_group_id": "phase-k-group-1",
        "detections": [_detection()],
        "representative_crop_ref": "aa/figcrop-v1-phase-k.jpg",
        "brickognize_candidates": [],
        "verification": {
            "status": "verified",
            "reason": "deterministic fixture",
            "compared_candidate_ids": ["sw0001"],
            "catalog_checked_at": FIRST_SEEN,
        },
        "fig_no": "sw0001",
        "catalog": {"no": "sw0001", "name": "Fixture figure"},
        "quantity": 2,
        "condition_notes": None,
        "used": {"avg_price": 50.0, "price_detail_count": 7},
        "unit_value": 50.0,
        "extended_value": 100.0,
        "null_value_reason": None,
        "errors": [],
    }]
    return {
        "listing_key": key,
        "minifig_analysis": analysis,
        "figure_count": 2,
        "figure_count_source": "detection",
        "identified_count": 2,
        "unknown_count": 0,
        "priced_subtotal": 100.0,
        "sold_count": 7,
        "pricing_complete": True,
        "status": "success",
    }


def _write(path, payload) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _invoke(tmp_path, *, candidate=None, appraisal=None, batch=None, fee="0.13"):
    candidate_path = _write(tmp_path / "candidate.json", candidate or _candidate())
    appraisal_path = _write(tmp_path / "appraisal.json", appraisal or _appraisal())
    identification_path = _write(
        tmp_path / "priced-identifications.json",
        [_identification()] if batch is None else batch,
    )
    args = [
        "deals", "build", candidate_path, appraisal_path,
        "--identification", identification_path,
        "--first-seen-at", FIRST_SEEN,
        "--last-seen-at", FIRST_SEEN,
    ]
    if fee is not None:
        args.extend(["--fee-rate", fee])
    return runner.invoke(app, args)


def test_should_select_the_one_matching_valid_identification_record():
    matching = _identification()
    batch = [_identification("k-bid|unrelated"), matching]

    assert deals_command._select_identification_record(batch, LISTING_KEY) is matching


def test_should_reject_a_non_array_identification_batch_at_the_unit_seam():
    with pytest.raises(ValueError, match="JSON root must be an array"):
        deals_command._select_identification_record(
            {"results": [_identification()]}, LISTING_KEY)


def test_should_build_minifigure_deal_from_matching_priced_identification(tmp_path):
    result = _invoke(tmp_path, batch=[
        _identification("k-bid|unrelated"),
        _identification(),
    ])

    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)
    assert record["listing_key"] == LISTING_KEY
    assert record["figure_count"] == 2
    assert record["figure_count_source"] == "detection"
    assert sum(row["extended_value"] for row in record["minifig_analysis"]) == 100.0
    assert record["potential_profit"] == 47.0
    assert record["profit_incomplete"] is False
    assert record["score"] is not None


@pytest.mark.parametrize(("batch", "message"), [
    ({"results": [_identification()]}, "identification JSON root must be an array"),
    ([], "exactly one record matching candidate listing_key"),
    ([_identification(), _identification()],
     "exactly one record matching candidate listing_key"),
    ([_identification("k-bid|other")],
     "exactly one record matching candidate listing_key"),
    ([42], "identification record 0 must be an object"),
    ([{"listing_key": LISTING_KEY}], "identification record 0"),
])
def test_should_fail_loudly_for_invalid_identification_batches(
    tmp_path, batch, message,
):
    result = _invoke(tmp_path, batch=batch)

    assert result.exit_code != 0
    assert message in result.output


def test_should_fail_loudly_when_candidate_and_appraisal_keys_differ(tmp_path):
    result = _invoke(tmp_path, appraisal=_appraisal("k-bid|other"))

    assert result.exit_code != 0
    assert "appraisal listing_key does not match candidate listing_key" in result.output


@pytest.mark.parametrize(("fee", "message"), [
    (None, "--fee-rate is required when --identification is supplied"),
    ("nan", "fee rate must be a finite decimal from 0 through less than 1"),
    ("1", "fee rate must be a finite decimal from 0 through less than 1"),
])
def test_should_require_a_valid_explicit_resale_fee(tmp_path, fee, message):
    result = _invoke(tmp_path, fee=fee)

    assert result.exit_code != 0
    assert message in result.output
