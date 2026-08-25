from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from legoscout_cli.commands import minifig as minifig_commands
from legoscout_cli.display import rows as display_rows
from legoscout_cli.ledger import build_record, db as ledger_db
from legoscout_cli.main import app
from legoscout_cli.orchestrator import build_run_manifest, synthesis_coverage
from legoscout_cli.pricing import minifig_detector
from legoscout_cli.pricing import minifig_identification as identification

runner = CliRunner()


def _candidate():
    return {
        "listing_key": "k-bid|phase-g",
        "source": "k-bid",
        "title": "Three Star Wars minifigures",
        "url": "https://example.invalid/phase-g",
        "direct_url": "https://example.invalid/phase-g",
        "current_price": 40.0,
        "price_basis": "current_price",
        "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
        "item_location": "Evansville, IN 47725",
        "seller_id": "seller",
        "seller_name": "Seller",
        "image_urls": [],
    }


def _appraisal():
    return {
        "listing_key": "k-bid|phase-g",
        "listing_category": "minifigure",
        "estimated_total": 40.0,
        "fee_breakdown": {
            "hammer": 40.0,
            "premium_pct": 0.0,
            "sales_tax_pct": 0.0,
            "shipping_handling": 0.0,
        },
        "observations": {
            "vision": {
                "status": "observed",
                "stated_figure_count": 4,
                "photo_figure_count": 3,
            },
            "description": "fixture",
            "model_score": 50,
            "model_rationale": "fixture",
        },
    }


def _source_artifact():
    return {
        "source": "k-bid",
        "checked": True,
        "blocked": False,
        "blocker": None,
        "candidate_records": [_candidate()],
        "unavailable_updates": [],
        "unchanged_duplicate_keys": [],
        "learning_notes": [],
        "actions_requiring_approval": [],
        "evidence_summary": "fixture",
        "completed_at": "2026-08-25T00:00:00Z",
    }


def _provider_items():
    return [
        {
            "id": "sw0001",
            "name": "Clone Trooper",
            "img_url": "https://example.invalid/sw0001.webp",
            "external_sites": [],
            "category": "Star Wars",
            "type": "fig",
            "score": .9,
        },
    ]


def _provider_prediction(paths, **kwargs):
    rows = []
    for path in paths:
        rows.append({
            "path": path,
            "status": "success",
            "reason": None,
            "cached": False,
            "prediction": {
                "contract": {
                    "endpoint": "https://api.brickognize.com/predict/figs/",
                    "contract_version": "brickognize-legacy-figs-v1",
                    "crop_sha256": "c" * 64,
                    "top_k_items": 10,
                    "min_similarity_items": .5,
                },
                "response": {
                    "listing_id": "fixture",
                    "bounding_box": {
                        "left": 0.0, "upper": 0.0,
                        "right": 100.0, "lower": 100.0,
                        "image_width": 100.0, "image_height": 100.0,
                        "score": .99,
                    },
                    "items": _provider_items(),
                },
            },
        })
    return rows


def _pricer(fig_no, catalog, refresh=False):
    return {
        "fig_no": fig_no,
        "catalog": catalog,
        "used": {
            "condition": "U",
            "guide_type": "sold",
            "sold_window": "bricklink_sold_guide_last_6_months",
            "six_month_avg_sold_price": 30.0,
            "avg_price": 30.0,
            "qty_avg_price": 30.0,
            "unit_quantity": 8,
            "total_quantity": 8,
            "price_detail_count": 8,
            "price_detail": [],
        },
        "lookup_status": "found",
        "unit_value": 30.0,
        "null_value_reason": None,
    }


def _set_kwdefault(monkeypatch, function, name, value):
    defaults = dict(function.__kwdefaults__ or {})
    defaults[name] = value
    monkeypatch.setattr(function, "__kwdefaults__", defaults)


def test_public_minifig_pipeline_pairs_builds_persists_and_displays(
    monkeypatch,
    tmp_path,
):
    image = tmp_path / "listing.jpg"
    Image.new("RGB", (100, 100), color=(10, 20, 30)).save(image, "JPEG")
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps([{
        "listing_key": "k-bid|phase-g",
        "saved_photo_paths": [str(image)],
        "observations": _appraisal()["observations"],
    }]), encoding="utf-8")
    crop_root = tmp_path / "crops"
    detection_path = tmp_path / "detection.json"
    identify_path = tmp_path / "identify-stage.json"
    verified_path = tmp_path / "verified.json"
    final_path = tmp_path / "k-bid.identify-1.json"

    def detector_loader():
        def detect(paths):
            return [{
                "path": path,
                "detections": [
                    {"box": [.05, .1, .3, .9], "confidence": .9},
                    {"box": [.35, .1, .6, .9], "confidence": .8},
                    {"box": [.65, .1, .95, .9], "confidence": .7},
                ],
            } for path in paths]
        return detect

    monkeypatch.setitem(
        minifig_detector.DETECTOR_LOADERS, "recorded-detector", detector_loader)
    detected = runner.invoke(app, [
        "minifig", "detect",
        "--input", str(handoff),
        "--output", str(detection_path),
        "--detector", "recorded-detector",
        "--crop-root", str(crop_root),
    ])
    assert detected.exit_code == 0, detected.output

    monkeypatch.setattr(minifig_commands, "MINIFIG_CROP_ROOT", str(crop_root))
    _set_kwdefault(
        monkeypatch, identification.identify_file,
        "predictor", _provider_prediction)
    _set_kwdefault(
        monkeypatch, identification.identify_file,
        "cache_path", str(tmp_path / "brickognize-cache.json"))
    identified = runner.invoke(app, [
        "minifig", "identify",
        "--input", str(detection_path),
        "--output", str(identify_path),
    ])
    assert identified.exit_code == 0, identified.output

    verified = json.loads(identify_path.read_text())
    assert verified["listings"][0]["source_member_digest"].startswith(
        "figmembers-v1-")
    for index, group in enumerate(verified["listings"][0]["groups"]):
        group["verification"] = {
            "status": "verified",
            "reason": "recorded visual/catalog match",
            "compared_candidate_ids": ["sw0001"],
            "catalog_checked_at": "2026-08-25T00:00:00Z",
        }
        group["fig_no"] = "sw0001"
        group["catalog"] = {
            "no": "sw0001",
            "name": "Clone Trooper",
            "thumbnail_url": "//img.bricklink.com/M/sw0001.jpg",
        }
        group["condition_notes"] = None
    verified_path.write_text(json.dumps(verified), encoding="utf-8")

    _set_kwdefault(monkeypatch, identification.price_file, "pricer", _pricer)
    priced = runner.invoke(app, [
        "minifig", "price",
        "--input", str(verified_path),
        "--output", str(final_path),
    ])
    assert priced.exit_code == 0, priced.output
    final_results = json.loads(final_path.read_text())
    assert final_results[0]["figure_count"] == 3
    assert final_results[0]["priced_subtotal"] == 90.0

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "k-bid.json").write_text(
        json.dumps(_source_artifact()), encoding="utf-8")
    (run_dir / "k-bid.appraisal-1.json").write_text(
        json.dumps([_appraisal()]), encoding="utf-8")
    (run_dir / "k-bid.identify-1.json").write_text(
        json.dumps(final_results), encoding="utf-8")
    manifest = build_run_manifest(str(run_dir), active_sources=["k-bid"])
    assert manifest["complete"] is True, manifest

    coverage = synthesis_coverage(
        [_candidate()], [_appraisal()], identification_results=final_results,
        fee_rate=.13)
    assert coverage["complete"] is True, coverage

    record = build_record.build_deal_record(
        _candidate(), _appraisal(),
        first_seen_at="2026-08-25T00:00:00Z",
        last_seen_at="2026-08-25T00:00:00Z",
        identification=final_results[0],
        fee_rate=.13,
    )
    db_path = str(tmp_path / "found_deals.db")
    ledger_db.init(db_path).close()
    ledger_db.upsert_deals([record], path=db_path)
    stored = ledger_db.get_deal("k-bid|phase-g", path=db_path)
    assert stored is not None
    assert stored["figure_count"] == 3
    assert stored["figure_count_source"] == "detection"
    assert stored["potential_profit"] == 38.3
    assert len(stored["minifig_analysis"]) == 1
    assert len(stored["minifig_analysis"][0]["detections"]) == 3
    assert stored["minifig_analysis"][0]["representative_crop_ref"]

    row = display_rows.row(stored, favorites=set())
    assert row["figCount"] == 3
    assert row.get("perFig") is None
