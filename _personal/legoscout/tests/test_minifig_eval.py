from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from legoscout_cli.pricing import minifig_eval

FIXTURE = Path(__file__).parent / "fixtures" / "minifig_eval"


def _manifest():
    return minifig_eval.load_manifest(str(FIXTURE / "manifest.json"))


def _candidate(name="candidate-a", recall_boxes=None, latency=.2,
               model="model-a", version="1"):
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    images = []
    for listing in manifest["listings"]:
        boxes = (listing.get("expected_boxes", []) if recall_boxes is None
                 else recall_boxes)
        images.append({
            "asset": listing["asset"],
            "detections": [{"box": box, "confidence": .9} for box in boxes],
            "latency_seconds": latency,
        })
    return {
        "name": name,
        "model": model,
        "model_version": version,
        "weights_sha256": "a" * 64,
        "dependency_versions": {"detector-package": "8.4.128"},
        "load_seconds": 1.25,
        "images": images,
    }


def _environment(host="mac"):
    return {
        "host": host,
        "os": "macOS",
        "architecture": "arm64",
        "python_version": "3.11.15",
        "cv2_version": "5.0.0.93",
    }


def test_should_load_version_one_manifest_and_required_provenance():
    manifest = _manifest()
    assert manifest["version"] == 1
    assert manifest["dataset_id"] == "minifig-eval-33-real-listings-v1"
    assert len(manifest["listings"]) == 33
    human_seed_count = 0
    for row in manifest["listings"]:
        assert row["listing_key"]
        assert row["source"]
        assert row["title"]
        assert row["provenance"]["kind"]
        assert row["provenance"]["source_url"].startswith("https://")
        assert row["consent"] == {
            "basis": "public-marketplace-evaluation", "recorded": True}
        assert len(row["photo_sha256"]) == 64
        assert not Path(row["asset"]).is_absolute()
        if "expected_boxes" in row:
            human_seed_count += 1
            assert len(row["expected_boxes"]) == len(row["expected_quantities"])
            assert isinstance(row["expected_identities"], list)
        assert isinstance(row["hard_case_tags"], list)
    assert human_seed_count == 3


def test_should_load_version_one_adam_label_schema():
    labels = minifig_eval.load_labels(str(FIXTURE / "labels.json"))
    assert labels == {
        "version": 1,
        "manifest_version": 1,
        "dataset_id": "minifig-eval-33-real-listings-v1",
        "manifest_sha256": "2028e06a5f3876a093930f94a548223bc01d11a24e6101567ac38f6bc6fe28cb",
        "labeler": "Adam Bertram",
        "decisions": [],
    }


def test_should_reject_wrong_manifest_or_label_version(tmp_path):
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    manifest["version"] = 2
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest))
    with pytest.raises(minifig_eval.EvalDataError, match="version 1"):
        minifig_eval.load_manifest(str(p))

    labels = json.loads((FIXTURE / "labels.json").read_text())
    labels["version"] = 2
    p.write_text(json.dumps(labels))
    with pytest.raises(minifig_eval.EvalDataError, match="version 1"):
        minifig_eval.load_labels(str(p))


def test_should_report_every_missing_workspace_asset_as_skipped(tmp_path):
    statuses = minifig_eval.asset_statuses(_manifest(), str(tmp_path / "absent"))
    assert len(statuses) == 33
    assert all(row["status"] == "skipped" for row in statuses)
    assert all("missing" in row["reason"] for row in statuses)


def test_should_validate_asset_sha256(tmp_path):
    manifest = _manifest()
    listing = manifest["listings"][0]
    asset = tmp_path / listing["asset"]
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"wrong")
    statuses = minifig_eval.asset_statuses(
        {"version": 1, "listings": [listing]}, str(tmp_path))
    assert statuses[0]["status"] == "skipped"
    assert "sha256" in statuses[0]["reason"]


def test_should_compute_per_image_recall_inputs_and_total_recall():
    report = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate()], _environment())
    cand = report["candidates"][0]
    assert cand["recall"]["matched"] == 11
    assert cand["recall"]["expected"] == 11
    assert cand["recall"]["value"] == 1.0
    expected_by_image = [
        row["expected"] for row in cand["recall"]["per_image"]]
    assert len(expected_by_image) == 33
    assert sorted(value for value in expected_by_image if value) == [3, 3, 5]


def test_should_aggregate_load_and_warm_per_image_latency_separately():
    report = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate(latency=.25)], _environment())
    timings = report["candidates"][0]["timings"]
    assert timings == {
        "load_seconds": 1.25,
        "warm_per_image_seconds": [.25] * 33,
        "warm_mean_seconds": .25,
        "warm_max_seconds": .25,
    }


def test_should_require_environment_dependency_model_and_version_fields():
    for field in ("host", "os", "architecture", "python_version", "cv2_version"):
        env = _environment()
        del env[field]
        with pytest.raises(minifig_eval.BenchmarkError, match=field):
            minifig_eval.build_benchmark_report(_manifest(), [_candidate()], env)

    for field in ("model", "model_version", "weights_sha256",
                  "dependency_versions"):
        candidate = _candidate()
        del candidate[field]
        with pytest.raises(minifig_eval.BenchmarkError, match=field):
            minifig_eval.build_benchmark_report(
                _manifest(), [candidate], _environment())


def test_should_reject_candidate_boxes_outside_the_normalized_contract():
    manifest = _manifest()
    bad_candidate = _candidate()
    bad_candidate["images"][0]["detections"] = [{
        "box": [0.0, 0.0, 1.1, 1.0],
        "confidence": 0.9,
    }]

    with pytest.raises(
        minifig_eval.BenchmarkError,
        match="coordinates must be in 0..1",
    ):
        minifig_eval.build_benchmark_report(
            manifest, [bad_candidate], _environment())


def test_should_select_highest_recall_then_fastest_then_name():
    # A misses everything; B and C are exact. B wins the exact recall tie on
    # latency. D ties B on latency too, so lexical name is final tie-breaker.
    empty = _candidate("a", recall_boxes=[], latency=.01)
    c = _candidate("c", latency=.4)
    d = _candidate("d", latency=.2)
    b = _candidate("b", latency=.2)
    report = minifig_eval.build_benchmark_report(
        _manifest(), [empty, c, d, b], _environment())
    assert report["status"] == "success"
    assert report["selected_winner"] == "b"
    assert [row["name"] for row in report["selection_order"]] == ["b", "d", "c"]


def test_should_block_when_no_candidate_has_useful_recall():
    report = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate(recall_boxes=[])], _environment(),
        useful_recall=.5)
    assert report["status"] == "blocked"
    assert report["selected_winner"] is None
    assert "useful recall" in report["reason"]


def test_should_reject_duplicate_candidate_names():
    with pytest.raises(minifig_eval.BenchmarkError, match="duplicate"):
        minifig_eval.build_benchmark_report(
            _manifest(), [_candidate(), _candidate()], _environment())


def test_should_validate_both_host_reports_and_same_winner_contract():
    mac = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate()], _environment("mac"))
    server = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate()], _environment("adam-server"))
    verified = minifig_eval.verify_host_reports(
        [mac, server], required_hosts={"mac", "adam-server"})
    assert verified["status"] == "success"
    assert verified["selected_winner"] == "candidate-a"


def test_should_reject_missing_host_mismatched_model_or_absent_latency():
    mac = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate()], _environment("mac"))
    server = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate()], _environment("adam-server"))
    with pytest.raises(minifig_eval.BenchmarkError, match="adam-server"):
        minifig_eval.verify_host_reports([mac], {"mac", "adam-server"})

    bad_model = copy.deepcopy(server)
    bad_model["candidates"][0]["model_version"] = "2"
    with pytest.raises(minifig_eval.BenchmarkError, match="model"):
        minifig_eval.verify_host_reports([mac, bad_model], {"mac", "adam-server"})

    no_latency = copy.deepcopy(server)
    no_latency["candidates"][0]["timings"]["warm_mean_seconds"] = None
    with pytest.raises(minifig_eval.BenchmarkError, match="latency"):
        minifig_eval.verify_host_reports([mac, no_latency], {"mac", "adam-server"})


def test_should_write_machine_validated_report_command_atomically(tmp_path):
    environment_path = tmp_path / "environment.json"
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "report.json"
    environment_path.write_text(json.dumps(_environment()))
    candidate_path.write_text(json.dumps(_candidate()))
    exit_code = minifig_eval.main([
        "report",
        "--manifest", str(FIXTURE / "manifest.json"),
        "--environment", str(environment_path),
        "--candidate", str(candidate_path),
        "--output", str(output_path),
    ])
    assert exit_code == 0
    report = json.loads(output_path.read_text())
    assert report["status"] == "success"
    assert report["selected_winner"] == "candidate-a"
    assert list(tmp_path.glob(".report.json.*.tmp")) == []


def test_should_write_blocked_report_and_return_nonzero(tmp_path):
    environment_path = tmp_path / "environment.json"
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "report.json"
    environment_path.write_text(json.dumps(_environment()))
    candidate_path.write_text(json.dumps(_candidate(recall_boxes=[])))
    exit_code = minifig_eval.main([
        "report",
        "--manifest", str(FIXTURE / "manifest.json"),
        "--environment", str(environment_path),
        "--candidate", str(candidate_path),
        "--output", str(output_path),
    ])
    assert exit_code != 0
    assert json.loads(output_path.read_text())["status"] == "blocked"


def _phase_j_manifest() -> dict:
    return {
        "version": 1,
        "dataset_id": "test-33-real-v1",
        "asset_root": "workspace",
        "assets_disposable": True,
        "listings": [
            {
                "listing_key": key,
                "source": "k-bid",
                "title": f"Real listing {index}",
                "provenance": {
                    "kind": "classifier-saved-photo",
                    "source_url": f"https://example.test/listing/{index}",
                    "run": "20260823T145220Z",
                },
                "consent": {
                    "basis": "public-marketplace-evaluation",
                    "recorded": True,
                },
                "asset": f"assets/listing-{index}.jpg",
                "photo_sha256": f"{index + 1:064x}",
                "image_size": [1000, 1000],
                "hard_case_tags": ["clutter"] if index == 0 else [],
            }
            for index, key in enumerate(("k-bid|one", "k-bid|two"))
        ],
    }


def _phase_j_labels(*, complete: bool = True) -> dict:
    decisions = []
    if complete:
        decisions = [
            {
                "listing_key": "k-bid|one",
                "expected_boxes": [
                    [0.10, 0.10, 0.30, 0.50],
                    [0.50, 0.10, 0.70, 0.50],
                ],
                "expected_quantity": 2,
                "groups": [
                    {
                        "match_group_id": "group-one-a",
                        "expected_fig_no": "sw0001",
                        "obscure": False,
                    },
                    {
                        "match_group_id": "group-one-b",
                        "expected_fig_no": None,
                        "obscure": True,
                    },
                ],
                "hard_case": True,
                "reviewed_at": "2026-08-25T12:00:00Z",
            },
            {
                "listing_key": "k-bid|two",
                "expected_boxes": [[0.20, 0.20, 0.40, 0.60]],
                "expected_quantity": 1,
                "groups": [
                    {
                        "match_group_id": "group-two-a",
                        "expected_fig_no": "cty0001",
                        "obscure": False,
                    },
                ],
                "hard_case": False,
                "reviewed_at": "2026-08-25T12:00:00Z",
            },
        ]
    manifest = _phase_j_manifest()
    return {
        "version": 1,
        "manifest_version": 1,
        "dataset_id": "test-33-real-v1",
        "manifest_sha256": minifig_eval.canonical_sha256(manifest),
        "labeler": "Adam Bertram",
        "decisions": decisions,
    }


def _phase_j_artifacts(*, perfect: bool = False) -> tuple[dict, dict]:
    manifest = _phase_j_manifest()
    manifest_sha256 = minifig_eval.canonical_sha256(manifest)
    detection_boxes = {
        "k-bid|one": [
            [0.10, 0.10, 0.30, 0.50],
            [0.50, 0.10, 0.70, 0.50],
        ],
        "k-bid|two": [[0.20, 0.20, 0.40, 0.60]],
    }
    if not perfect:
        detection_boxes["k-bid|one"][1] = [0.75, 0.60, 0.90, 0.90]
    detections = {
        "version": 1,
        "kind": "minifig_detection",
        "manifest_sha256": manifest_sha256,
        "detector": {"name": "grounding-dino-tiny", "contract_version": "v1"},
        "listings": [],
        "summary": {"listing_count": 2, "detection_count": 3},
        "timings": {"total_seconds": 2.0, "mean_per_photo_seconds": 1.0},
    }
    identifications = {
        "version": 1,
        "kind": "minifig_identification",
        "manifest_sha256": manifest_sha256,
        "request_contract": {"contract_version": "fixture-v1"},
        "listings": [],
        "summary": {"listing_count": 2, "group_count": 3},
        "timings": {"total_seconds": 3.0, "mean_per_crop_seconds": 1.0},
    }
    group_specs = {
        "k-bid|one": [
            ("group-one-a", "sw0001", "verified", "crop-one-a.jpg"),
            (
                "group-one-b",
                None if perfect else "wrong0001",
                "unknown" if perfect else "verified",
                "crop-one-b.jpg",
            ),
        ],
        "k-bid|two": [
            (
                "group-two-a",
                "cty0001" if perfect else "wrong0002",
                "verified",
                "crop-two-a.jpg",
            ),
        ],
    }
    for listing in manifest["listings"]:
        key = listing["listing_key"]
        photo_detections = [
            (lambda crop_id: {
                "box": box,
                "crop_ref": f"{crop_id}.jpg",
                "photo_relative_id": "photo-0001",
                "source_photo_sha256": listing["photo_sha256"],
                "crop_id": crop_id,
            })("figcrop-v1-" + hashlib.sha256(
                f"{key}:{index}".encode()).hexdigest())
            for index, box in enumerate(detection_boxes[key])
        ]
        detections["listings"].append({
            "listing_key": key,
            "status": "success",
            "reason": None,
            "observations": {},
            "photos": [{
                "photo_relative_id": "photo-0001",
                "source_photo_sha256": listing["photo_sha256"],
                "status": "success",
                "reason": None,
                "detections": photo_detections,
            }],
        })
        groups = []
        for group_id, fig_no, status, crop_ref in group_specs[key]:
            candidate = {
                "id": fig_no or "candidate-unknown",
                "name": "Candidate",
                "score": 0.9,
                "img_url": "https://example.test/candidate.webp",
            }
            source_detection = copy.deepcopy(
                photo_detections[min(len(groups), len(photo_detections) - 1)])
            crop_ref = source_detection["crop_ref"]
            group_detections = [source_detection]
            if not perfect and group_id == "group-two-a":
                duplicate = copy.deepcopy(source_detection)
                duplicate["crop_id"] = str(duplicate["crop_id"]) + "-duplicate"
                duplicate["crop_ref"] = f"{duplicate['crop_id']}.jpg"
                photo_detections.append(copy.deepcopy(duplicate))
                group_detections.append(duplicate)
            groups.append({
                "match_group_id": group_id,
                "status": "success",
                "reason": None,
                "representative_crop_ref": crop_ref,
                "brickognize_contract": {
                    "crop_sha256": hashlib.sha256(str(crop_ref).encode()).hexdigest(),
                },
                "brickognize_candidates": [candidate],
                "detections": group_detections,
                "verification": {
                    "status": status,
                    "reason": "fixture",
                    "compared_candidate_ids": [candidate["id"]],
                    "catalog_checked_at": "2026-08-25T12:00:00Z",
                },
                "fig_no": fig_no,
            })
        identifications["listings"].append({
            "listing_key": key,
            "status": "success",
            "reason": None,
            "observations": {},
            "groups": groups,
        })
    identifications["detection_artifact_sha256"] = minifig_eval.canonical_sha256(
        detections)
    return detections, identifications


def _write_eval_inputs(tmp_path, *, labels=None, perfect=False):
    manifest = _phase_j_manifest()
    detections, identifications = _phase_j_artifacts(perfect=perfect)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for listing in manifest["listings"]:
        asset = workspace / listing["asset"]
        asset.parent.mkdir(exist_ok=True)
        asset.write_bytes(bytes.fromhex(listing["photo_sha256"]))
        listing["photo_sha256"] = minifig_eval.hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest_digest = minifig_eval.canonical_sha256(manifest)
    labels_value = copy.deepcopy(labels if labels is not None else _phase_j_labels())
    labels_value["manifest_sha256"] = manifest_digest
    manifest_by_key = {row["listing_key"]: row for row in manifest["listings"]}
    detections["manifest_sha256"] = manifest_digest
    for detection_listing in detections["listings"]:
        photo_hash = manifest_by_key[detection_listing["listing_key"]]["photo_sha256"]
        for photo in detection_listing["photos"]:
            photo["source_photo_sha256"] = photo_hash
            for detection in photo["detections"]:
                detection["source_photo_sha256"] = photo_hash
    identifications["manifest_sha256"] = manifest_digest
    for identification_listing in identifications["listings"]:
        photo_hash = manifest_by_key[identification_listing["listing_key"]]["photo_sha256"]
        for group in identification_listing["groups"]:
            for detection in group["detections"]:
                detection["source_photo_sha256"] = photo_hash
    identifications["detection_artifact_sha256"] = minifig_eval.canonical_sha256(detections)
    manifest_path = tmp_path / "manifest.json"
    labels_path = tmp_path / "labels.json"
    manifest_path.write_text(json.dumps(manifest))
    labels_path.write_text(json.dumps(labels_value))
    (workspace / "detections.json").write_text(json.dumps(detections))
    (workspace / "identifications.json").write_text(json.dumps(identifications))
    return manifest_path, labels_path, workspace


def _write_eval_crops(root, identifications):
    for listing in identifications["listings"]:
        for group in listing["groups"]:
            ref = group["representative_crop_ref"]
            path = root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(ref.encode())


def test_should_ship_exactly_33_real_listing_manifest_rows_and_no_fake_labels():
    manifest = _manifest()
    labels = minifig_eval.load_labels(
        str(FIXTURE / "labels.json"), manifest=manifest)
    assert manifest["dataset_id"] == "minifig-eval-33-real-listings-v1"
    assert len(manifest["listings"]) == 33
    assert len({row["listing_key"] for row in manifest["listings"]}) == 33
    assert {row["source"] for row in manifest["listings"]} == {
        "ebay", "hibid", "k-bid", "shopgoodwill"}
    assert sum(bool(row["hard_case_tags"])
               for row in manifest["listings"]) == 15
    assert all(row["provenance"]["source_url"].startswith("https://")
               for row in manifest["listings"])
    assert labels["dataset_id"] == manifest["dataset_id"]
    assert labels["decisions"] == []


def test_should_reject_duplicate_unknown_mismatched_or_malformed_human_labels(tmp_path):
    manifest = _phase_j_manifest()
    labels = _phase_j_labels()

    duplicate = copy.deepcopy(labels)
    duplicate["decisions"].append(copy.deepcopy(duplicate["decisions"][0]))
    with pytest.raises(minifig_eval.EvalDataError, match="duplicate label listing_key"):
        minifig_eval.validate_labels(duplicate, manifest)

    unknown = copy.deepcopy(labels)
    unknown["decisions"][0]["listing_key"] = "k-bid|unknown"
    with pytest.raises(minifig_eval.EvalDataError, match="unknown manifest listing_key"):
        minifig_eval.validate_labels(unknown, manifest)

    mismatch = copy.deepcopy(labels)
    mismatch["dataset_id"] = "different-dataset"
    with pytest.raises(minifig_eval.EvalDataError, match="dataset_id"):
        minifig_eval.validate_labels(mismatch, manifest)

    malformed = copy.deepcopy(labels)
    malformed["decisions"][0]["groups"][0]["obscure"] = "yes"
    with pytest.raises(minifig_eval.EvalDataError, match="obscure must be a boolean"):
        minifig_eval.validate_labels(malformed, manifest)


def test_should_emit_deterministic_human_queue_from_detect_and_identify_proposals():
    manifest = _phase_j_manifest()
    detections, identifications = _phase_j_artifacts()
    queue = minifig_eval.build_labeling_queue(
        manifest, _phase_j_labels(complete=False), detections, identifications)
    assert queue["dataset_id"] == manifest["dataset_id"]
    assert queue["labeler"] == "Adam Bertram"
    assert queue["summary"] == {
        "listing_count": 2,
        "pending_listing_count": 2,
        "proposal_group_count": 3,
        "hard_case_listing_count": 1,
    }
    first = queue["proposals"][0]
    assert first["listing_key"] == "k-bid|one"
    assert first["proposed_boxes"] == [
        [0.10, 0.10, 0.30, 0.50],
        [0.75, 0.60, 0.90, 0.90],
    ]
    assert first["expected_boxes"] is None
    assert first["expected_quantity"] is None
    assert first["groups"][0]["match_group_id"] == "group-one-a"
    assert first["groups"][0]["representative_crop_ref"] == (
        detections["listings"][0]["photos"][0]["detections"][0]["crop_ref"])
    assert first["groups"][0]["expected_fig_no"] is None
    assert first["groups"][0]["obscure"] is None


def test_should_compute_all_locked_metrics_with_exact_non_vacuous_formulas():
    manifest = _phase_j_manifest()
    labels = minifig_eval.validate_labels(_phase_j_labels(), manifest)
    detections, identifications = _phase_j_artifacts()
    report = minifig_eval.build_eval_report(
        manifest, labels, detections, identifications, stage="all")
    metrics = report["metrics"]
    assert metrics["detection_recall"] == {
        "matched": 2, "expected": 3, "excluded": 0,
        "value": pytest.approx(2 / 3)}
    assert metrics["verified_id_precision"] == {
        "correct": 1, "verified": 3, "excluded": 0,
        "value": pytest.approx(1 / 3)}
    assert metrics["wrong_id_escape_rate"] == {
        "escaped": 2, "labeled_groups": 3, "excluded": 0,
        "value": pytest.approx(2 / 3)}
    assert metrics["exact_quantity_lot_rate"] == {
        "exact": 1, "labeled_lots": 2, "excluded": 0, "value": 0.5}
    assert metrics["obscure_unknown_with_crop"] == {
        "routed": 0, "obscure": 1, "excluded": 0, "value": 0.0}
    assert report["timings"]["identify"] == {
        "total_seconds": 3.0, "mean_per_crop_seconds": 1.0}
    assert report["status"] == "failed"
    assert {bar["name"] for bar in report["bars"] if not bar["passed"]} == {
        "detection_recall",
        "verified_id_precision",
        "wrong_id_escape_rate",
        "exact_quantity_lot_rate",
        "obscure_unknown_with_crop",
    }


@pytest.mark.parametrize(
    ("stage", "expected_bars"),
    [
        ("all", 5),
        ("detect", 1),
        ("identify", 3),
        ("quantity", 1),
    ],
)
def test_should_apply_only_the_selected_stage_bars(stage, expected_bars, tmp_path):
    manifest = _phase_j_manifest()
    labels = minifig_eval.validate_labels(_phase_j_labels(), manifest)
    detections, identifications = _phase_j_artifacts(perfect=True)
    _write_eval_crops(tmp_path, identifications)
    report = minifig_eval.build_eval_report(
        manifest, labels, detections, identifications, stage=stage,
        crop_root=tmp_path)
    assert len(report["bars"]) == expected_bars
    assert report["status"] == "non_gating"
    assert report["release_gate"]["eligible"] is False
    assert all(bar["passed"] for bar in report["bars"])


def test_should_block_zero_denominators_instead_of_vacuously_passing():
    manifest = _phase_j_manifest()
    labels = minifig_eval.validate_labels(_phase_j_labels(complete=False), manifest)
    detections, identifications = _phase_j_artifacts(perfect=True)
    report = minifig_eval.build_eval_report(
        manifest, labels, detections, identifications, stage="all")
    assert report["status"] == "blocked"
    assert report["label_coverage"] == {
        "labeled_listings": 0,
        "manifest_listings": 2,
        "hard_case_labels": 0,
        "complete": False,
    }
    assert all(bar["value"] is None and not bar["passed"] for bar in report["bars"])


def test_should_write_queue_and_blocked_report_at_the_human_label_gate(tmp_path):
    manifest_path, labels_path, workspace = _write_eval_inputs(
        tmp_path, labels=_phase_j_labels(complete=False), perfect=True)
    output = tmp_path / "report.json"
    exit_code = minifig_eval.evaluate_files(
        manifest_path, labels_path, workspace, output, stage="all")
    assert exit_code != 0
    report = json.loads(output.read_text())
    queue = json.loads((workspace / "labeling-queue.json").read_text())
    assert report["status"] == "blocked"
    assert report["reason"] == "human labels are incomplete"
    assert queue["summary"]["pending_listing_count"] == 2
    assert list(tmp_path.glob(".report.json.*.tmp")) == []
    assert list(workspace.glob(".labeling-queue.json.*.tmp")) == []


def test_should_write_failed_threshold_report_but_no_report_for_malformed_input(tmp_path):
    manifest_path, labels_path, workspace = _write_eval_inputs(tmp_path)
    output = tmp_path / "report.json"
    exit_code = minifig_eval.evaluate_files(
        manifest_path, labels_path, workspace, output, stage="all")
    assert exit_code != 0
    assert json.loads(output.read_text())["status"] == "failed"

    output.unlink()
    malformed = json.loads(labels_path.read_text())
    malformed["decisions"][0]["listing_key"] = "unknown|listing"
    labels_path.write_text(json.dumps(malformed))
    with pytest.raises(minifig_eval.EvalDataError, match="unknown manifest listing_key"):
        minifig_eval.evaluate_files(
            manifest_path, labels_path, workspace, output, stage="all")
    assert not output.exists()


def test_should_reject_invalid_eval_stage():
    manifest = _phase_j_manifest()
    labels = minifig_eval.validate_labels(_phase_j_labels(), manifest)
    detections, identifications = _phase_j_artifacts(perfect=True)
    with pytest.raises(minifig_eval.EvalDataError, match="stage"):
        minifig_eval.build_eval_report(
            manifest, labels, detections, identifications, stage="bogus")


@pytest.mark.parametrize(
    "protected_name",
    ("manifest", "labels", "detections", "identifications", "queue"),
)
def test_should_never_overwrite_eval_inputs_or_labeling_queue(
    tmp_path,
    protected_name,
):
    manifest_path, labels_path, workspace = _write_eval_inputs(
        tmp_path, labels=_phase_j_labels(complete=False), perfect=True)
    paths = {
        "manifest": manifest_path,
        "labels": labels_path,
        "detections": workspace / "detections.json",
        "identifications": workspace / "identifications.json",
        "queue": workspace / "labeling-queue.json",
    }
    output = paths[protected_name]
    if protected_name == "queue":
        output.write_text('{"sentinel": true}\n')
    before = output.read_bytes()

    with pytest.raises(minifig_eval.EvalDataError, match="output must be different"):
        minifig_eval.evaluate_files(
            manifest_path, labels_path, workspace, output, stage="all")

    assert output.read_bytes() == before


def test_should_isolate_selected_stage_from_unrelated_artifact_contracts(tmp_path):
    manifest = _phase_j_manifest()
    labels = minifig_eval.validate_labels(_phase_j_labels(), manifest)
    detections, identifications = _phase_j_artifacts(perfect=True)
    _write_eval_crops(tmp_path, identifications)

    detect_report = minifig_eval.build_eval_report(
        manifest,
        labels,
        detections,
        {"kind": "not-an-identification-artifact"},
        stage="detect",
    )
    assert detect_report["status"] == "non_gating"

    identify_report = minifig_eval.build_eval_report(
        manifest,
        labels,
        {"kind": "not-a-detection-artifact"},
        identifications,
        stage="identify",
        crop_root=tmp_path,
    )
    assert identify_report["status"] == "non_gating"


def _canonical_sha256(value):
    return minifig_eval.canonical_sha256(value)


def _lineage_bound_artifacts(*, perfect=True):
    manifest = _phase_j_manifest()
    detections, identifications = _phase_j_artifacts(perfect=perfect)
    return manifest, detections, identifications


def _approval(manifest, labels):
    return {
        "version": 1,
        "kind": "minifig_eval_human_approval",
        "approver": "Adam Bertram",
        "decision": "approved",
        "approved_at": "2026-08-25T13:00:00Z",
        "manifest_sha256": _canonical_sha256(manifest),
        "labels_sha256": _canonical_sha256(labels),
    }


def _benchmark_host_report(host, release_manifest):
    benchmark_manifest = minifig_eval._detector_benchmark_manifest(release_manifest)
    expected_assets = {row["asset"] for row in benchmark_manifest["listings"]}
    candidate = _candidate(
        name="grounding-dino-tiny",
        model="IDEA-Research/grounding-dino-tiny",
        version="a2bb814dd30d776dcf7e30523b00659f4f141c71",
    )
    candidate["weights_sha256"] = (
        "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3")
    candidate["dependency_versions"] = {
        "pillow": "12.3.0", "torch": "2.13.0", "transformers": "5.15.1"}
    candidate["images"] = [
        row for row in candidate["images"] if row["asset"] in expected_assets
    ]
    return minifig_eval.build_benchmark_report(
        benchmark_manifest,
        [candidate],
        _environment(host),
        useful_recall=0.5,
    )


def _release_model_contract(identifier_contract):
    return {
        "detector": {
            "name": "grounding-dino-tiny",
            "contract_version": "v1",
            "model": "IDEA-Research/grounding-dino-tiny",
            "model_revision": "a2bb814dd30d776dcf7e30523b00659f4f141c71",
            "weights_sha256": (
                "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3"),
        },
        "identifier": identifier_contract,
    }


def test_should_never_release_pass_a_tiny_fixture_or_wrong_canonical_count(tmp_path):
    manifest, detections, identifications = _lineage_bound_artifacts()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)
    _write_eval_crops(tmp_path, identifications)
    report = minifig_eval.build_eval_report(
        manifest,
        labels,
        detections,
        identifications,
        stage="all",
        crop_root=tmp_path,
    )
    assert report["status"] == "non_gating"
    assert report["release_gate"] == {
        "eligible": False,
        "canonical_dataset_id": "minifig-eval-33-real-listings-v1",
        "required_listing_count": 33,
        "reason": "dataset is an explicitly non-gating fixture",
    }

    wrong_count = copy.deepcopy(manifest)
    wrong_count["dataset_id"] = "minifig-eval-33-real-listings-v1"
    labels["dataset_id"] = wrong_count["dataset_id"]
    labels["manifest_sha256"] = _canonical_sha256(wrong_count)
    detections["manifest_sha256"] = labels["manifest_sha256"]
    identifications["manifest_sha256"] = labels["manifest_sha256"]
    report = minifig_eval.build_eval_report(
        wrong_count, labels, detections, identifications, stage="all")
    assert report["status"] == "blocked"
    assert "exactly 33" in report["release_gate"]["reason"]


def test_should_require_out_of_band_approval_bound_to_exact_labels_digest():
    manifest = _phase_j_manifest()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)
    approval = _approval(manifest, labels)

    verified = minifig_eval.validate_human_approval(
        approval, manifest=manifest, labels=labels)
    assert verified["labels_sha256"] == _canonical_sha256(labels)

    changed = copy.deepcopy(labels)
    changed["decisions"][0]["reviewed_at"] = "2026-08-25T14:00:00Z"
    with pytest.raises(minifig_eval.EvalDataError, match="labels_sha256"):
        minifig_eval.validate_human_approval(
            approval, manifest=manifest, labels=changed)
    assert not hasattr(minifig_eval, "create_human_approval")
    assert not hasattr(minifig_eval, "mint_human_approval")


def test_should_bind_artifacts_to_manifest_photo_hashes_and_detection_lineage():
    manifest, detections, identifications = _lineage_bound_artifacts()
    minifig_eval.validate_eval_lineage(
        manifest, detections=detections, identifications=identifications)

    wrong_manifest = copy.deepcopy(detections)
    wrong_manifest["manifest_sha256"] = "0" * 64
    with pytest.raises(minifig_eval.EvalDataError, match="manifest_sha256"):
        minifig_eval.validate_eval_lineage(
            manifest, detections=wrong_manifest, identifications=None)

    wrong_photo = copy.deepcopy(detections)
    wrong_photo["listings"][0]["photos"][0]["source_photo_sha256"] = "0" * 64
    with pytest.raises(minifig_eval.EvalDataError, match="photo.*sha256"):
        minifig_eval.validate_eval_lineage(
            manifest, detections=wrong_photo, identifications=None)

    wrong_upstream = copy.deepcopy(identifications)
    wrong_upstream["detection_artifact_sha256"] = "0" * 64
    with pytest.raises(minifig_eval.EvalDataError, match="detection_artifact_sha256"):
        minifig_eval.validate_eval_lineage(
            manifest, detections=detections, identifications=wrong_upstream)

    wrong_detection = copy.deepcopy(identifications)
    wrong_detection["listings"][0]["groups"][0]["detections"][0]["crop_id"] = "other"
    with pytest.raises(minifig_eval.EvalDataError, match="detection lineage"):
        minifig_eval.validate_eval_lineage(
            manifest, detections=detections, identifications=wrong_detection)


def test_should_count_obscure_unknown_only_with_safe_matching_content_crop(tmp_path):
    manifest, detections, identifications = _lineage_bound_artifacts()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)
    group = identifications["listings"][0]["groups"][1]
    crop_ref = group["representative_crop_ref"]
    crop = tmp_path / crop_ref
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(crop_ref.encode())

    report = minifig_eval.build_eval_report(
        manifest,
        labels,
        detections,
        identifications,
        stage="identify",
        crop_root=tmp_path,
    )
    assert report["metrics"]["obscure_unknown_with_crop"]["routed"] == 1

    crop.write_bytes(b"tampered")
    report = minifig_eval.build_eval_report(
        manifest,
        labels,
        detections,
        identifications,
        stage="identify",
        crop_root=tmp_path,
    )
    assert report["metrics"]["obscure_unknown_with_crop"]["routed"] == 0
    assert any("crop sha256" in row["reason"] for row in report["per_case_errors"])


def test_should_require_finite_two_host_evidence_bound_to_run_and_model_contract():
    manifest = _manifest()
    _, _, identifications = _lineage_bound_artifacts()
    model_contract = _release_model_contract(
        identifications["request_contract"])
    reports = [
        _benchmark_host_report("mac", manifest),
        _benchmark_host_report("adam-server", manifest),
    ]
    verified = minifig_eval.verify_eval_host_reports(
        reports,
        manifest=manifest,
        model_contract=model_contract,
    )
    assert verified["status"] == "verified"
    assert verified["hosts"] == ["adam-server", "mac"]
    expected_benchmark = minifig_eval._detector_benchmark_manifest(manifest)
    assert verified["benchmark_manifest_sha256"] == _canonical_sha256(
        expected_benchmark)

    nonfinite = copy.deepcopy(reports)
    nonfinite[1]["candidates"][0]["timings"]["warm_per_image_seconds"][0] = None
    with pytest.raises(minifig_eval.EvalDataError, match="non-finite"):
        minifig_eval.verify_eval_host_reports(
            nonfinite,
            manifest=manifest,
            model_contract=model_contract,
        )

    wrong_run = copy.deepcopy(reports)
    wrong_run[1]["dataset_run"] = "other-run"
    with pytest.raises(minifig_eval.EvalDataError, match="dataset contract"):
        minifig_eval.verify_eval_host_reports(
            wrong_run,
            manifest=manifest,
            model_contract=model_contract,
        )

    wrong_benchmark = copy.deepcopy(reports)
    wrong_benchmark[0]["manifest_sha256"] = wrong_benchmark[1]["manifest_sha256"] = "0" * 64
    with pytest.raises(minifig_eval.EvalDataError, match="benchmark manifest_sha256"):
        minifig_eval.verify_eval_host_reports(
            wrong_benchmark,
            manifest=manifest,
            model_contract=model_contract,
        )


def test_should_load_only_selected_stage_artifacts_and_skip_queue_nonblockingly(tmp_path):
    labels = _phase_j_labels()
    manifest_path, labels_path, workspace = _write_eval_inputs(
        tmp_path, labels=labels, perfect=True)
    (workspace / "identifications.json").unlink()
    output = tmp_path / "report.json"
    # The unrelated identification artifact and release evidence are absent.

    exit_code = minifig_eval.evaluate_files(
        manifest_path,
        labels_path,
        workspace,
        output,
        stage="detect",
        approval_path=tmp_path / "missing-approval.json",
        host_report_paths=(tmp_path / "missing-host.json",),
        crop_root=tmp_path / "missing-crops",
        write_queue=True,
    )
    assert exit_code == 0
    report = json.loads(output.read_text())
    assert report["status"] == "non_gating"
    assert report["stage"] == "detect"
    assert report["queue"] == {
        "status": "skipped",
        "reason": "queue requires both detect and identify artifacts",
    }
    assert not (workspace / "labeling-queue.json").exists()


def test_should_preserve_upstream_failure_and_continue_valid_siblings():
    manifest, detections, identifications = _lineage_bound_artifacts()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)
    failed = identifications["listings"][0]
    failed["status"] = "skipped"
    failed["reason"] = "provider unavailable for listing"
    failed["groups"] = []

    report = minifig_eval.build_eval_report(
        manifest,
        labels,
        None,
        identifications,
        stage="quantity",
    )
    assert report["metrics"]["exact_quantity_lot_rate"] == {
        "exact": 1,
        "labeled_lots": 1,
        "excluded": 1,
        "value": 1.0,
    }
    assert report["denominator_policy"] == (
        "exclude upstream non-success cases from metric denominators; "
        "release pass requires zero excluded cases")
    assert report["case_results"][0] == {
        "listing_key": "k-bid|one",
        "stage": "quantity",
        "status": "skipped",
        "reason": "provider unavailable for listing",
    }
    assert report["case_results"][1]["status"] == "success"


def test_should_require_actual_booleans_for_release_label_decisions():
    manifest = _phase_j_manifest()
    for field_path in (("hard_case",), ("groups", 0, "obscure")):
        labels = _phase_j_labels()
        target = labels["decisions"][0]
        for part in field_path[:-1]:
            target = target[part]
        target[field_path[-1]] = 1
        with pytest.raises(minifig_eval.EvalDataError, match="boolean"):
            minifig_eval.validate_labels(labels, manifest)


def test_should_reject_detection_photo_child_lineage_mismatch():
    manifest, detections, identifications = _lineage_bound_artifacts()
    detections["listings"][0]["photos"][0]["photo_relative_id"] = "other-photo"
    identifications["detection_artifact_sha256"] = _canonical_sha256(detections)

    with pytest.raises(minifig_eval.EvalDataError, match="photo_relative_id"):
        minifig_eval.validate_eval_lineage(
            manifest, detections=detections, identifications=identifications)


def test_should_require_exact_content_addressed_crop_basename(tmp_path):
    manifest, _, identifications = _lineage_bound_artifacts()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)
    group = identifications["listings"][0]["groups"][1]
    detection = group["detections"][0]
    crop_ref = f"prefix-{detection['crop_id']}.jpg"
    detection["crop_ref"] = crop_ref
    group["representative_crop_ref"] = crop_ref
    group["brickognize_contract"]["crop_sha256"] = hashlib.sha256(
        crop_ref.encode()).hexdigest()
    crop = tmp_path / crop_ref
    crop.write_bytes(crop_ref.encode())

    report = minifig_eval.build_eval_report(
        manifest,
        labels,
        None,
        identifications,
        stage="identify",
        crop_root=tmp_path,
    )

    assert report["metrics"]["obscure_unknown_with_crop"]["routed"] == 0
    assert any("content-addressed" in row["reason"]
               for row in report["per_case_errors"])


def test_should_not_implicitly_use_workspace_as_the_crop_root(tmp_path):
    manifest_path, labels_path, workspace = _write_eval_inputs(
        tmp_path, perfect=True)
    identifications = json.loads(
        (workspace / "identifications.json").read_text())
    _write_eval_crops(workspace, identifications)
    output = tmp_path / "report.json"

    exit_code = minifig_eval.evaluate_files(
        manifest_path,
        labels_path,
        workspace,
        output,
        stage="identify",
        crop_root=None,
        write_queue=False,
    )

    assert exit_code != 0
    report = json.loads(output.read_text())
    assert report["metrics"]["obscure_unknown_with_crop"]["routed"] == 0
    assert any("crop root was not configured" in row["reason"]
               for row in report["per_case_errors"])


def test_should_bind_queue_and_report_to_exact_artifact_digests(tmp_path):
    manifest, detections, identifications = _lineage_bound_artifacts()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)
    queue = minifig_eval.build_labeling_queue(
        manifest, labels, detections, identifications)
    assert queue["detection_artifact_sha256"] == _canonical_sha256(detections)
    assert queue["identification_artifact_sha256"] == _canonical_sha256(
        identifications)

    _write_eval_crops(tmp_path, identifications)
    report = minifig_eval.build_eval_report(
        manifest,
        labels,
        detections,
        identifications,
        stage="all",
        crop_root=tmp_path,
    )
    assert report["artifact_sha256"] == {
        "detections": _canonical_sha256(detections),
        "identifications": _canonical_sha256(identifications),
    }


def test_should_reject_cross_host_benchmarks_from_different_manifest_content():
    manifest = _manifest()
    other_manifest = copy.deepcopy(manifest)
    other_manifest["listings"][0]["title"] = "Different immutable dataset content"
    mac = minifig_eval.build_benchmark_report(
        manifest, [_candidate()], _environment("mac"))
    server = minifig_eval.build_benchmark_report(
        other_manifest, [_candidate()], _environment("adam-server"))

    with pytest.raises(minifig_eval.BenchmarkError, match="dataset"):
        minifig_eval.verify_host_reports(
            [mac, server], required_hosts={"mac", "adam-server"})


def test_should_publish_the_exact_detector_model_contract():
    manifest, detections, identifications = _lineage_bound_artifacts()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)

    report = minifig_eval.build_eval_report(
        manifest, labels, detections, identifications, stage="all")

    assert report["model_contract"]["detector"] == {
        "name": "grounding-dino-tiny",
        "contract_version": "v1",
        "model": "IDEA-Research/grounding-dino-tiny",
        "model_revision": "a2bb814dd30d776dcf7e30523b00659f4f141c71",
        "weights_sha256": (
            "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3"),
    }


def test_should_preserve_group_failure_status_and_reason_per_case(tmp_path):
    manifest, _, identifications = _lineage_bound_artifacts()
    labels = _phase_j_labels()
    labels["manifest_sha256"] = _canonical_sha256(manifest)
    group = identifications["listings"][0]["groups"][0]
    group["status"] = "skipped"
    group["reason"] = "provider unavailable for group"
    _write_eval_crops(tmp_path, identifications)

    identify_report = minifig_eval.build_eval_report(
        manifest,
        labels,
        None,
        identifications,
        stage="identify",
        crop_root=tmp_path,
    )
    identify_case = identify_report["case_results"][0]
    assert identify_case["status"] == "partial"
    assert identify_case["reason"] == "provider unavailable for group"
    assert identify_report["case_results"][1]["status"] == "success"

    quantity_report = minifig_eval.build_eval_report(
        manifest, labels, None, identifications, stage="quantity")
    quantity_case = quantity_report["case_results"][0]
    assert quantity_case["status"] == "partial"
    assert "provider unavailable for group" in quantity_case["reason"]
    assert quantity_report["case_results"][1]["status"] == "success"


def test_should_require_ten_through_fifteen_human_hard_decisions_for_release():
    manifest = _phase_j_manifest()
    manifest["dataset_id"] = "minifig-eval-33-real-listings-v1"
    template_listing = manifest["listings"][0]
    manifest["listings"] = [
        {**copy.deepcopy(template_listing), "listing_key": f"fixture|{index}"}
        for index in range(33)
    ]
    template_decision = _phase_j_labels()["decisions"][0]

    for hard_count, expected_eligible in ((9, False), (10, True), (15, True), (16, False)):
        labels = {
            "decisions": [
                {
                    **copy.deepcopy(template_decision),
                    "listing_key": f"fixture|{index}",
                    "hard_case": index < hard_count,
                }
                for index in range(33)
            ],
        }
        gate = minifig_eval._release_gate(manifest, labels)
        assert gate["eligible"] is expected_eligible
        if not expected_eligible:
            assert "10-15 hard cases" in gate["reason"]
