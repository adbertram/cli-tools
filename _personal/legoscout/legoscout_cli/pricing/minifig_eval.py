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

from . import minifig_detector
from .minifig_detector import iou

DATASET_VERSION = 1
DEFAULT_USEFUL_RECALL = 0.50
RECALL_IOU_THRESHOLD = 0.50
EVAL_STAGES = ("all", "detect", "identify", "quantity")
EVAL_BARS = {
    "detection_recall": {"operator": ">=", "threshold": 0.90},
    "verified_id_precision": {"operator": ">=", "threshold": 0.85},
    "wrong_id_escape_rate": {"operator": "<", "threshold": 0.05},
    "exact_quantity_lot_rate": {"operator": ">=", "threshold": 0.90},
    "obscure_unknown_with_crop": {"operator": "==", "threshold": 1.0},
}
STAGE_METRICS = {
    "all": tuple(EVAL_BARS),
    "detect": ("detection_recall",),
    "identify": (
        "verified_id_precision",
        "wrong_id_escape_rate",
        "obscure_unknown_with_crop",
    ),
    "quantity": ("exact_quantity_lot_rate",),
}


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
    _required_string(manifest, "dataset_id", "manifest")
    if manifest.get("asset_root") != "workspace":
        raise EvalDataError("manifest.asset_root must be workspace")
    if manifest.get("assets_disposable") is not True:
        raise EvalDataError("manifest.assets_disposable must be true")
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
        _required_string(listing, "title", owner)
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
                or not all(isinstance(item, int) and not isinstance(item, bool)
                           and item > 0 for item in size)):
            raise EvalDataError(f"{owner}.image_size must be [width, height]")
        tags = listing.get("hard_case_tags")
        if not isinstance(tags, list) or not all(
                isinstance(tag, str) and tag for tag in tags):
            raise EvalDataError(f"{owner}.hard_case_tags must be strings")

        # Phase C detector seeds may retain human-reviewed boxes in the manifest
        # for benchmark reproducibility. Phase J labels belong in labels.json;
        # therefore these fields are optional and never prefilled from proposals.
        if "expected_boxes" in listing:
            boxes = listing["expected_boxes"]
            if not isinstance(boxes, list):
                raise EvalDataError(f"{owner}.expected_boxes must be a list")
            for box_index, box in enumerate(boxes):
                _validate_box(box, f"{owner}.expected_boxes[{box_index}]")
            identities = listing.get("expected_identities")
            quantities = listing.get("expected_quantities")
            if not isinstance(identities, list):
                raise EvalDataError(f"{owner}.expected_identities must be a list")
            if (not isinstance(quantities, list)
                    or len(quantities) != len(boxes)
                    or not all(isinstance(value, int) and not isinstance(value, bool)
                               and value > 0 for value in quantities)):
                raise EvalDataError(
                    f"{owner}.expected_quantities must match boxes with positive integers")
    return manifest


def validate_labels(
    labels: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate Adam-owned labels against one exact manifest identity."""
    if not isinstance(labels, dict):
        raise EvalDataError("labels must be an object")
    if labels.get("version") != DATASET_VERSION:
        raise EvalDataError(f"labels must use version {DATASET_VERSION}")
    if labels.get("manifest_version") != manifest.get("version"):
        raise EvalDataError(
            f"labels.manifest_version must match manifest version {manifest.get('version')}")
    if labels.get("dataset_id") != manifest.get("dataset_id"):
        raise EvalDataError("labels.dataset_id must match manifest.dataset_id")
    labels_manifest_digest = labels.get("manifest_sha256")
    if (
        manifest.get("dataset_id") == CANONICAL_DATASET_ID
        or labels_manifest_digest is not None
    ) and labels_manifest_digest != canonical_sha256(manifest):
        raise EvalDataError("labels.manifest_sha256 must match manifest digest")
    if labels.get("labeler") != "Adam Bertram":
        raise EvalDataError("labels.labeler must be Adam Bertram")
    decisions = labels.get("decisions")
    if not isinstance(decisions, list):
        raise EvalDataError("labels.decisions must be a list")

    manifest_keys = {
        row["listing_key"] for row in manifest.get("listings", [])
        if isinstance(row, dict) and isinstance(row.get("listing_key"), str)
    }
    seen_keys: set[str] = set()
    normalized = dict(labels)
    normalized_decisions: list[dict[str, Any]] = []
    for index, decision in enumerate(decisions):
        owner = f"labels.decisions[{index}]"
        if not isinstance(decision, dict):
            raise EvalDataError(f"{owner} must be an object")
        expected_keys = {
            "listing_key", "expected_boxes", "expected_quantity", "groups",
            "hard_case", "reviewed_at",
        }
        actual_keys = set(decision)
        if actual_keys != expected_keys:
            raise EvalDataError(
                f"{owner} must contain exact keys {sorted(expected_keys)}; "
                f"missing={sorted(expected_keys - actual_keys)}; "
                f"extra={sorted(actual_keys - expected_keys)}")
        key = _required_string(decision, "listing_key", owner)
        if key in seen_keys:
            raise EvalDataError(f"duplicate label listing_key: {key}")
        seen_keys.add(key)
        if key not in manifest_keys:
            raise EvalDataError(f"label references unknown manifest listing_key: {key}")
        boxes = decision["expected_boxes"]
        if not isinstance(boxes, list):
            raise EvalDataError(f"{owner}.expected_boxes must be a list")
        for box_index, box in enumerate(boxes):
            _validate_box(box, f"{owner}.expected_boxes[{box_index}]")
        quantity = decision["expected_quantity"]
        if (not isinstance(quantity, int) or isinstance(quantity, bool)
                or quantity < 0):
            raise EvalDataError(f"{owner}.expected_quantity must be a non-negative integer")
        if not isinstance(decision["hard_case"], bool):
            raise EvalDataError(f"{owner}.hard_case must be a boolean")
        _required_string(decision, "reviewed_at", owner)
        groups = decision["groups"]
        if not isinstance(groups, list):
            raise EvalDataError(f"{owner}.groups must be a list")
        group_ids: set[str] = set()
        for group_index, group in enumerate(groups):
            group_owner = f"{owner}.groups[{group_index}]"
            if not isinstance(group, dict):
                raise EvalDataError(f"{group_owner} must be an object")
            group_keys = {"match_group_id", "expected_fig_no", "obscure"}
            if set(group) != group_keys:
                raise EvalDataError(
                    f"{group_owner} must contain exact keys {sorted(group_keys)}")
            group_id = _required_string(group, "match_group_id", group_owner)
            if group_id in group_ids:
                raise EvalDataError(
                    f"duplicate label match_group_id for {key}: {group_id}")
            group_ids.add(group_id)
            fig_no = group["expected_fig_no"]
            if fig_no is not None and (
                    not isinstance(fig_no, str) or not fig_no.strip()):
                raise EvalDataError(
                    f"{group_owner}.expected_fig_no must be null or a non-empty string")
            if not isinstance(group["obscure"], bool):
                raise EvalDataError(f"{group_owner}.obscure must be a boolean")
        normalized_decisions.append(dict(decision))
    normalized["decisions"] = normalized_decisions
    return normalized


def load_labels(
    path: str,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load the version-one Adam decision file."""
    labels = _load_json_object(path, "labels")
    if manifest is None:
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
    return validate_labels(labels, manifest)


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
    try:
        _sha256(candidate["weights_sha256"], "candidate weights_sha256")
    except EvalDataError as exc:
        raise BenchmarkError(str(exc)) from exc
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
    expected_assets = {row["asset"] for row in manifest["listings"]}
    unexpected_assets = sorted(set(by_asset) - expected_assets)
    if unexpected_assets:
        raise BenchmarkError(
            "candidate included asset outside benchmark manifest: "
            + ", ".join(unexpected_assets))

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
            listing.get("expected_boxes", []), predicted_boxes)
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
        "dataset_id": manifest["dataset_id"],
        "manifest_sha256": canonical_sha256(manifest),
        "dataset_run": _manifest_run(manifest, required=False),
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
    required_host_set = set(required_hosts)
    missing = sorted(required_host_set - set(by_host))
    if missing:
        raise BenchmarkError(f"missing host report: {', '.join(missing)}")
    unexpected = sorted(set(by_host) - required_host_set)
    if unexpected:
        raise BenchmarkError(f"unexpected host report: {', '.join(unexpected)}")

    contracts: list[tuple[Any, ...]] = []
    dataset_contracts: list[tuple[Any, ...]] = []
    winner_name: str | None = None
    for host in sorted(required_hosts):
        report = by_host[host]
        manifest_digest = report.get("manifest_sha256")
        if (not isinstance(report.get("dataset_id"), str)
                or not isinstance(manifest_digest, str)):
            raise BenchmarkError(f"host {host} dataset contract missing")
        try:
            _sha256(manifest_digest, f"host {host} manifest_sha256")
        except EvalDataError as exc:
            raise BenchmarkError(str(exc)) from exc
        dataset_contracts.append((
            report.get("dataset_version"), report.get("dataset_id"),
            manifest_digest, report.get("dataset_run"),
        ))
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
        scalar_timing_fields = (
            "load_seconds", "warm_mean_seconds", "warm_max_seconds")
        if not isinstance(timings, dict):
            raise BenchmarkError(f"host {host} winner latency missing")
        for field in scalar_timing_fields:
            value = timings.get(field)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(float(value)) or float(value) < 0):
                raise BenchmarkError(
                    f"host {host} winner latency {field} missing or non-finite")
        warm_rows = timings.get("warm_per_image_seconds")
        if not isinstance(warm_rows, list) or not warm_rows:
            raise BenchmarkError(f"host {host} winner per-image latency missing")
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(float(value)) or float(value) < 0
            for value in warm_rows
        ):
            raise BenchmarkError(
                f"host {host} winner per-image latency missing or non-finite")
        contracts.append((
            winner.get("name"), winner.get("model"),
            winner.get("model_version"), winner.get("weights_sha256"),
            json.dumps(winner.get("dependency_versions"), sort_keys=True),
        ))
    if len(set(contracts)) != 1:
        raise BenchmarkError("host reports have mismatched model contract")
    if len(set(dataset_contracts)) != 1:
        raise BenchmarkError("host reports have mismatched dataset contract")
    return {
        "status": "success",
        "selected_winner": winner_name,
        "hosts": sorted(required_hosts),
        "contract": contracts[0],
    }


CANONICAL_DATASET_ID = "minifig-eval-33-real-listings-v1"
REQUIRED_RELEASE_LISTINGS = 33
REQUIRED_EVAL_HOSTS = frozenset({"mac", "adam-server"})
DENOMINATOR_POLICY = (
    "exclude upstream non-success cases from metric denominators; "
    "release pass requires zero excluded cases"
)


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Hash a JSON object independently of formatting and key order."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: object, owner: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise EvalDataError(f"{owner} must be a lowercase SHA-256")
    return value


def _manifest_run(
    manifest: Mapping[str, Any], *, required: bool = True,
) -> str | None:
    runs = {
        row.get("provenance", {}).get("run")
        for row in manifest.get("listings", [])
        if isinstance(row, dict) and isinstance(row.get("provenance"), dict)
    }
    if len(runs) == 1:
        run = next(iter(runs))
        if isinstance(run, str) and run:
            return run
    if not required and not runs:
        return None
    raise EvalDataError("manifest must bind every listing to one dataset run")


def validate_human_approval(
    approval: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    labels: Mapping[str, Any],
    labels_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate an externally-created Adam approval; never mint one here."""
    expected = {
        "version", "kind", "approver", "decision", "approved_at",
        "manifest_sha256", "labels_sha256",
    }
    if not isinstance(approval, dict) or set(approval) != expected:
        raise EvalDataError(
            f"human approval must contain exact keys {sorted(expected)}")
    if approval.get("version") != DATASET_VERSION:
        raise EvalDataError(f"human approval must use version {DATASET_VERSION}")
    if approval.get("kind") != "minifig_eval_human_approval":
        raise EvalDataError("human approval kind is invalid")
    if approval.get("approver") != "Adam Bertram":
        raise EvalDataError("human approval approver must be Adam Bertram")
    if approval.get("decision") != "approved":
        raise EvalDataError("human approval decision must be approved")
    _required_string(approval, "approved_at", "human approval")
    if approval.get("manifest_sha256") != canonical_sha256(manifest):
        raise EvalDataError("human approval manifest_sha256 does not match manifest")
    expected_labels = labels_sha256 or canonical_sha256(labels)
    if approval.get("labels_sha256") != expected_labels:
        raise EvalDataError("human approval labels_sha256 does not match exact labels")
    return dict(approval)


def _artifact_rows(
    payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    kind: str,
    require_manifest_digest: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        raise EvalDataError(f"{kind} artifact kind must be {kind}")
    if (
        require_manifest_digest
        and payload.get("manifest_sha256") != canonical_sha256(manifest)
    ):
        raise EvalDataError(f"{kind}.manifest_sha256 does not match manifest")
    rows = payload.get("listings")
    if not isinstance(rows, list):
        raise EvalDataError(f"{kind}.listings must be a list")
    actual_keys: list[str] = []
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EvalDataError(f"{kind}.listings[{index}] must be an object")
        key = _required_string(row, "listing_key", f"{kind}.listings[{index}]")
        if key in actual_keys:
            raise EvalDataError(f"duplicate {kind} listing_key: {key}")
        actual_keys.append(key)
        normalized.append(row)
    expected_keys = [row["listing_key"] for row in manifest["listings"]]
    if actual_keys != expected_keys:
        raise EvalDataError(
            f"{kind} ordered listing coverage mismatch: "
            f"expected={expected_keys}; actual={actual_keys}")
    return normalized


def _detection_boxes(row: Mapping[str, Any]) -> list[list[float]]:
    photos = row.get("photos")
    if not isinstance(photos, list):
        raise EvalDataError(
            f"detection listing {row.get('listing_key')} photos must be a list")
    boxes: list[list[float]] = []
    for photo_index, photo in enumerate(photos):
        if not isinstance(photo, dict):
            raise EvalDataError(
                f"detection photo {photo_index} must be an object")
        detections = photo.get("detections")
        if not isinstance(detections, list):
            raise EvalDataError(
                f"detection photo {photo_index} detections must be a list")
        for detection_index, detection in enumerate(detections):
            if not isinstance(detection, dict):
                raise EvalDataError(
                    f"detection {detection_index} must be an object")
            box = detection.get("box")
            _validate_box(box, f"detection photo {photo_index} box")
            if not isinstance(box, list):  # narrowed by _validate_box above
                raise EvalDataError("detection box must be a list")
            boxes.append([float(value) for value in box])
    return boxes


def _identification_groups(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = row.get("groups")
    if not isinstance(groups, list):
        raise EvalDataError(
            f"identification listing {row.get('listing_key')} groups must be a list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise EvalDataError(f"identification group {index} must be an object")
        group_id = _required_string(group, "match_group_id", f"group[{index}]")
        if group_id in seen:
            raise EvalDataError(f"duplicate identification match_group_id: {group_id}")
        seen.add(group_id)
        crop_ref = group.get("representative_crop_ref")
        if crop_ref is not None:
            _relative_asset(crop_ref, f"group[{index}].representative_crop_ref")
        candidates = group.get("brickognize_candidates")
        if not isinstance(candidates, list):
            raise EvalDataError(f"group[{index}].brickognize_candidates must be a list")
        detections = group.get("detections")
        if not isinstance(detections, list):
            raise EvalDataError(f"group[{index}].detections must be a list")
        normalized.append(group)
    return normalized


def _upstream_status(
    row: Mapping[str, Any], owner: str,
) -> tuple[str, str | None]:
    status = row.get("status")
    if status not in {"success", "partial", "skipped", "blocked"}:
        raise EvalDataError(f"{owner}.status is invalid")
    reason = row.get("reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise EvalDataError(f"{owner}.reason must be null or a non-empty string")
    if status != "success" and reason is None:
        raise EvalDataError(f"{owner}.reason is required for status {status}")
    return str(status), reason


def _lineage_detection(
    detection: Mapping[str, Any], expected_hash: str, owner: str,
    *, expected_photo_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(detection, dict):
        raise EvalDataError(f"{owner} must be an object")
    _validate_box(detection.get("box"), f"{owner}.box")
    _required_string(detection, "crop_id", owner)
    _relative_asset(detection.get("crop_ref"), owner)
    photo_id = _required_string(detection, "photo_relative_id", owner)
    if expected_photo_id is not None and photo_id != expected_photo_id:
        raise EvalDataError(
            f"{owner}.photo_relative_id does not match its parent photo")
    if detection.get("source_photo_sha256") != expected_hash:
        raise EvalDataError(f"{owner} photo sha256 does not match manifest")
    return dict(detection)


def validate_eval_lineage(
    manifest: Mapping[str, Any],
    *,
    detections: Mapping[str, Any] | None,
    identifications: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Bind selected artifacts to the manifest and their upstream detections."""
    if detections is None and identifications is None:
        raise EvalDataError("at least one evaluation artifact is required")
    strict_lineage = (
        manifest.get("dataset_id") == CANONICAL_DATASET_ID
        or (detections is not None and detections.get("manifest_sha256") is not None)
        or (
            identifications is not None
            and identifications.get("manifest_sha256") is not None
        )
    )
    if not strict_lineage:
        return {
            "manifest_sha256": canonical_sha256(manifest),
            "detections": (
                _artifact_rows(
                    detections, manifest, kind="minifig_detection",
                    require_manifest_digest=False)
                if detections is not None else []),
            "identifications": (
                _artifact_rows(
                    identifications, manifest, kind="minifig_identification",
                    require_manifest_digest=False)
                if identifications is not None else []),
        }
    manifest_by_key = {row["listing_key"]: row for row in manifest["listings"]}
    detection_rows: list[dict[str, Any]] = []
    identification_rows: list[dict[str, Any]] = []
    detected: dict[str, dict[str, Any]] = {}
    if detections is not None:
        detection_rows = _artifact_rows(
            detections, manifest, kind="minifig_detection")
        for listing_index, row in enumerate(detection_rows):
            _upstream_status(row, f"detection listing {listing_index}")
            photos = row.get("photos")
            if not isinstance(photos, list):
                raise EvalDataError("detection photos must be a list")
            expected_hash = manifest_by_key[row["listing_key"]]["photo_sha256"]
            seen_photo_ids: set[str] = set()
            for photo_index, photo in enumerate(photos):
                if not isinstance(photo, dict):
                    raise EvalDataError("detection photo must be an object")
                _upstream_status(photo, f"detection photo {photo_index}")
                photo_id = _required_string(
                    photo, "photo_relative_id", f"detection photo {photo_index}")
                if photo_id in seen_photo_ids:
                    raise EvalDataError(
                        f"duplicate detection photo_relative_id: {photo_id}")
                seen_photo_ids.add(photo_id)
                if photo.get("source_photo_sha256") != expected_hash:
                    raise EvalDataError("detection photo sha256 does not match manifest")
                rows = photo.get("detections")
                if not isinstance(rows, list):
                    raise EvalDataError("detection photo detections must be a list")
                for index, detection in enumerate(rows):
                    item = _lineage_detection(
                        detection, expected_hash, f"detection {index}",
                        expected_photo_id=photo_id)
                    if item["crop_id"] in detected:
                        raise EvalDataError(
                            f"duplicate detection crop_id: {item['crop_id']}")
                    detected[item["crop_id"]] = item
    if identifications is not None:
        identification_rows = _artifact_rows(
            identifications, manifest, kind="minifig_identification")
        _sha256(
            identifications.get("detection_artifact_sha256"),
            "minifig_identification.detection_artifact_sha256")
        embedded: dict[str, dict[str, Any]] = {}
        for listing_index, row in enumerate(identification_rows):
            _upstream_status(row, f"identification listing {listing_index}")
            expected_hash = manifest_by_key[row["listing_key"]]["photo_sha256"]
            for group in _identification_groups(row):
                _upstream_status(group, f"identification group {group['match_group_id']}")
                for detection in group["detections"]:
                    item = _lineage_detection(
                        detection, expected_hash,
                        f"identification group {group['match_group_id']} detection")
                    if item["crop_id"] in embedded:
                        raise EvalDataError(
                            f"duplicate identification crop_id: {item['crop_id']}")
                    embedded[item["crop_id"]] = item
        if detections is not None:
            if identifications.get("detection_artifact_sha256") != canonical_sha256(
                    detections):
                raise EvalDataError(
                    "minifig_identification.detection_artifact_sha256 does not match detections")
            if set(embedded) != set(detected):
                raise EvalDataError("identification detection lineage coverage mismatch")
            for crop_id, item in embedded.items():
                if canonical_sha256(item) != canonical_sha256(detected[crop_id]):
                    raise EvalDataError(
                        f"identification detection lineage mismatch for {crop_id}")
    return {
        "manifest_sha256": canonical_sha256(manifest),
        "detections": detection_rows,
        "identifications": identification_rows,
    }


def _proposal_status(group: Mapping[str, Any]) -> tuple[str, str | None]:
    verification = group.get("verification")
    if not isinstance(verification, dict):
        return "unverified", None
    status = verification.get("status")
    if status not in {"verified", "unknown", "unverifiable"}:
        raise EvalDataError(
            f"group {group.get('match_group_id')} verification.status is invalid")
    fig_no = group.get("fig_no")
    if status == "verified":
        if not isinstance(fig_no, str) or not fig_no:
            raise EvalDataError(
                f"verified group {group.get('match_group_id')} must have fig_no")
        return status, fig_no
    if fig_no is not None:
        raise EvalDataError(
            f"non-verified group {group.get('match_group_id')} must have null fig_no")
    return status, None


def _proposed_quantity(groups: Sequence[Mapping[str, Any]]) -> int:
    total = 0
    for group in groups:
        detections = group.get("detections")
        if not isinstance(detections, list):
            raise EvalDataError(
                f"group {group.get('match_group_id')} detections must be a list")
        by_photo: dict[str, int] = {}
        for detection in detections:
            if not isinstance(detection, dict):
                raise EvalDataError("group detection must be an object")
            photo_id = detection.get("photo_relative_id")
            if not isinstance(photo_id, str) or not photo_id:
                raise EvalDataError("group detection photo_relative_id must be a string")
            by_photo[photo_id] = by_photo.get(photo_id, 0) + 1
        total += max(by_photo.values(), default=0)
    return total


def build_labeling_queue(
    manifest: Mapping[str, Any],
    labels: Mapping[str, Any],
    detections: Mapping[str, Any],
    identifications: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an editable queue without turning model proposals into labels."""
    labels = validate_labels(labels, manifest)
    lineage = validate_eval_lineage(
        manifest, detections=detections, identifications=identifications)
    detection_rows = lineage["detections"]
    identification_rows = lineage["identifications"]
    decisions = {row["listing_key"]: row for row in labels["decisions"]}
    proposals: list[dict[str, Any]] = []
    proposal_group_count = 0
    for listing, detection_row, identification_row in zip(
            manifest["listings"], detection_rows, identification_rows):
        key = listing["listing_key"]
        decision = decisions.get(key)
        label_groups = {
            group["match_group_id"]: group
            for group in decision.get("groups", [])
        } if decision else {}
        groups: list[dict[str, Any]] = []
        for group in _identification_groups(identification_row):
            proposal_group_count += 1
            candidates = group["brickognize_candidates"]
            verification_status, verified_fig_no = _proposal_status(group)
            top_candidate = candidates[0] if candidates else None
            expected = label_groups.get(group["match_group_id"])
            groups.append({
                "match_group_id": group["match_group_id"],
                "representative_crop_ref": group.get("representative_crop_ref"),
                "candidates": candidates,
                "pipeline_status": verification_status,
                "proposed_fig_no": (
                    verified_fig_no
                    if verified_fig_no is not None
                    else top_candidate.get("id")
                    if isinstance(top_candidate, dict)
                    else None
                ),
                "expected_fig_no": (
                    expected["expected_fig_no"] if expected else None),
                "obscure": expected["obscure"] if expected else None,
            })
        proposals.append({
            "listing_key": key,
            "source": listing["source"],
            "title": listing["title"],
            "source_url": listing["provenance"]["source_url"],
            "asset": listing["asset"],
            "hard_case_tags": listing["hard_case_tags"],
            "proposed_boxes": _detection_boxes(detection_row),
            "proposed_quantity": _proposed_quantity(
                _identification_groups(identification_row)),
            "groups": groups,
            "expected_boxes": decision["expected_boxes"] if decision else None,
            "expected_quantity": decision["expected_quantity"] if decision else None,
            "hard_case": decision["hard_case"] if decision else None,
            "reviewed_at": decision["reviewed_at"] if decision else None,
        })
    return {
        "version": DATASET_VERSION,
        "manifest_version": manifest["version"],
        "manifest_sha256": canonical_sha256(manifest),
        "labels_sha256": canonical_sha256(labels),
        "detection_artifact_sha256": canonical_sha256(detections),
        "identification_artifact_sha256": canonical_sha256(identifications),
        "dataset_id": manifest["dataset_id"],
        "labeler": "Adam Bertram",
        "instructions": {
            "expected_boxes": "Replace null with normalized human boxes.",
            "expected_quantity": "Replace null with the exact physical lot quantity.",
            "expected_fig_no": (
                "For every group, record the human-correct BrickLink minifigure ID "
                "or null when identity is unknown."),
            "obscure": "Mark true only when the correct identity should route to unknown.",
            "hard_case": "Mark 10-15 cluttered/hard listings true in the 33-listing set.",
        },
        "summary": {
            "listing_count": len(proposals),
            "pending_listing_count": len(proposals) - len(decisions),
            "proposal_group_count": proposal_group_count,
            "hard_case_listing_count": sum(
                bool(row["hard_case_tags"]) for row in manifest["listings"]),
        },
        "proposals": proposals,
    }


def _metric(value_numerator: int, value_denominator: int) -> float | None:
    return value_numerator / value_denominator if value_denominator else None


def _bar(name: str, value: float | None) -> dict[str, Any]:
    contract = EVAL_BARS[name]
    operator = contract["operator"]
    threshold = float(contract["threshold"])
    if value is None:
        passed = False
    elif operator == ">=":
        passed = value >= threshold
    elif operator == "<":
        passed = value < threshold
    elif operator == "==":
        passed = value == threshold
    else:  # pragma: no cover - static contract above
        raise EvalDataError(f"unknown eval operator: {operator}")
    return {
        "name": name,
        "operator": operator,
        "threshold": threshold,
        "value": value,
        "passed": passed,
        "reason": None if passed else (
            "no human-labeled denominator" if value is None
            else f"value {value:.6f} does not satisfy {operator} {threshold:.6f}"),
    }


def _release_gate(
    manifest: Mapping[str, Any], labels: Mapping[str, Any],
) -> dict[str, Any]:
    base = {
        "eligible": False,
        "canonical_dataset_id": CANONICAL_DATASET_ID,
        "required_listing_count": REQUIRED_RELEASE_LISTINGS,
    }
    if manifest["dataset_id"] != CANONICAL_DATASET_ID:
        return {**base, "reason": "dataset is an explicitly non-gating fixture"}
    if len(manifest["listings"]) != REQUIRED_RELEASE_LISTINGS:
        return {
            **base,
            "reason": "canonical release dataset must contain exactly 33 listings",
        }
    hard_count = sum(row["hard_case"] for row in labels["decisions"])
    if not 10 <= hard_count <= 15:
        return {
            **base,
            "reason": "canonical release labels must contain 10-15 hard cases",
        }
    return {**base, "eligible": True, "reason": None}


def _finite_timings(
    value: object, fields: Sequence[str], owner: str,
) -> dict[str, float]:
    if not isinstance(value, dict):
        raise EvalDataError(f"{owner} timings must contain finite values")
    result: dict[str, float] = {}
    for field in fields:
        raw = value.get(field)
        if (not isinstance(raw, (int, float)) or isinstance(raw, bool)
                or not math.isfinite(float(raw)) or float(raw) < 0):
            raise EvalDataError(f"{owner}.{field} must be finite and non-negative")
        result[field] = float(raw)
    return result


def _detector_model_contract(value: object) -> dict[str, Any] | None:
    """Expand the shipped benchmark winner to its exact model identity."""
    if value is None:
        return None
    if not isinstance(value, dict) or not value:
        raise EvalDataError("detector contract must be a non-empty object")
    expected_base = {
        "name": "grounding-dino-tiny",
        "contract_version": minifig_detector.DETECTOR_CONTRACT_VERSION,
    }
    if value != expected_base:
        # Synthetic/non-release stage fixtures remain usable and non-gating.
        # The release host verifier below accepts only the expanded winner.
        return dict(value)
    return {
        **expected_base,
        "model": minifig_detector.GROUNDING_DINO_MODEL,
        "model_revision": minifig_detector.GROUNDING_DINO_REVISION,
        "weights_sha256": minifig_detector.GROUNDING_DINO_WEIGHTS_SHA256,
    }


def _eval_model_contract(
    detections: Mapping[str, Any] | None,
    identifications: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "detector": _detector_model_contract(
            detections.get("detector") if detections else None),
        "identifier": (
            identifications.get("request_contract") if identifications else None),
    }


def _detector_benchmark_manifest(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the immutable detector-seed dataset embedded in Phase J."""
    seed_rows = [
        dict(row) for row in manifest.get("listings", [])
        if isinstance(row, dict) and isinstance(row.get("expected_boxes"), list)
    ]
    if not seed_rows:
        raise EvalDataError("release manifest contains no detector benchmark seed rows")
    return {
        "version": manifest.get("version"),
        "dataset_id": f"{manifest.get('dataset_id')}-detector-seed",
        "asset_root": manifest.get("asset_root"),
        "assets_disposable": manifest.get("assets_disposable"),
        "listings": seed_rows,
    }


def verify_eval_host_reports(
    reports: Sequence[Mapping[str, Any]],
    *,
    manifest: Mapping[str, Any],
    model_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind two-host benchmark evidence to the Phase J release dataset/model."""
    detector_contract = model_contract.get("detector")
    expected_detector = _detector_model_contract({
        "name": "grounding-dino-tiny",
        "contract_version": minifig_detector.DETECTOR_CONTRACT_VERSION,
    })
    if expected_detector is None:  # pragma: no cover - static contract is non-null
        raise EvalDataError("release detector model contract is unavailable")
    if detector_contract != expected_detector:
        raise EvalDataError(
            "release model contract detector does not match the benchmark winner")
    identifier_contract = model_contract.get("identifier")
    if not isinstance(identifier_contract, dict) or not identifier_contract:
        raise EvalDataError(
            "release model contract requires non-empty identifier contract")

    benchmark_manifest = _detector_benchmark_manifest(manifest)
    expected_benchmark_digest = canonical_sha256(benchmark_manifest)
    expected_run = _manifest_run(manifest)
    try:
        verified = verify_host_reports(reports, REQUIRED_EVAL_HOSTS)
    except BenchmarkError as exc:
        raise EvalDataError(str(exc)) from exc

    for report in reports:
        environment = report.get("environment")
        host = environment.get("host") if isinstance(environment, dict) else "unknown"
        if report.get("dataset_version") != DATASET_VERSION:
            raise EvalDataError(f"host {host} dataset_version does not match")
        if report.get("dataset_id") != benchmark_manifest["dataset_id"]:
            raise EvalDataError(f"host {host} benchmark dataset_id does not match")
        if report.get("dataset_run") != expected_run:
            raise EvalDataError(f"host {host} benchmark dataset_run does not match")
        if report.get("manifest_sha256") != expected_benchmark_digest:
            raise EvalDataError(
                f"host {host} benchmark manifest_sha256 does not match")

    winner_contract = verified["contract"]
    expected_winner = (
        expected_detector["name"],
        expected_detector["model"],
        expected_detector["model_revision"],
        expected_detector["weights_sha256"],
    )
    if tuple(winner_contract[:4]) != expected_winner:
        raise EvalDataError("host benchmark winner does not match release detector model")
    return {
        "status": "verified",
        "hosts": verified["hosts"],
        "dataset_run": expected_run,
        "manifest_sha256": canonical_sha256(manifest),
        "benchmark_dataset_id": benchmark_manifest["dataset_id"],
        "benchmark_manifest_sha256": expected_benchmark_digest,
        "benchmark_model_contract": list(winner_contract),
        "model_contract": dict(model_contract),
    }


def _safe_content_crop(
    group: Mapping[str, Any], crop_root: str | Path | None,
) -> tuple[bool, str | None]:
    if crop_root is None:
        return False, "obscure figure crop root was not configured"
    crop_ref = group.get("representative_crop_ref")
    if not isinstance(crop_ref, str) or not crop_ref:
        return False, "obscure figure has no representative crop"
    try:
        _relative_asset(crop_ref, "representative crop")
    except EvalDataError as exc:
        return False, str(exc)
    root = Path(crop_root).expanduser().resolve(strict=False)
    candidate = (root / crop_ref).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return False, "obscure figure crop escapes configured root"
    if not candidate.is_file():
        return False, "obscure figure crop is missing under configured root"
    contract = group.get("brickognize_contract")
    expected = contract.get("crop_sha256") if isinstance(contract, dict) else None
    try:
        _sha256(expected, "brickognize_contract.crop_sha256")
    except EvalDataError as exc:
        return False, str(exc)
    detections = group.get("detections")
    representative = next((
        row for row in detections
        if isinstance(row, dict) and row.get("crop_ref") == crop_ref
    ), None) if isinstance(detections, list) else None
    crop_id = representative.get("crop_id") if isinstance(representative, dict) else None
    if not isinstance(crop_id, str) or crop_id != Path(crop_ref).stem:
        return False, "obscure figure crop is not content-addressed by crop_id"
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
        return False, "obscure figure crop sha256 does not match artifact"
    return True, None


def build_eval_report(
    manifest: Mapping[str, Any],
    labels: Mapping[str, Any],
    detections: Mapping[str, Any] | None,
    identifications: Mapping[str, Any] | None,
    *,
    stage: str,
    crop_root: str | Path | None = None,
    approval: Mapping[str, Any] | None = None,
    approval_labels_sha256: str | None = None,
    host_reports: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Score selected stages and reserve `passed` for the full release gate."""
    if stage not in EVAL_STAGES:
        raise EvalDataError(f"stage must be one of {', '.join(EVAL_STAGES)}")
    labels = validate_labels(labels, manifest)
    evaluate_detection = stage in {"all", "detect"}
    evaluate_identity = stage in {"all", "identify"}
    evaluate_quantity = stage in {"all", "quantity"}
    manifest_count = len(manifest["listings"])
    labeled_count = len(labels["decisions"])
    hard_case_count = sum(row["hard_case"] for row in labels["decisions"])
    release_gate = _release_gate(manifest, labels)
    model_contract = _eval_model_contract(detections, identifications)
    hard_complete = (
        manifest["dataset_id"] != CANONICAL_DATASET_ID
        or 10 <= hard_case_count <= 15)
    coverage_complete = labeled_count == manifest_count and hard_complete

    counts = {
        "matched": 0, "expected_boxes": 0, "correct_verified": 0,
        "verified": 0, "wrong_escapes": 0, "labeled_groups": 0,
        "exact_quantities": 0, "labeled_lots": 0,
        "obscure_routed": 0, "obscure_total": 0,
    }
    excluded = {
        "detection_recall": 0, "verified_id_precision": 0,
        "wrong_id_escape_rate": 0, "exact_quantity_lot_rate": 0,
        "obscure_unknown_with_crop": 0,
    }
    errors: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    detection_by_key: dict[str, dict[str, Any]] = {}
    identification_by_key: dict[str, dict[str, Any]] = {}

    if coverage_complete:
        lineage = validate_eval_lineage(
            manifest,
            detections=detections if evaluate_detection else None,
            identifications=(identifications if evaluate_identity or evaluate_quantity else None),
        )
        detection_by_key = {row["listing_key"]: row for row in lineage["detections"]}
        identification_by_key = {
            row["listing_key"]: row for row in lineage["identifications"]}

        for decision in labels["decisions"]:
            key = decision["listing_key"]
            if evaluate_detection:
                row = detection_by_key[key]
                upstream_status, upstream_reason = _upstream_status(row, f"detection {key}")
                if upstream_status != "success":
                    excluded["detection_recall"] += 1
                    cases.append({
                        "listing_key": key, "stage": "detect",
                        "status": upstream_status, "reason": upstream_reason})
                else:
                    matched, expected = _recall_counts(
                        decision["expected_boxes"], _detection_boxes(row))
                    counts["matched"] += matched
                    counts["expected_boxes"] += expected
                    reason = None
                    if matched != expected:
                        reason = f"matched {matched} of {expected} human boxes"
                        errors.append({
                            "listing_key": key, "stage": "detect", "reason": reason})
                    cases.append({
                        "listing_key": key, "stage": "detect",
                        "status": "success", "reason": reason})

            if evaluate_identity or evaluate_quantity:
                row = identification_by_key[key]
                upstream_status, upstream_reason = _upstream_status(
                    row, f"identification {key}")
                if upstream_status != "success":
                    group_count = max(1, len(decision["groups"]))
                    if evaluate_identity:
                        excluded["verified_id_precision"] += group_count
                        excluded["wrong_id_escape_rate"] += group_count
                        excluded["obscure_unknown_with_crop"] += sum(
                            group["obscure"] for group in decision["groups"])
                        cases.append({
                            "listing_key": key, "stage": "identify",
                            "status": upstream_status, "reason": upstream_reason})
                    if evaluate_quantity:
                        excluded["exact_quantity_lot_rate"] += 1
                        cases.append({
                            "listing_key": key, "stage": "quantity",
                            "status": upstream_status, "reason": upstream_reason})
                    continue

                groups = _identification_groups(row)
                groups_by_id = {group["match_group_id"]: group for group in groups}
                if evaluate_identity:
                    case_reason = None
                    case_status = "success"
                    for expected_group in decision["groups"]:
                        group_id = expected_group["match_group_id"]
                        group = groups_by_id.get(group_id)
                        if group is None:
                            excluded["verified_id_precision"] += 1
                            excluded["wrong_id_escape_rate"] += 1
                            if expected_group["obscure"]:
                                excluded["obscure_unknown_with_crop"] += 1
                            reason = f"identification group {group_id} is missing"
                            errors.append({
                                "listing_key": key, "stage": "identify",
                                "match_group_id": group_id, "reason": reason})
                            case_reason = reason
                            case_status = "partial"
                            continue
                        group_status, group_reason = _upstream_status(
                            group, f"identification group {group_id}")
                        if group_status != "success":
                            excluded["verified_id_precision"] += 1
                            excluded["wrong_id_escape_rate"] += 1
                            if expected_group["obscure"]:
                                excluded["obscure_unknown_with_crop"] += 1
                            errors.append({
                                "listing_key": key, "stage": "identify",
                                "match_group_id": group_id,
                                "status": group_status, "reason": group_reason})
                            case_reason = group_reason
                            case_status = "partial"
                            continue
                        proposal_status, proposed_fig_no = _proposal_status(group)
                        counts["labeled_groups"] += 1
                        if proposal_status == "verified":
                            counts["verified"] += 1
                            if proposed_fig_no == expected_group["expected_fig_no"]:
                                counts["correct_verified"] += 1
                            else:
                                counts["wrong_escapes"] += 1
                                reason = (
                                    f"wrong verified ID {proposed_fig_no!r}; human label is "
                                    f"{expected_group['expected_fig_no']!r}")
                                errors.append({
                                    "listing_key": key, "stage": "identify",
                                    "match_group_id": group_id, "reason": reason})
                                case_reason = reason
                        if expected_group["obscure"]:
                            counts["obscure_total"] += 1
                            if proposal_status in {"unknown", "unverifiable"}:
                                routed, crop_reason = _safe_content_crop(group, crop_root)
                            else:
                                routed = False
                                crop_reason = "obscure figure did not route to unknown"
                            if routed:
                                counts["obscure_routed"] += 1
                            else:
                                errors.append({
                                    "listing_key": key, "stage": "identify",
                                    "match_group_id": group_id,
                                    "reason": crop_reason})
                                case_reason = crop_reason
                    cases.append({
                        "listing_key": key, "stage": "identify",
                        "status": case_status, "reason": case_reason})

                if evaluate_quantity:
                    failed_groups = []
                    for group in groups:
                        group_status, group_reason = _upstream_status(
                            group,
                            f"identification group {group['match_group_id']}")
                        if group_status != "success":
                            failed_groups.append((
                                group["match_group_id"], group_status, group_reason))
                    if failed_groups:
                        excluded["exact_quantity_lot_rate"] += 1
                        failure_detail = "; ".join(
                            f"{group_id} ({group_status}): {group_reason}"
                            for group_id, group_status, group_reason in failed_groups)
                        failure_reason = (
                            "quantity excluded because upstream groups were non-success: "
                            + failure_detail)
                        errors.append({
                            "listing_key": key,
                            "stage": "quantity",
                            "status": "partial",
                            "reason": failure_reason,
                        })
                        cases.append({
                            "listing_key": key, "stage": "quantity", "status": "partial",
                            "reason": failure_reason})
                    else:
                        proposed = _proposed_quantity(groups)
                        counts["labeled_lots"] += 1
                        reason = None
                        if proposed == decision["expected_quantity"]:
                            counts["exact_quantities"] += 1
                        else:
                            reason = (
                                f"proposed quantity {proposed}; human quantity "
                                f"{decision['expected_quantity']}")
                            errors.append({
                                "listing_key": key, "stage": "quantity", "reason": reason})
                        cases.append({
                            "listing_key": key, "stage": "quantity",
                            "status": "success", "reason": reason})

    metrics = {
        "detection_recall": {
            "matched": counts["matched"], "expected": counts["expected_boxes"],
            "excluded": excluded["detection_recall"],
            "value": _metric(counts["matched"], counts["expected_boxes"])},
        "verified_id_precision": {
            "correct": counts["correct_verified"], "verified": counts["verified"],
            "excluded": excluded["verified_id_precision"],
            "value": _metric(counts["correct_verified"], counts["verified"])},
        "wrong_id_escape_rate": {
            "escaped": counts["wrong_escapes"], "labeled_groups": counts["labeled_groups"],
            "excluded": excluded["wrong_id_escape_rate"],
            "value": _metric(counts["wrong_escapes"], counts["labeled_groups"])},
        "exact_quantity_lot_rate": {
            "exact": counts["exact_quantities"], "labeled_lots": counts["labeled_lots"],
            "excluded": excluded["exact_quantity_lot_rate"],
            "value": _metric(counts["exact_quantities"], counts["labeled_lots"])},
        "obscure_unknown_with_crop": {
            "routed": counts["obscure_routed"], "obscure": counts["obscure_total"],
            "excluded": excluded["obscure_unknown_with_crop"],
            "value": _metric(counts["obscure_routed"], counts["obscure_total"])},
    }
    bars = [_bar(name, metrics[name]["value"]) for name in STAGE_METRICS[stage]]
    selected_excluded = sum(excluded[name] for name in STAGE_METRICS[stage])
    approval_result = {"status": "not_required", "reason": None}
    host_result = {"status": "not_required", "reason": None}

    if not coverage_complete:
        status, reason = "blocked", "human labels are incomplete"
    elif manifest["dataset_id"] == CANONICAL_DATASET_ID and not release_gate["eligible"]:
        status, reason = "blocked", release_gate["reason"]
    elif not all(bar["passed"] for bar in bars):
        status, reason = "failed", "one or more evaluation bars failed"
    elif selected_excluded:
        status, reason = "failed", "one or more upstream non-success cases were excluded"
    elif stage != "all" or not release_gate["eligible"]:
        status, reason = "non_gating", "selected stage or dataset is explicitly non-gating"
    elif approval is None:
        status = "blocked"
        reason = "out-of-band human approval artifact is required"
        approval_result = {"status": "missing", "reason": reason}
    else:
        try:
            approved = validate_human_approval(
                approval, manifest=manifest, labels=labels,
                labels_sha256=approval_labels_sha256)
        except EvalDataError as exc:
            status, reason = "blocked", str(exc)
            approval_result = {"status": "invalid", "reason": reason}
        else:
            approval_result = {
                "status": "approved", "reason": None,
                "approver": approved["approver"],
                "approved_at": approved["approved_at"],
                "labels_sha256": approved["labels_sha256"]}
            try:
                _finite_timings(
                    detections.get("timings") if detections else None,
                    ("total_seconds", "mean_per_photo_seconds"), "local detect")
                _finite_timings(
                    identifications.get("timings") if identifications else None,
                    ("total_seconds", "mean_per_crop_seconds"), "local identify")
                host_result = verify_eval_host_reports(
                    host_reports, manifest=manifest, model_contract=model_contract)
            except EvalDataError as exc:
                status, reason = "blocked", str(exc)
                host_result = {"status": "invalid", "reason": reason}
            else:
                status, reason = "passed", None

    return {
        "version": DATASET_VERSION,
        "dataset_id": manifest["dataset_id"],
        "dataset_run": _manifest_run(
            manifest, required=bool(release_gate["eligible"])),
        "manifest_sha256": canonical_sha256(manifest),
        "labels_sha256": approval_labels_sha256 or canonical_sha256(labels),
        "stage": stage, "status": status, "reason": reason,
        "release_gate": release_gate,
        "human_approval": approval_result,
        "host_verification": host_result,
        "label_coverage": {
            "labeled_listings": labeled_count, "manifest_listings": manifest_count,
            "hard_case_labels": hard_case_count, "complete": coverage_complete},
        "denominator_policy": DENOMINATOR_POLICY,
        "metrics": metrics, "bars": bars,
        "timings": {
            "detect": detections.get("timings") if detections else None,
            "identify": identifications.get("timings") if identifications else None},
        "model_contract": model_contract,
        "artifact_sha256": {
            "detections": canonical_sha256(detections) if detections else None,
            "identifications": (
                canonical_sha256(identifications) if identifications else None),
        },
        "case_results": cases,
        "per_case_errors": errors,
    }



def _validate_eval_paths(
    manifest_path: str | Path,
    labels_path: str | Path,
    workspace: str | Path,
    output_path: str | Path,
    approval_path: str | Path | None = None,
    host_report_paths: Sequence[str | Path] = (),
) -> Path:
    """Keep outputs distinct from every possible evaluation input."""
    root = Path(workspace)
    inputs = {
        "manifest": Path(manifest_path),
        "labels": Path(labels_path),
        "detections": root / "detections.json",
        "identifications": root / "identifications.json",
    }
    if approval_path is not None:
        inputs["approval"] = Path(approval_path)
    for index, report_path in enumerate(host_report_paths):
        inputs[f"host report {index}"] = Path(report_path)
    outputs = {
        "output": Path(output_path),
        "labeling queue": root / "labeling-queue.json",
    }
    resolved_inputs = {
        name: path.expanduser().resolve(strict=False) for name, path in inputs.items()}
    resolved_outputs = {
        name: path.expanduser().resolve(strict=False) for name, path in outputs.items()}
    if resolved_outputs["output"] == resolved_outputs["labeling queue"]:
        raise EvalDataError("output must be different from labeling queue")
    for output_name, output in resolved_outputs.items():
        for input_name, input_path in resolved_inputs.items():
            if output == input_path:
                raise EvalDataError(f"{output_name} must be different from {input_name}")
    return root


def evaluate_files(
    manifest_path: str | Path,
    labels_path: str | Path,
    workspace: str | Path,
    output_path: str | Path,
    *,
    stage: str,
    approval_path: str | Path | None = None,
    host_report_paths: Sequence[str | Path] = (),
    crop_root: str | Path | None = None,
    write_queue: bool = True,
) -> int:
    """Load only selected-stage artifacts and atomically publish one report."""
    if stage not in EVAL_STAGES:
        raise EvalDataError(f"stage must be one of {', '.join(EVAL_STAGES)}")
    root = _validate_eval_paths(
        manifest_path, labels_path, workspace, output_path,
        approval_path, host_report_paths)
    manifest = load_manifest(str(manifest_path))
    labels = load_labels(str(labels_path), manifest=manifest)
    labels_file_sha256 = hashlib.sha256(Path(labels_path).read_bytes()).hexdigest()
    approval = (
        _load_json_object(str(approval_path), "human approval")
        if approval_path is not None and stage == "all" else None)
    host_reports = ([
        _load_json_object(str(report_path), f"host report {index}")
        for index, report_path in enumerate(host_report_paths)
    ] if stage == "all" else [])

    complete = len(labels["decisions"]) == len(manifest["listings"])
    detections: dict[str, Any] | None = None
    identifications: dict[str, Any] | None = None
    if complete and stage in {"all", "detect"}:
        detections = _load_json_object(str(root / "detections.json"), "detections")
    if complete and stage in {"all", "identify", "quantity"}:
        identifications = _load_json_object(
            str(root / "identifications.json"), "identifications")

    report = build_eval_report(
        manifest, labels, detections, identifications,
        stage=stage,
        crop_root=crop_root,
        approval=approval,
        approval_labels_sha256=labels_file_sha256,
        host_reports=host_reports)

    if not write_queue:
        queue_status = {"status": "skipped", "reason": "queue generation disabled"}
    elif stage != "all":
        queue_status = {
            "status": "skipped",
            "reason": "queue requires both detect and identify artifacts"}
    else:
        try:
            queue_detections = detections or _load_json_object(
                str(root / "detections.json"), "detections")
            queue_identifications = identifications or _load_json_object(
                str(root / "identifications.json"), "identifications")
            queue = build_labeling_queue(
                manifest, labels, queue_detections, queue_identifications)
        except EvalDataError as exc:
            queue_status = {"status": "skipped", "reason": str(exc)}
        else:
            write_json_atomic(str(root / "labeling-queue.json"), queue)
            queue_status = {
                "status": "written", "reason": None,
                "manifest_sha256": canonical_sha256(manifest),
                "queue_sha256": canonical_sha256(queue),
                "detection_artifact_sha256": canonical_sha256(queue_detections),
                "identification_artifact_sha256": canonical_sha256(
                    queue_identifications),
            }
    report["queue"] = queue_status

    if complete and stage in {"all", "detect"}:
        assets = asset_statuses(manifest, str(root))
        report["assets"] = assets
        if any(row["status"] != "success" for row in assets):
            report["status"] = "blocked"
            report["reason"] = "one or more disposable assets are missing or changed"
    else:
        report["assets"] = {
            "status": "not_loaded",
            "reason": "assets are not required for this stage or incomplete labels"}
    write_json_atomic(str(output_path), report)
    return 0 if report["status"] in {"passed", "non_gating"} else 2



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
