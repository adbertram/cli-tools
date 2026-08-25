from __future__ import annotations

import copy
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
        boxes = (listing["expected_boxes"] if recall_boxes is None
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
    assert len(manifest["listings"]) == 3
    for row in manifest["listings"]:
        assert row["listing_key"]
        assert row["source"]
        assert row["provenance"]["kind"]
        assert row["provenance"]["source_url"].startswith("https://")
        assert row["consent"] == {
            "basis": "public-marketplace-evaluation", "recorded": True}
        assert len(row["photo_sha256"]) == 64
        assert not Path(row["asset"]).is_absolute()
        assert len(row["expected_boxes"]) == len(row["expected_quantities"])
        assert isinstance(row["expected_identities"], list)
        assert isinstance(row["hard_case_tags"], list)


def test_should_load_version_one_adam_label_schema():
    labels = minifig_eval.load_labels(str(FIXTURE / "labels.json"))
    assert labels == {
        "version": 1,
        "manifest_version": 1,
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
    assert len(statuses) == 3
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
    assert [row["expected"] for row in cand["recall"]["per_image"]] == [3, 3, 5]


def test_should_aggregate_load_and_warm_per_image_latency_separately():
    report = minifig_eval.build_benchmark_report(
        _manifest(), [_candidate(latency=.25)], _environment())
    timings = report["candidates"][0]["timings"]
    assert timings == {
        "load_seconds": 1.25,
        "warm_per_image_seconds": [.25, .25, .25],
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
