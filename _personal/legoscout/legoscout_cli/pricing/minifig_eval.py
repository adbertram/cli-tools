"""Versioned minifigure evaluation data and detector benchmark reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from .minifig_detector import iou

DATASET_VERSION = 1
DEFAULT_USEFUL_RECALL = 0.50
RECALL_IOU_THRESHOLD = 0.50


class EvalDataError(ValueError):
    """Manifest or human-label data violates its versioned contract."""


class BenchmarkError(ValueError):
    """Benchmark input or cross-host output violates its contract."""


def _load_json_object(path: str, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalDataError(f"{kind} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise EvalDataError(f"{kind} must be an object")
    return value


def _required_object(row: Mapping[str, Any], field: str, owner: str) -> dict[str, Any]:
    value = row.get(field)
    if not isinstance(value, dict):
        raise EvalDataError(f"{owner}.{field} must be an object")
    return value


def _required_string(row: Mapping[str, Any], field: str, owner: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvalDataError(f"{owner}.{field} must be a non-empty string")
    return value


def _relative_asset(value: object, owner: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvalDataError(f"{owner}.asset must be a non-empty string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise EvalDataError(f"{owner}.asset must be a safe relative path")
    return value


def _validate_box(value: object, owner: str) -> None:
    if not isinstance(value, list) or len(value) != 4:
        raise EvalDataError(f"{owner} must contain four coordinates")
    coordinates: list[float] = []
    for coordinate in value:
        if (not isinstance(coordinate, (int, float))
                or isinstance(coordinate, bool)
                or not math.isfinite(float(coordinate))):
            raise EvalDataError(f"{owner} coordinates must be finite numbers")
        coordinates.append(float(coordinate))
    x1, y1, x2, y2 = coordinates
    if not all(0 <= coordinate <= 1 for coordinate in coordinates):
        raise EvalDataError(f"{owner} coordinates must be in 0..1")
    if x2 <= x1 or y2 <= y1:
        raise EvalDataError(f"{owner} must have positive area")


def load_manifest(path: str) -> dict[str, Any]:
    """Load and validate a version-one eval manifest."""
    manifest = _load_json_object(path, "manifest")
    if manifest.get("version") != DATASET_VERSION:
        raise EvalDataError(f"manifest must use version {DATASET_VERSION}")
    listings = manifest.get("listings")
    if not isinstance(listings, list):
        raise EvalDataError("manifest.listings must be a list")
    keys: set[str] = set()
    assets: set[str] = set()
    for index, listing in enumerate(listings):
        owner = f"manifest.listings[{index}]"
        if not isinstance(listing, dict):
            raise EvalDataError(f"{owner} must be an object")
        key = _required_string(listing, "listing_key", owner)
        if key in keys:
            raise EvalDataError(f"duplicate manifest listing_key: {key}")
        keys.add(key)
        _required_string(listing, "source", owner)
        provenance = _required_object(listing, "provenance", owner)
        _required_string(provenance, "kind", f"{owner}.provenance")
        source_url = _required_string(
            provenance, "source_url", f"{owner}.provenance")
        if not source_url.startswith("https://"):
            raise EvalDataError(f"{owner}.provenance.source_url must use https")
        consent = _required_object(listing, "consent", owner)
        _required_string(consent, "basis", f"{owner}.consent")
        if consent.get("recorded") is not True:
            raise EvalDataError(f"{owner}.consent.recorded must be true")
        asset = _relative_asset(listing.get("asset"), owner)
        if asset in assets:
            raise EvalDataError(f"duplicate manifest asset: {asset}")
        assets.add(asset)
        sha = _required_string(listing, "photo_sha256", owner)
        if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
            raise EvalDataError(f"{owner}.photo_sha256 must be lowercase SHA-256")
        size = listing.get("image_size")
        if (not isinstance(size, list) or len(size) != 2
                or not all(isinstance(item, int) and item > 0 for item in size)):
            raise EvalDataError(f"{owner}.image_size must be [width, height]")
        boxes = listing.get("expected_boxes")
        identities = listing.get("expected_identities")
        quantities = listing.get("expected_quantities")
        tags = listing.get("hard_case_tags")
        if not isinstance(boxes, list):
            raise EvalDataError(f"{owner}.expected_boxes must be a list")
        for box_index, box in enumerate(boxes):
            _validate_box(box, f"{owner}.expected_boxes[{box_index}]")
        if not isinstance(identities, list):
            raise EvalDataError(f"{owner}.expected_identities must be a list")
        if (not isinstance(quantities, list)
                or len(quantities) != len(boxes)
                or not all(isinstance(value, int) and value > 0
                           for value in quantities)):
            raise EvalDataError(
                f"{owner}.expected_quantities must match boxes with positive integers")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise EvalDataError(f"{owner}.hard_case_tags must be strings")
    return manifest


def load_labels(path: str) -> dict[str, Any]:
    """Load the version-one Adam decision file."""
    labels = _load_json_object(path, "labels")
    if labels.get("version") != DATASET_VERSION:
        raise EvalDataError(f"labels must use version {DATASET_VERSION}")
    if labels.get("manifest_version") != DATASET_VERSION:
        raise EvalDataError(
            f"labels.manifest_version must be {DATASET_VERSION}")
    if labels.get("labeler") != "Adam Bertram":
        raise EvalDataError("labels.labeler must be Adam Bertram")
    if not isinstance(labels.get("decisions"), list):
        raise EvalDataError("labels.decisions must be a list")
    return labels


def asset_statuses(
    manifest: Mapping[str, Any],
    workspace: str,
) -> list[dict[str, Any]]:
    """Report missing or changed disposable assets without aborting siblings."""
    root = Path(workspace)
    statuses: list[dict[str, Any]] = []
    listings = manifest.get("listings")
    if not isinstance(listings, list):
        raise EvalDataError("manifest.listings must be a list")
    for listing in listings:
        if not isinstance(listing, dict):
            raise EvalDataError("manifest listing must be an object")
        asset = _relative_asset(listing.get("asset"), "manifest listing")
        path = root / asset
        base = {"listing_key": listing.get("listing_key"), "asset": asset}
        if not path.is_file():
            statuses.append({
                **base, "status": "skipped", "reason": "asset is missing"})
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != listing.get("photo_sha256"):
            statuses.append({
                **base,
                "status": "skipped",
                "reason": "asset sha256 does not match manifest",
            })
            continue
        statuses.append({
            **base, "status": "success", "reason": None, "path": str(path)})
    return statuses


def _recall_counts(
    expected: Sequence[Sequence[float]],
    predicted: Sequence[Sequence[float]],
) -> tuple[int, int]:
    pairs: list[tuple[float, int, int]] = []
    for expected_index, expected_box in enumerate(expected):
        for predicted_index, predicted_box in enumerate(predicted):
            overlap = iou(expected_box, predicted_box)
            if overlap >= RECALL_IOU_THRESHOLD:
                pairs.append((-overlap, expected_index, predicted_index))
    used_expected: set[int] = set()
    used_predicted: set[int] = set()
    for _, expected_index, predicted_index in sorted(pairs):
        if expected_index in used_expected or predicted_index in used_predicted:
            continue
        used_expected.add(expected_index)
        used_predicted.add(predicted_index)
    return len(used_expected), len(expected)


def _finite_nonnegative(value: object, field: str) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(float(value)) or float(value) < 0):
        raise BenchmarkError(f"{field} must be a finite non-negative number")
    return float(value)


def _candidate_report(
    manifest: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    required = (
        "name", "model", "model_version", "weights_sha256",
        "dependency_versions", "load_seconds", "images",
    )
    for field in required:
        if field not in candidate:
            raise BenchmarkError(f"candidate missing {field}")
    for field in ("name", "model", "model_version", "weights_sha256"):
        if not isinstance(candidate[field], str) or not candidate[field]:
            raise BenchmarkError(f"candidate {field} must be a non-empty string")
    dependencies = candidate["dependency_versions"]
    if (not isinstance(dependencies, dict) or not dependencies
            or not all(isinstance(key, str) and isinstance(value, str)
                       for key, value in dependencies.items())):
        raise BenchmarkError("candidate dependency_versions must be a non-empty object")
    load_seconds = _finite_nonnegative(
        candidate["load_seconds"], "candidate load_seconds")
    images = candidate["images"]
    if not isinstance(images, list):
        raise BenchmarkError("candidate images must be a list")
    by_asset: dict[str, Mapping[str, Any]] = {}
    for row in images:
        if not isinstance(row, dict) or not isinstance(row.get("asset"), str):
            raise BenchmarkError("candidate image row must name an asset")
        if row["asset"] in by_asset:
            raise BenchmarkError(f"duplicate candidate asset: {row['asset']}")
        by_asset[row["asset"]] = row

    per_image: list[dict[str, Any]] = []
    latencies: list[float] = []
    total_matched = 0
    total_expected = 0
    for listing in manifest["listings"]:
        asset = listing["asset"]
        row = by_asset.get(asset)
        if row is None:
            raise BenchmarkError(f"candidate omitted asset: {asset}")
        detections = row.get("detections")
        if not isinstance(detections, list):
            raise BenchmarkError(f"candidate detections must be a list: {asset}")
        predicted_boxes: list[Sequence[float]] = []
        for detection in detections:
            if not isinstance(detection, dict):
                raise BenchmarkError(f"candidate detection must be an object: {asset}")
            try:
                _validate_box(detection.get("box"), f"candidate {asset} box")
            except EvalDataError as exc:
                raise BenchmarkError(str(exc)) from exc
            predicted_boxes.append(detection["box"])
        latency = _finite_nonnegative(
            row.get("latency_seconds"), f"candidate {asset} latency_seconds")
        latencies.append(latency)
        matched, expected_count = _recall_counts(
            listing["expected_boxes"], predicted_boxes)
        total_matched += matched
        total_expected += expected_count
        per_image.append({
            "asset": asset,
            "matched": matched,
            "expected": expected_count,
            "predicted": len(predicted_boxes),
            "value": matched / expected_count if expected_count else None,
        })
    recall = total_matched / total_expected if total_expected else None
    if recall is None:
        raise BenchmarkError("benchmark manifest has no expected boxes")
    return {
        "name": candidate["name"],
        "model": candidate["model"],
        "model_version": candidate["model_version"],
        "weights_sha256": candidate["weights_sha256"],
        "dependency_versions": dict(sorted(dependencies.items())),
        "recall": {
            "matched": total_matched,
            "expected": total_expected,
            "value": recall,
            "per_image": per_image,
        },
        "timings": {
            "load_seconds": load_seconds,
            "warm_per_image_seconds": latencies,
            "warm_mean_seconds": mean(latencies),
            "warm_max_seconds": max(latencies),
        },
    }


def build_benchmark_report(
    manifest: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    environment: Mapping[str, Any],
    useful_recall: float = DEFAULT_USEFUL_RECALL,
) -> dict[str, Any]:
    """Build a deterministic backend comparison and winner verdict."""
    environment_fields = (
        "host", "os", "architecture", "python_version", "cv2_version")
    for field in environment_fields:
        if field not in environment or environment[field] is None:
            raise BenchmarkError(f"environment missing {field}")
    if not isinstance(candidates, Sequence) or not candidates:
        raise BenchmarkError("benchmark requires at least one candidate")
    reports = [_candidate_report(manifest, candidate) for candidate in candidates]
    names = [row["name"] for row in reports]
    if len(names) != len(set(names)):
        raise BenchmarkError("duplicate candidate name")
    useful = [row for row in reports if row["recall"]["value"] >= useful_recall]
    useful.sort(key=lambda row: (
        -row["recall"]["value"],
        row["timings"]["warm_mean_seconds"],
        row["name"],
    ))
    winner = useful[0]["name"] if useful else None
    return {
        "dataset_version": DATASET_VERSION,
        "environment": {field: environment[field] for field in environment_fields},
        "useful_recall_threshold": useful_recall,
        "status": "success" if winner else "blocked",
        "reason": None if winner else "no candidate reached useful recall",
        "selected_winner": winner,
        "selection_order": [{
            "name": row["name"],
            "recall": row["recall"]["value"],
            "warm_mean_seconds": row["timings"]["warm_mean_seconds"],
        } for row in useful],
        "candidates": reports,
    }


def verify_host_reports(
    reports: Sequence[Mapping[str, Any]],
    required_hosts: Iterable[str],
) -> dict[str, Any]:
    """Reject incomplete or divergent Mac/server benchmark evidence."""
    by_host: dict[str, Mapping[str, Any]] = {}
    for report in reports:
        environment = report.get("environment")
        if not isinstance(environment, dict) or not isinstance(
                environment.get("host"), str):
            raise BenchmarkError("report missing environment host")
        host = environment["host"]
        if host in by_host:
            raise BenchmarkError(f"duplicate host report: {host}")
        by_host[host] = report
    missing = sorted(set(required_hosts) - set(by_host))
    if missing:
        raise BenchmarkError(f"missing host report: {', '.join(missing)}")

    contracts: list[tuple[Any, ...]] = []
    winner_name: str | None = None
    for host in sorted(required_hosts):
        report = by_host[host]
        selected = report.get("selected_winner")
        if report.get("status") != "success" or not isinstance(selected, str):
            raise BenchmarkError(f"host {host} has no selected winner")
        if winner_name is None:
            winner_name = selected
        elif selected != winner_name:
            raise BenchmarkError("host reports selected different winners")
        candidates = report.get("candidates")
        if not isinstance(candidates, list):
            raise BenchmarkError(f"host {host} candidates missing")
        winner = next((row for row in candidates
                       if isinstance(row, dict) and row.get("name") == selected), None)
        if winner is None:
            raise BenchmarkError(f"host {host} winner candidate missing")
        timings = winner.get("timings")
        if (not isinstance(timings, dict)
                or not isinstance(timings.get("warm_mean_seconds"), (int, float))
                or not math.isfinite(float(timings["warm_mean_seconds"]))):
            raise BenchmarkError(f"host {host} winner latency missing")
        contracts.append((
            winner.get("name"), winner.get("model"),
            winner.get("model_version"), winner.get("weights_sha256"),
            json.dumps(winner.get("dependency_versions"), sort_keys=True),
        ))
    if len(set(contracts)) != 1:
        raise BenchmarkError("host reports have mismatched model contract")
    return {
        "status": "success",
        "selected_winner": winner_name,
        "hosts": sorted(required_hosts),
        "contract": contracts[0],
    }


def write_json_atomic(path: str, value: Mapping[str, Any]) -> None:
    """Write deterministic JSON without exposing a partial report."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp",
        dir=destination.parent,
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, destination)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """Build one machine-validated detector report from raw candidates."""
    parser = argparse.ArgumentParser(prog="python -m legoscout_cli.pricing.minifig_eval")
    subcommands = parser.add_subparsers(dest="command", required=True)
    report_parser = subcommands.add_parser("report")
    report_parser.add_argument("--manifest", required=True)
    report_parser.add_argument("--environment", required=True)
    report_parser.add_argument("--candidate", action="append", required=True)
    report_parser.add_argument("--output", required=True)
    report_parser.add_argument(
        "--useful-recall", type=float, default=DEFAULT_USEFUL_RECALL)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    environment = _load_json_object(args.environment, "environment")
    candidates = [
        _load_json_object(candidate_path, "candidate")
        for candidate_path in args.candidate
    ]
    report = build_benchmark_report(
        manifest,
        candidates,
        environment,
        useful_recall=args.useful_recall,
    )
    write_json_atomic(args.output, report)
    return 0 if report["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
