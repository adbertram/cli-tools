from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from legoscout_cli import orchestrator
from legoscout_cli.pricing import minifig_identification as identification
from legoscout_cli.pricing import minifig_sales


def _candidate(fig_no: str) -> dict:
    return {
        "id": fig_no,
        "name": f"Candidate {fig_no}",
        "img_url": f"https://example.invalid/{fig_no}.webp",
        "external_sites": [],
        "category": "Theme",
        "type": "fig",
        "score": 0.9,
    }


def _detection(crop_id: str, *, photo: str = "photo-1", confidence=0.9) -> dict:
    return {
        "crop_id": crop_id,
        "source_photo_sha256": ("a" if photo == "photo-1" else "b") * 64,
        "photo_relative_id": photo,
        "box": [0.1, 0.1, 0.4, 0.8],
        "detector_name": "fixture-detector",
        "detector_version": "v1",
        "detector_confidence": confidence,
        "crop_ref": f"crops/{crop_id}.jpg",
    }


def _group(
    group_id: str,
    crop_id: str,
    *,
    fig_no: str = "sw0001",
    candidates: tuple[str, ...] = ("sw0001",),
) -> dict:
    return {
        "match_group_id": group_id,
        "candidate_signature": "fixture-signature",
        "detections": [_detection(crop_id)],
        "representative_crop_ref": f"crops/{crop_id}.jpg",
        "brickognize_candidates": [_candidate(value) for value in candidates],
        "brickognize_contract": {"contract_version": "fixture-v1"},
        "status": "success",
        "reason": None,
        "verification": {
            "status": "verified",
            "reason": "crop, catalog name, and catalog image agree",
            "compared_candidate_ids": list(candidates),
            "catalog_checked_at": "2026-08-25T00:00:00Z",
        },
        "fig_no": fig_no,
        "catalog": {
            "no": fig_no,
            "name": f"Catalog {fig_no}",
            "thumbnail_url": f"//img.bricklink.com/M/{fig_no}.jpg",
        },
        "condition_notes": None,
    }


def _artifact(listings: list[tuple[str, list[dict], str, str | None]]) -> dict:
    rows = []
    for key, groups, status, reason in listings:
        row = {
            "listing_key": key,
            "observations": {},
            "status": status,
            "reason": reason,
            "groups": groups,
        }
        row["source_member_digest"] = identification.source_member_digest(row)
        rows.append(row)
    return {
        "version": 1,
        "kind": "minifig_identification",
        "request_contract": {},
        "listings": rows,
        "summary": {},
        "timings": {},
    }


def _priced(fig_no: str, catalog: dict, refresh: bool = False) -> dict:
    return {
        "fig_no": fig_no,
        "catalog": catalog,
        "used": {
            "condition": "U",
            "guide_type": "sold",
            "sold_window": "bricklink_sold_guide_last_6_months",
            "six_month_avg_sold_price": 10.0,
            "avg_price": 10.0,
            "qty_avg_price": 10.0,
            "unit_quantity": 2,
            "total_quantity": 2,
            "price_detail_count": 2,
            "price_detail": [],
        },
        "lookup_status": "found",
        "unit_value": 10.0,
        "null_value_reason": None,
    }


def test_should_preserve_upstream_incomplete_reason_and_never_mark_pricing_complete():
    report = identification.price_batch(_artifact([
        ("source|1", [_group("group-1", "crop-1")], "success",
         "1 of 2 photos skipped: unreadable image"),
    ]), pricer=_priced)

    result = report["results"][0]
    assert result["status"] == "success"
    assert result["reason"] == "1 of 2 photos skipped: unreadable image"
    assert result["pricing_complete"] is False
    assert result["priced_subtotal"] == 10.0


@pytest.mark.parametrize("mutation, expected", [
    ("empty-comparison", "all Brickognize candidates"),
    ("partial-comparison", "all Brickognize candidates"),
    ("fig-outside-candidates", "fig_no must be one of"),
    ("catalog-name-missing", "catalog name"),
    ("catalog-image-missing", "catalog image"),
    ("provider-skipped", "provider-success"),
])
def test_should_block_verified_semantics_without_complete_provider_and_catalog_evidence(
    mutation,
    expected,
):
    group = _group(
        "group-1", "crop-1", fig_no="sw0001",
        candidates=("sw0001", "sw0002"),
    )
    if mutation == "empty-comparison":
        group["verification"]["compared_candidate_ids"] = []
    elif mutation == "partial-comparison":
        group["verification"]["compared_candidate_ids"] = ["sw0001"]
    elif mutation == "fig-outside-candidates":
        group["fig_no"] = "sw9999"
        group["catalog"]["no"] = "sw9999"
    elif mutation == "catalog-name-missing":
        del group["catalog"]["name"]
    elif mutation == "catalog-image-missing":
        del group["catalog"]["thumbnail_url"]
    else:
        group["status"] = "skipped"
        group["reason"] = "provider timed out"

    calls = []
    result = identification.price_batch(
        _artifact([("source|1", [group], "success", None)]),
        pricer=lambda *args, **kwargs: calls.append((args, kwargs)),
    )["results"][0]

    assert calls == []
    entry = result["minifig_analysis"][0]
    assert entry["verification"]["status"] == "unverifiable"
    assert entry["null_value_reason"] == "stage_failed"
    assert expected in entry["errors"][0]
    assert result["pricing_complete"] is False


def test_should_isolate_malformed_detection_group_and_price_valid_sibling():
    valid = _group("valid-group", "valid-crop")
    malformed = _group("bad-group", "bad-crop", fig_no="sw0002",
                       candidates=("sw0002",))
    malformed["detections"][0]["box"] = [.8, .1, .2, .8]
    artifact = _artifact([
        ("source|1", [valid, malformed], "success", None),
    ])
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append(fig_no)
        return _priced(fig_no, catalog, refresh)

    result = identification.price_batch(artifact, pricer=pricer)["results"][0]

    assert calls == ["sw0001"]
    assert [entry["fig_no"] for entry in result["minifig_analysis"]] == ["sw0001"]
    assert result["failed_groups"][0]["match_group_id"] == "bad-group"
    # The malformed group's own mutation is the inverted box; the isolation
    # error must name that defect, not an unrelated field.
    assert "box is inverted" in result["failed_groups"][0]["errors"][0]
    assert result["pricing_complete"] is False


def _source(key: str) -> dict:
    return {"listing_key": key}


def _appraisal(key: str, category: str = "minifigure") -> dict:
    return {"listing_key": key, "listing_category": category}


def test_should_reject_reversed_identification_subset_order():
    sources = [_source("source|1"), _source("source|2"), _source("source|3")]
    appraisals = [
        _appraisal("source|1"),
        _appraisal("source|2", "bulk"),
        _appraisal("source|3"),
    ]
    reversed_results = [
        {"listing_key": "source|3"},
        {"listing_key": "source|1"},
    ]

    with pytest.raises(
        orchestrator.AppraisalBatchKeyError,
        match="identification result order",
    ):
        orchestrator.validate_identification_batch(
            sources, appraisals, reversed_results)


def _detection_artifact(shared_ref: str) -> dict:
    listings = []
    for key in ("source|1", "source|2"):
        listings.append({
            "listing_key": key,
            "observations": {},
            "status": "success",
            "reason": None,
            "photos": [{
                "photo_relative_id": "photo-1",
                "source_photo_sha256": "a" * 64,
                "status": "success",
                "reason": None,
                "detections": [_detection("shared-crop") | {
                    "crop_ref": shared_ref,
                }],
            }],
        })
    return {
        "version": 1,
        "kind": "minifig_detection",
        "detector": {"name": "fixture", "contract_version": "v1"},
        "listings": listings,
        "summary": {},
    }


def test_should_scope_content_crop_and_group_ids_to_listing_and_coalesce_price(tmp_path):
    crop_root = tmp_path / "crops"
    shared_ref = "shared/shared-crop.jpg"
    crop_path = crop_root / shared_ref
    crop_path.parent.mkdir(parents=True)
    crop_path.write_bytes(b"same content")

    def predictor(paths, **kwargs):
        assert paths == [str(crop_path), str(crop_path)]
        return [{
            "path": path,
            "status": "success",
            "reason": None,
            "cached": False,
            "prediction": {
                "contract": {"contract_version": "fixture-v1"},
                "response": {
                    "listing_id": "fixture",
                    "bounding_box": {
                        "left": 0, "upper": 0, "right": 1, "lower": 1,
                        "image_width": 1, "image_height": 1, "score": 1,
                    },
                    "items": [_candidate("sw0001")],
                },
            },
        } for path in paths]

    identified = identification.identify_batch(
        _detection_artifact(shared_ref),
        crop_root=crop_root,
        workers=1,
        top_k=10,
        min_similarity=0.5,
        predictor=predictor,
    )
    assert [row["listing_key"] for row in identified["listings"]] == [
        "source|1", "source|2"]
    assert [row["groups"][0]["detections"][0]["crop_id"]
            for row in identified["listings"]] == ["shared-crop", "shared-crop"]

    for listing in identified["listings"]:
        group = listing["groups"][0]
        group.update({
            "verification": {
                "status": "verified",
                "reason": "crop, catalog name, and image agree",
                "compared_candidate_ids": ["sw0001"],
                "catalog_checked_at": "2026-08-25T00:00:00Z",
            },
            "fig_no": "sw0001",
            "catalog": {
                "no": "sw0001",
                "name": "Catalog sw0001",
                "thumbnail_url": "//img.bricklink.com/M/sw0001.jpg",
            },
            "condition_notes": None,
        })

    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append(fig_no)
        return _priced(fig_no, catalog, refresh)

    priced = identification.price_batch(identified, pricer=pricer)
    assert calls == ["sw0001"]
    assert [row["listing_key"] for row in priced["results"]] == [
        "source|1", "source|2"]
    assert [row["priced_subtotal"] for row in priced["results"]] == [10.0, 10.0]


def test_should_coalesce_same_fig_even_when_catalog_evidence_payloads_differ():
    first = _group("group-1", "crop-1")
    second = _group("group-2", "crop-2")
    second["catalog"]["name"] = "Alternate localized catalog name"
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append((fig_no, copy.deepcopy(catalog)))
        return _priced(fig_no, catalog, refresh)

    results = identification.price_batch(_artifact([
        ("source|1", [first], "success", None),
        ("source|2", [second], "success", None),
    ]), pricer=pricer)["results"]

    assert len(calls) == 1
    assert [row["minifig_analysis"][0]["catalog"]["name"] for row in results] == [
        "Catalog sw0001", "Alternate localized catalog name"]


def test_run_batch_stage_preserves_order_isolates_and_uses_canonical_statuses(tmp_path):
    output = tmp_path / "stage.json"
    items = [{"listing_key": "source|1"}, {"listing_key": "source|2"}]

    def process_one(item):
        if item["listing_key"] == "source|1":
            raise RuntimeError("fixture failure")
        return {**item, "status": "success", "reason": None}

    report = identification.run_batch_stage(
        "fixture", items, process_one, workers=2, output_path=output)

    assert [row["listing_key"] for row in report["results"]] == [
        "source|1", "source|2"]
    assert [row["status"] for row in report["results"]] == [
        "blocked", "success"]
    assert set(row["status"] for row in report["results"]) <= {
        "success", "skipped", "blocked"}
    assert report["summary"]["processed"] == 2
    assert report["summary"]["succeeded"] == 1
    assert report["summary"]["failed"] == 1
    assert json.loads(output.read_text()) == report
