"""Durable minifigure detection artifacts.

This module consumes only classifier-saved local photo paths. It never fetches
listing media. Later minifigure stages extend this module's artifact pipeline.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Sequence

from ..paths import BRICKOGNIZE_MINIFIG_CACHE
from ..ledger import minifig_analysis
from . import brickognize, minifig_detector, minifig_sales

DETECTION_ARTIFACT_VERSION = 1
DETECTION_ARTIFACT_KIND = "minifig_detection"
IDENTIFICATION_ARTIFACT_VERSION = 1
IDENTIFICATION_ARTIFACT_KIND = "minifig_identification"
GROUP_CONTRACT_VERSION = "minifig-group-v1"
SOURCE_MEMBER_CONTRACT_VERSION = "minifig-source-members-v1"
SOURCE_MEMBER_DIGEST_PREFIX = "figmembers-v1-"
DETECTION_INPUT_KEYS = frozenset({
    "listing_key",
    "saved_photo_paths",
    "observations",
})

DetectorFn = Callable[[str, Sequence[str]], list[dict[str, Any]]]
CropWriter = Callable[[str, dict[str, Any], str], str]
Predictor = Callable[..., list[dict[str, Any]]]
STAGE_STATUSES = frozenset({"success", "skipped", "blocked"})


class DetectionInputError(ValueError):
    """The classifier hand-off is invalid or unreadable."""


class DetectionBatchError(ValueError):
    """The detector violated its batch result contract."""


class DetectionOutputError(OSError):
    """The durable artifact could not be atomically written."""


class IdentificationArtifactError(ValueError):
    """A detection or provider artifact violates the identify contract."""


def _exact_keys(row: dict[str, Any], index: int) -> None:
    keys = set(row)
    if keys != DETECTION_INPUT_KEYS:
        missing = sorted(DETECTION_INPUT_KEYS - keys)
        extra = sorted(keys - DETECTION_INPUT_KEYS)
        raise DetectionInputError(
            f"listing {index} must contain exact keys "
            f"{sorted(DETECTION_INPUT_KEYS)}; missing={missing}; extra={extra}"
        )


def _validate_listing(row: object, index: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise DetectionInputError(f"listing {index} must be an object")
    _exact_keys(row, index)
    listing_key = row["listing_key"]
    if not isinstance(listing_key, str) or not listing_key.strip():
        raise DetectionInputError(
            f"listing {index} listing_key must be a non-empty string")
    paths = row["saved_photo_paths"]
    if not isinstance(paths, list):
        raise DetectionInputError(
            f"listing {index} saved_photo_paths must be an array")
    for path_index, value in enumerate(paths):
        if not isinstance(value, str) or not value:
            raise DetectionInputError(
                f"listing {index} saved_photo_paths[{path_index}] must be a "
                "non-empty string")
        if not Path(value).is_absolute():
            raise DetectionInputError(
                f"listing {index} saved_photo_paths[{path_index}] must be an "
                "absolute local path")
    if not isinstance(row["observations"], dict):
        raise DetectionInputError(
            f"listing {index} observations must be an object")
    return row


def load_detection_input(path: str | Path) -> list[dict[str, Any]]:
    """Read and strictly validate the classifier minifigure hand-off."""
    input_path = Path(path)
    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DetectionInputError(
            f"unable to read input {input_path}: {type(exc).__name__}: {exc}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DetectionInputError(
            f"invalid JSON in {input_path}: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}"
        ) from exc
    if not isinstance(payload, list):
        raise DetectionInputError("detection input must be a JSON array")

    listings = [_validate_listing(row, index)
                for index, row in enumerate(payload)]
    keys = [row["listing_key"] for row in listings]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise DetectionInputError(
            f"duplicate listing_key values: {', '.join(duplicates)}")
    return listings


def _photo_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _detector_record(
    raw: dict[str, Any],
    *,
    photo_sha256: str,
    photo_relative_id: str,
    detector_name: str,
    crop_ref: str,
) -> dict[str, Any]:
    crop_id = raw.get("crop_id")
    box = raw.get("box")
    confidence = raw.get("confidence")
    if not isinstance(crop_id, str) or not crop_id:
        raise DetectionBatchError("detection crop_id must be a non-empty string")
    if not isinstance(box, list) or len(box) != 4:
        raise DetectionBatchError("detection box must contain four coordinates")
    if (not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)):
        raise DetectionBatchError("detection confidence must be numeric")
    return {
        "crop_id": crop_id,
        "source_photo_sha256": photo_sha256,
        "photo_relative_id": photo_relative_id,
        "box": list(box),
        "detector_name": detector_name,
        "detector_version": minifig_detector.DETECTOR_CONTRACT_VERSION,
        "detector_confidence": float(confidence),
        "crop_ref": crop_ref,
    }


def _photo_result(
    path: str,
    raw: dict[str, Any],
    *,
    photo_relative_id: str,
    detector_name: str,
    crop_root: str | Path,
    crop_writer: CropWriter,
) -> dict[str, Any]:
    base = {
        "photo_relative_id": photo_relative_id,
        "source_photo_sha256": None,
        "status": "skipped",
        "reason": None,
        "detections": [],
    }
    if raw.get("status") != "success":
        reason = raw.get("reason")
        base["reason"] = reason if isinstance(reason, str) and reason else (
            "detector skipped photo without a reason")
        return base
    try:
        photo_sha256 = _photo_sha256(path)
        detections = raw.get("detections")
        if not isinstance(detections, list):
            raise DetectionBatchError("photo detections must be an array")
        persisted = []
        for detection in detections:
            if not isinstance(detection, dict):
                raise DetectionBatchError("detection must be an object")
            crop_ref = crop_writer(path, detection, str(crop_root))
            if not isinstance(crop_ref, str) or not crop_ref:
                raise DetectionBatchError(
                    "crop writer must return a non-empty relative ref")
            if Path(crop_ref).is_absolute():
                raise DetectionBatchError("crop_ref must be relative")
            persisted.append(_detector_record(
                detection,
                photo_sha256=photo_sha256,
                photo_relative_id=photo_relative_id,
                detector_name=detector_name,
                crop_ref=crop_ref,
            ))
    except Exception as exc:
        base["reason"] = f"crop persistence failed: {type(exc).__name__}: {exc}"
        return base
    base.update({
        "source_photo_sha256": photo_sha256,
        "status": "success",
        "reason": None,
        "detections": persisted,
    })
    return base


def _listing_status(photos: list[dict[str, Any]]) -> tuple[str, str | None]:
    if not photos:
        return "skipped", "no saved photo paths"
    skipped = sum(row["status"] == "skipped" for row in photos)
    if skipped == 0:
        return "success", None
    if skipped == len(photos):
        return "skipped", "all photos skipped"
    # The stage completed and retains the skipped-photo reason; `partial` is
    # not part of the locked success|skipped|blocked status vocabulary.
    return "success", f"{skipped} of {len(photos)} photos skipped"


def _summary(listings: list[dict[str, Any]]) -> dict[str, int]:
    photos = [photo for listing in listings for photo in listing["photos"]]
    return {
        "listing_count": len(listings),
        "success_count": sum(row["status"] == "success" for row in listings),
        "partial_count": 0,
        "skipped_count": sum(row["status"] == "skipped" for row in listings),
        "photo_count": len(photos),
        "photo_success_count": sum(
            row["status"] == "success" for row in photos),
        "photo_skipped_count": sum(
            row["status"] == "skipped" for row in photos),
        "detection_count": sum(
            len(row["detections"]) for row in photos),
    }


def detect_batch(
    listings: list[dict[str, Any]],
    *,
    detector_name: str,
    crop_root: str | Path,
    detector_fn: DetectorFn = minifig_detector.detect_many,
    crop_writer: CropWriter = minifig_detector.write_crop,
) -> dict[str, Any]:
    """Detect all saved photos once and build a path-free durable artifact."""
    started_at = time.perf_counter()
    if detector_name not in minifig_detector.DETECTOR_LOADERS:
        raise DetectionInputError(f"unknown detector: {detector_name}")
    flat_paths = [path for listing in listings
                  for path in listing["saved_photo_paths"]]
    raw_rows = detector_fn(detector_name, flat_paths) if flat_paths else []
    if not isinstance(raw_rows, list) or len(raw_rows) != len(flat_paths):
        raise DetectionBatchError(
            "detector batch must return exactly one result per saved photo")

    photo_items = []
    cursor = 0
    for listing in listings:
        for index, path in enumerate(listing["saved_photo_paths"], start=1):
            raw = raw_rows[cursor]
            cursor += 1
            if not isinstance(raw, dict) or raw.get("path") != path:
                raise DetectionBatchError(
                    "detector result path/order does not match input")
            photo_items.append({
                "listing_key": listing["listing_key"],
                "path": path,
                "raw": raw,
                "photo_relative_id": f"photo-{index:04d}",
            })

    def persist_photo(item: dict[str, Any]) -> dict[str, Any]:
        return _photo_result(
            item["path"],
            item["raw"],
            photo_relative_id=item["photo_relative_id"],
            detector_name=detector_name,
            crop_root=crop_root,
            crop_writer=crop_writer,
        )

    persisted_photos = run_batch_stage(
        "detect", photo_items, persist_photo, 1, None)["results"]
    output_listings = []
    cursor = 0
    for listing in listings:
        photo_count = len(listing["saved_photo_paths"])
        photos = persisted_photos[cursor:cursor + photo_count]
        cursor += photo_count
        status, reason = _listing_status(photos)
        output_listings.append({
            "listing_key": listing["listing_key"],
            "observations": listing["observations"],
            "status": status,
            "reason": reason,
            "photos": photos,
        })

    elapsed = time.perf_counter() - started_at
    return {
        "version": DETECTION_ARTIFACT_VERSION,
        "kind": DETECTION_ARTIFACT_KIND,
        "detector": {
            "name": detector_name,
            "contract_version": minifig_detector.DETECTOR_CONTRACT_VERSION,
        },
        "listings": output_listings,
        "summary": _summary(output_listings),
        "timings": {
            "total_seconds": elapsed,
            "mean_per_photo_seconds": (
                elapsed / len(flat_paths) if flat_paths else 0.0),
        },
    }


def atomic_write_json(path: str | Path, payload: object) -> None:
    """Write JSON through a sibling temporary file, preserving old output."""
    output_path = Path(path)
    try:
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, output_path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise
    except Exception as exc:
        raise DetectionOutputError(
            f"unable to write output {output_path}: {type(exc).__name__}: {exc}"
        ) from exc


def run_batch_stage(
    stage_name: str,
    items: Sequence[dict[str, Any]],
    process_one: Callable[[dict[str, Any]], dict[str, Any]],
    workers: int,
    output_path: str | Path | None,
    *,
    clock: Callable[[], float] = time.monotonic,
    executor_factory: Callable[..., Any] = ThreadPoolExecutor,
) -> dict[str, Any]:
    """Preserve order and isolate keyed failures for every batch stage."""
    if not isinstance(stage_name, str) or not stage_name.strip():
        raise ValueError("stage_name must be a non-empty string")
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    rows = list(items)
    wall_started = clock()

    def run(item: dict[str, Any]) -> tuple[dict[str, Any], float]:
        started = clock()
        try:
            result = process_one(item)
            if not isinstance(result, dict):
                raise TypeError("stage callback must return an object")
            if result.get("status") not in STAGE_STATUSES:
                raise ValueError(
                    "stage callback status must be success, skipped, or blocked")
        except Exception as exc:  # one item must not abort valid siblings
            result = {
                key: deepcopy(item[key])
                for key in ("listing_key", "crop_id", "match_group_id")
                if key in item
            }
            result.update({
                "status": "blocked",
                "reason": f"{type(exc).__name__}: {exc}",
            })
        return result, max(0.0, clock() - started)

    if rows:
        with executor_factory(max_workers=min(workers, len(rows))) as pool:
            futures = [pool.submit(run, item) for item in rows]
            resolved = [future.result() for future in futures]
    else:
        resolved = []
    results = [result for result, _ in resolved]
    durations = [duration for _, duration in resolved]
    summary = {
        "stage": stage_name,
        "processed": len(results),
        "succeeded": sum(row["status"] == "success" for row in results),
        "skipped": sum(row["status"] == "skipped" for row in results),
        "failed": sum(row["status"] == "blocked" for row in results),
        "reasons": [row["reason"] for row in results
                    if isinstance(row.get("reason"), str) and row["reason"]],
        "workers": workers,
        "wall_seconds": round(max(0.0, clock() - wall_started), 6),
        "serial_equivalent_seconds": round(sum(durations), 6),
    }
    report = {"results": results, "summary": summary}
    if output_path is not None:
        atomic_write_json(output_path, report)
    return report


def detect_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    detector_name: str,
    crop_root: str | Path,
    detector_fn: DetectorFn = minifig_detector.detect_many,
    crop_writer: CropWriter = minifig_detector.write_crop,
) -> dict[str, int]:
    """Validate, detect, and atomically publish one complete batch."""
    source = Path(input_path).resolve(strict=False)
    destination = Path(output_path).resolve(strict=False)
    if source == destination:
        raise DetectionInputError("input and output must be different paths")
    listings = load_detection_input(input_path)
    artifact = detect_batch(
        listings,
        detector_name=detector_name,
        crop_root=crop_root,
        detector_fn=detector_fn,
        crop_writer=crop_writer,
    )
    atomic_write_json(output_path, artifact)
    return artifact["summary"]


DETECTION_FIELDS = frozenset({
    "crop_id",
    "source_photo_sha256",
    "photo_relative_id",
    "box",
    "detector_name",
    "detector_version",
    "detector_confidence",
    "crop_ref",
})
DETECTION_LISTING_FIELDS = frozenset({
    "listing_key", "observations", "status", "reason", "photos",
})
DETECTION_PHOTO_FIELDS = frozenset({
    "photo_relative_id", "source_photo_sha256", "status", "reason",
    "detections",
})


def _hex_sha256(value: object, label: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise IdentificationArtifactError(
            f"{label} must be a lowercase SHA-256")
    return value


def _relative_crop_ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise IdentificationArtifactError(
            f"{label} crop_ref must be a non-empty string")
    ref = Path(value)
    if ref.is_absolute() or ".." in ref.parts or "\\" in value:
        raise IdentificationArtifactError(
            f"{label} crop_ref must be a safe relative path")
    if ref.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise IdentificationArtifactError(
            f"{label} crop_ref must reference JPEG or PNG")
    return value


def _validate_detected(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != DETECTION_FIELDS:
        raise IdentificationArtifactError(
            f"{label} must contain exact detection fields")
    crop_id = value["crop_id"]
    if not isinstance(crop_id, str) or not crop_id:
        raise IdentificationArtifactError(
            f"{label} crop_id must be a non-empty string")
    _hex_sha256(value["source_photo_sha256"],
                f"{label} source_photo_sha256")
    photo_id = value["photo_relative_id"]
    if not isinstance(photo_id, str) or not photo_id:
        raise IdentificationArtifactError(
            f"{label} photo_relative_id must be a non-empty string")
    box = value["box"]
    if (not isinstance(box, list) or len(box) != 4
            or any(not isinstance(coord, (int, float))
                   or isinstance(coord, bool)
                   or not math.isfinite(float(coord))
                   or not 0.0 <= float(coord) <= 1.0
                   for coord in box)):
        raise IdentificationArtifactError(
            f"{label} box must contain four normalized coordinates")
    x1, y1, x2, y2 = (float(coord) for coord in box)
    if x2 < x1 or y2 < y1:
        raise IdentificationArtifactError(f"{label} box is inverted")
    if x2 == x1 or y2 == y1:
        raise IdentificationArtifactError(f"{label} box has zero-area")
    try:
        minifig_detector.iou(box, box)
    except minifig_detector.DetectorError as exc:
        raise IdentificationArtifactError(
            f"{label} box is invalid before detector_confidence-ranked "
            f"finalization: {exc}") from exc
    detector_name = value["detector_name"]
    detector_version = value["detector_version"]
    if not isinstance(detector_name, str) or not detector_name:
        raise IdentificationArtifactError(
            f"{label} detector_name must be a non-empty string")
    if not isinstance(detector_version, str) or not detector_version:
        raise IdentificationArtifactError(
            f"{label} detector_version must be a non-empty string")
    confidence = value["detector_confidence"]
    if (not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0):
        raise IdentificationArtifactError(
            f"{label} detector_confidence must be in 0..1")
    _relative_crop_ref(value["crop_ref"], label)
    return value


def validate_identification_artifact(payload: object) -> dict[str, Any]:
    """Validate one `minifig_detection` artifact before provider work."""
    if not isinstance(payload, dict):
        raise IdentificationArtifactError(
            "identification input must be a JSON object")
    if payload.get("version") != DETECTION_ARTIFACT_VERSION:
        raise IdentificationArtifactError(
            f"identification input must use version {DETECTION_ARTIFACT_VERSION}")
    if payload.get("kind") != DETECTION_ARTIFACT_KIND:
        raise IdentificationArtifactError(
            f"identification input kind must be {DETECTION_ARTIFACT_KIND}")
    detector = payload.get("detector")
    if (not isinstance(detector, dict)
            or set(detector) != {"name", "contract_version"}
            or not all(isinstance(value, str) and value
                       for value in detector.values())):
        raise IdentificationArtifactError(
            "identification input detector must contain name and contract_version")
    listings = payload.get("listings")
    if not isinstance(listings, list):
        raise IdentificationArtifactError(
            "identification input listings must be an array")
    if not isinstance(payload.get("summary"), dict):
        raise IdentificationArtifactError(
            "identification input summary must be an object")

    listing_keys = []
    for listing_index, listing in enumerate(listings):
        label = f"listing {listing_index}"
        if (not isinstance(listing, dict)
                or set(listing) != DETECTION_LISTING_FIELDS):
            raise IdentificationArtifactError(
                f"{label} must contain exact detection listing fields")
        listing_key = listing["listing_key"]
        if not isinstance(listing_key, str) or not listing_key:
            raise IdentificationArtifactError(
                f"{label} listing_key must be a non-empty string")
        listing_keys.append(listing_key)
        if not isinstance(listing["observations"], dict):
            raise IdentificationArtifactError(
                f"{label} observations must be an object")
        if listing["status"] not in STAGE_STATUSES:
            raise IdentificationArtifactError(f"{label} status is invalid")
        if listing["reason"] is not None and not isinstance(
                listing["reason"], str):
            raise IdentificationArtifactError(
                f"{label} reason must be a string or null")
        photos = listing["photos"]
        if not isinstance(photos, list):
            raise IdentificationArtifactError(
                f"{label} photos must be an array")
        crop_ids = []
        for photo_index, photo in enumerate(photos):
            photo_label = f"{label} photo {photo_index}"
            if (not isinstance(photo, dict)
                    or set(photo) != DETECTION_PHOTO_FIELDS):
                raise IdentificationArtifactError(
                    f"{photo_label} must contain exact photo fields")
            if photo["status"] not in ("success", "skipped"):
                raise IdentificationArtifactError(
                    f"{photo_label} status is invalid")
            detections = photo["detections"]
            if not isinstance(detections, list):
                raise IdentificationArtifactError(
                    f"{photo_label} detections must be an array")
            for detection_index, detection in enumerate(detections):
                detection_label = (
                    f"{photo_label} detection {detection_index}")
                row = _validate_detected(detection, detection_label)
                crop_ids.append(row["crop_id"])
        duplicate_crops = sorted({key for key in crop_ids
                                  if crop_ids.count(key) > 1})
        if duplicate_crops:
            raise IdentificationArtifactError(
                f"{label} has duplicate crop_id values: "
                + ", ".join(duplicate_crops))

    duplicate_listings = sorted({key for key in listing_keys
                                 if listing_keys.count(key) > 1})
    if duplicate_listings:
        raise IdentificationArtifactError(
            "duplicate listing_key values: " + ", ".join(duplicate_listings))
    return deepcopy(payload)


def load_identification_input(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise IdentificationArtifactError(
            f"unable to read input {input_path}: {type(exc).__name__}: {exc}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IdentificationArtifactError(
            f"invalid JSON in {input_path}: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}") from exc
    return validate_identification_artifact(payload)


def normalize_candidate_items(
    items: object,
    *,
    min_similarity: float,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise IdentificationArtifactError(
            "Brickognize candidates must be an array")
    seen = set()
    normalized = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise IdentificationArtifactError(
                f"candidate {index} must be an object")
        candidate_id = raw.get("id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise IdentificationArtifactError(
                f"candidate id at index {index} must be a non-empty string")
        if candidate_id in seen:
            raise IdentificationArtifactError(
                f"duplicate candidate id: {candidate_id}")
        seen.add(candidate_id)
        score = raw.get("score")
        if (not isinstance(score, (int, float)) or isinstance(score, bool)
                or not math.isfinite(float(score))
                or not 0.0 <= float(score) <= 1.0):
            raise IdentificationArtifactError(
                f"candidate {candidate_id} score must be in 0..1")
        if float(score) > min_similarity:
            normalized.append(deepcopy(raw))
    return sorted(normalized, key=lambda row: (-float(row["score"]), row["id"]))


def candidate_signature(candidates: list[dict[str, Any]]) -> str | None:
    if not candidates:
        return None
    ids = sorted(row["id"] for row in candidates)
    encoded = json.dumps({
        "contract_version": GROUP_CONTRACT_VERSION,
        "candidate_ids": ids,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "candsig-v1-" + hashlib.sha256(encoded).hexdigest()


def _crop_path(crop_root: str | Path, crop_ref: str) -> str:
    root = Path(crop_root).resolve(strict=False)
    candidate = (root / crop_ref).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise IdentificationArtifactError(
            f"crop_ref escapes crop root: {crop_ref}") from exc
    return str(candidate)


def _group_id(
    detections: list[dict[str, Any]],
    signature: str | None,
) -> str:
    encoded = json.dumps({
        "contract_version": GROUP_CONTRACT_VERSION,
        "candidate_signature": signature,
        "crop_ids": sorted(row["crop_id"] for row in detections),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "figgroup-v1-" + hashlib.sha256(encoded).hexdigest()


def _representative(members: list[dict[str, Any]]) -> dict[str, Any]:
    return min(members, key=lambda row: (
        -float(row["detection"]["detector_confidence"]),
        row["detection"]["crop_id"],
    ))


def _group_record(members: list[dict[str, Any]]) -> dict[str, Any]:
    representative = _representative(members)
    detections = [deepcopy(row["detection"]) for row in members]
    status = "success" if representative["status"] == "success" else "skipped"
    return {
        "match_group_id": _group_id(
            detections, representative["candidate_signature"]),
        "candidate_signature": representative["candidate_signature"],
        "detections": detections,
        "representative_crop_ref": representative["detection"]["crop_ref"],
        "brickognize_candidates": deepcopy(
            representative["candidates"]),
        "brickognize_contract": deepcopy(
            representative["contract"]),
        "status": status,
        "reason": representative["reason"] if status == "skipped" else None,
    }


def source_member_digest(listing: dict[str, Any]) -> str:
    """Bind one listing to its detector-owned group and crop membership."""
    membership = {
        "contract_version": SOURCE_MEMBER_CONTRACT_VERSION,
        "listing_key": listing["listing_key"],
        "groups": [
            {
                "match_group_id": group["match_group_id"],
                "detections": [
                    {field: detection[field] for field in sorted(DETECTION_FIELDS)}
                    for detection in group["detections"]
                ],
            }
            for group in listing["groups"]
        ],
    }
    encoded = json.dumps(
        membership, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return SOURCE_MEMBER_DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


def _listing_identification(
    listing: dict[str, Any],
    evidence: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for photo in listing["photos"]:
        for detection in photo["detections"]:
            row = evidence[(listing["listing_key"], detection["crop_id"])]
            signature = row["candidate_signature"]
            key = signature if signature is not None else (
                "isolated:" + detection["crop_id"])
            grouped.setdefault(key, []).append(row)
    groups = [_group_record(members) for members in grouped.values()]
    skipped_groups = sum(row["status"] == "skipped" for row in groups)
    upstream_reason = listing.get("reason")
    if not groups:
        status = listing["status"]
        reason = upstream_reason
    elif skipped_groups == len(groups):
        status = "skipped"
        reason = "; ".join(value for value in (
            upstream_reason, "all provider groups skipped") if value)
    elif skipped_groups:
        status = "success"
        reason = "; ".join(value for value in (
            upstream_reason,
            f"{skipped_groups} of {len(groups)} provider groups skipped",
        ) if value)
    else:
        status = "success"
        reason = upstream_reason
    output = {
        "listing_key": listing["listing_key"],
        "observations": deepcopy(listing["observations"]),
        "status": status,
        "reason": reason,
        "groups": groups,
    }
    output["source_member_digest"] = source_member_digest(output)
    return output


def _identification_summary(
    listings: list[dict[str, Any]],
    evidence: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, int]:
    groups = [group for listing in listings for group in listing["groups"]]
    rows = list(evidence.values())
    return {
        "listing_count": len(listings),
        "success_count": sum(row["status"] == "success" for row in listings),
        "partial_count": 0,
        "skipped_count": sum(row["status"] == "skipped" for row in listings),
        "crop_count": len(rows),
        "group_count": len(groups),
        "provider_success_count": sum(
            row["status"] == "success" for row in rows),
        "provider_skipped_count": sum(
            row["status"] == "skipped" for row in rows),
        "cache_hit_count": sum(
            row["status"] == "success" and row["cached"] for row in rows),
    }


def identify_batch(
    detection_artifact: dict[str, Any],
    *,
    crop_root: str | Path,
    workers: int,
    top_k: int,
    min_similarity: float,
    cache_path: str = BRICKOGNIZE_MINIFIG_CACHE,
    predictor: Predictor = brickognize.predict_many,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    brickognize.validate_options(
        workers=workers,
        top_k=top_k,
        min_similarity=min_similarity,
        timeout=brickognize.DEFAULT_TIMEOUT,
    )
    artifact = validate_identification_artifact(detection_artifact)
    detection_slots = [
        (listing["listing_key"], detection)
        for listing in artifact["listings"]
        for photo in listing["photos"]
        for detection in photo["detections"]
    ]
    detections = [detection for _, detection in detection_slots]
    crop_paths = [
        _crop_path(crop_root, detection["crop_ref"])
        for detection in detections
    ]
    if crop_paths:
        started = clock()
        provider_rows = predictor(
            crop_paths,
            workers=workers,
            top_k=top_k,
            min_similarity=min_similarity,
            cache_path=cache_path,
        )
        elapsed = clock() - started
    else:
        provider_rows = []
        elapsed = 0.0
    if not isinstance(provider_rows, list) or len(provider_rows) != len(detections):
        raise IdentificationArtifactError(
            "provider batch must return exactly one result per crop")

    def normalize_provider(item: dict[str, Any]) -> dict[str, Any]:
        index = item["index"]
        detection = item["detection"]
        crop_path = item["crop_path"]
        raw = item["raw"]
        base = {
            "listing_key": item["listing_key"],
            "detection": detection,
            "status": "skipped",
            "reason": None,
            "cached": False,
            "candidates": [],
            "candidate_signature": None,
            "contract": None,
        }
        if not isinstance(raw, dict) or raw.get("path") != crop_path:
            base["reason"] = (
                f"provider result {index} path/order does not match input")
        elif raw.get("status") != "success":
            reason = raw.get("reason")
            base["reason"] = reason if isinstance(reason, str) and reason else (
                "provider skipped crop without a reason")
        else:
            try:
                prediction = raw.get("prediction")
                if not isinstance(prediction, dict):
                    raise IdentificationArtifactError(
                        "provider prediction must be an object")
                response = brickognize.normalize_response(
                    prediction.get("response"))
                contract = prediction.get("contract")
                if not isinstance(contract, dict):
                    raise IdentificationArtifactError(
                        "provider contract must be an object")
                candidates = normalize_candidate_items(
                    response["items"], min_similarity=min_similarity)
            except (brickognize.BrickognizeError,
                    IdentificationArtifactError) as exc:
                base["reason"] = f"{type(exc).__name__}: {exc}"
            else:
                base.update({
                    "status": "success",
                    "reason": None,
                    "cached": raw.get("cached") is True,
                    "candidates": candidates,
                    "candidate_signature": candidate_signature(candidates),
                    "contract": deepcopy(contract),
                })
        return base

    provider_items = [
        {
            "index": index,
            "listing_key": listing_key,
            "detection": detection,
            "crop_path": crop_path,
            "raw": raw,
        }
        for index, ((listing_key, detection), crop_path, raw) in enumerate(zip(
            detection_slots, crop_paths, provider_rows))
    ]
    normalized_rows = run_batch_stage(
        "identify", provider_items, normalize_provider, workers, None)["results"]
    evidence = {
        (row["listing_key"], row["detection"]["crop_id"]): row
        for row in normalized_rows
    }

    output_listings = [
        _listing_identification(listing, evidence)
        for listing in artifact["listings"]
    ]
    total_seconds = round(float(elapsed), 6)
    timings = {
        "total_seconds": total_seconds,
        "mean_per_crop_seconds": (
            round(total_seconds / len(detections), 6) if detections else 0.0),
    }
    return {
        "version": IDENTIFICATION_ARTIFACT_VERSION,
        "kind": IDENTIFICATION_ARTIFACT_KIND,
        "request_contract": {
            "endpoint": brickognize.ENDPOINT,
            "contract_version": brickognize.CONTRACT_VERSION,
            "top_k_items": top_k,
            "min_similarity_items": float(min_similarity),
        },
        "listings": output_listings,
        "summary": _identification_summary(output_listings, evidence),
        "timings": timings,
    }


def identify_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    crop_root: str | Path,
    workers: int = brickognize.DEFAULT_WORKERS,
    top_k: int = 10,
    min_similarity: float = 0.5,
    cache_path: str = BRICKOGNIZE_MINIFIG_CACHE,
    predictor: Predictor = brickognize.predict_many,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    source = Path(input_path).resolve(strict=False)
    destination = Path(output_path).resolve(strict=False)
    if source == destination:
        raise IdentificationArtifactError(
            "input and output must be different paths")
    artifact = load_identification_input(input_path)
    output = identify_batch(
        artifact,
        crop_root=crop_root,
        workers=workers,
        top_k=top_k,
        min_similarity=min_similarity,
        cache_path=cache_path,
        predictor=predictor,
        clock=clock,
    )
    atomic_write_json(output_path, output)
    return {
        "summary": output["summary"],
        "timings": output["timings"],
    }


PRICE_MAX_WORKERS = 8
VERIFICATION_FIELDS = frozenset({
    "status", "reason", "compared_candidate_ids", "catalog_checked_at",
})
IDENTIFY_GROUP_FIELDS = frozenset({
    "match_group_id", "candidate_signature", "detections",
    "representative_crop_ref", "brickognize_candidates",
    "brickognize_contract", "status", "reason",
})


def _validate_price_artifact(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IdentificationArtifactError("price input must be a JSON object")
    if payload.get("version") != IDENTIFICATION_ARTIFACT_VERSION:
        raise IdentificationArtifactError(
            f"price input must use version {IDENTIFICATION_ARTIFACT_VERSION}")
    if payload.get("kind") != IDENTIFICATION_ARTIFACT_KIND:
        raise IdentificationArtifactError(
            f"price input kind must be {IDENTIFICATION_ARTIFACT_KIND}")
    listings = payload.get("listings")
    if not isinstance(listings, list):
        raise IdentificationArtifactError("price input listings must be an array")
    listing_keys = []
    for listing_index, listing in enumerate(listings):
        if not isinstance(listing, dict):
            raise IdentificationArtifactError(
                f"price listing {listing_index} must be an object")
        listing_key = listing.get("listing_key")
        if not isinstance(listing_key, str) or not listing_key:
            raise IdentificationArtifactError(
                f"price listing {listing_index} has no listing_key")
        listing_keys.append(listing_key)
        if not isinstance(listing.get("observations"), dict):
            raise IdentificationArtifactError(
                f"price listing {listing_index} observations must be an object")
        groups = listing.get("groups")
        if not isinstance(groups, list):
            raise IdentificationArtifactError(
                f"price listing {listing_index} groups must be an array")
        group_ids = []
        crop_ids = []
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                raise IdentificationArtifactError(
                    f"price listing {listing_index} group {group_index} must be "
                    "an object")
            missing = sorted(IDENTIFY_GROUP_FIELDS - set(group))
            if missing:
                raise IdentificationArtifactError(
                    f"price listing {listing_index} group {group_index} missing "
                    f"fields: {', '.join(missing)}")
            group_id = group.get("match_group_id")
            if not isinstance(group_id, str) or not group_id:
                raise IdentificationArtifactError(
                    f"price listing {listing_index} group {group_index} has no "
                    "match_group_id")
            group_ids.append(group_id)
            detections = group.get("detections")
            if not isinstance(detections, list) or not detections:
                raise IdentificationArtifactError(
                    f"price group {group_id} detections must be non-empty")
            for detection in detections:
                if not isinstance(detection, dict):
                    raise IdentificationArtifactError(
                        f"price group {group_id} detection must be an object")
                crop_id = detection.get("crop_id")
                if not isinstance(crop_id, str) or not crop_id:
                    raise IdentificationArtifactError(
                        f"price group {group_id} detection has no crop_id")
                crop_ids.append(crop_id)
        for label, values in (
            ("match_group_id", group_ids),
            ("crop_id", crop_ids),
        ):
            duplicates = sorted({value for value in values
                                 if values.count(value) > 1})
            if duplicates:
                raise IdentificationArtifactError(
                    f"price listing {listing_key} has duplicate {label} values: "
                    + ", ".join(duplicates))
        expected_digest = listing.get("source_member_digest")
        if (not isinstance(expected_digest, str)
                or not expected_digest.startswith(SOURCE_MEMBER_DIGEST_PREFIX)
                or len(expected_digest) != len(SOURCE_MEMBER_DIGEST_PREFIX) + 64
                or any(character not in "0123456789abcdef"
                       for character in expected_digest[
                           len(SOURCE_MEMBER_DIGEST_PREFIX):])):
            raise IdentificationArtifactError(
                f"price listing {listing_key} source_member_digest is invalid")
        actual_digest = source_member_digest(listing)
        if expected_digest != actual_digest:
            raise IdentificationArtifactError(
                f"price listing {listing_key} detector membership drift: "
                "source_member_digest does not match its groups and detections")
    duplicates = sorted({value for value in listing_keys
                         if listing_keys.count(value) > 1})
    if duplicates:
        raise IdentificationArtifactError(
            f"duplicate listing_key values: {', '.join(duplicates)}")
    return deepcopy(payload)


def load_price_input(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise IdentificationArtifactError(
            f"unable to read input {input_path}: {type(exc).__name__}: {exc}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IdentificationArtifactError(
            f"invalid JSON in {input_path}: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}") from exc
    return _validate_price_artifact(payload)


def _verification_error(group: dict[str, Any]) -> str | None:
    group_id = group["match_group_id"]
    for detection in group["detections"]:
        if "verification" in detection:
            return (f"group {group_id} verification must exist only on the "
                    "representative group, never on a detection")
        try:
            _validate_detected(detection, f"group {group_id} detection")
        except IdentificationArtifactError as exc:
            return str(exc)
    verification = group.get("verification")
    if not isinstance(verification, dict) or set(verification) != VERIFICATION_FIELDS:
        return (f"group {group_id} verification must contain exact fields "
                f"{sorted(VERIFICATION_FIELDS)}")
    status = verification.get("status")
    if status not in minifig_analysis.VERIFICATION_STATUSES:
        return f"group {group_id} verification.status is invalid: {status!r}"
    reason = verification.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return f"group {group_id} verification.reason must be non-empty"
    compared = verification.get("compared_candidate_ids")
    if (not isinstance(compared, list)
            or any(not isinstance(value, str) or not value for value in compared)
            or len(set(compared)) != len(compared)):
        return (f"group {group_id} verification.compared_candidate_ids must be "
                "a unique string array")
    checked = verification.get("catalog_checked_at")
    if not isinstance(checked, str) or not checked:
        return f"group {group_id} verification.catalog_checked_at is required"
    candidates = group.get("brickognize_candidates")
    if not isinstance(candidates, list):
        return f"group {group_id} brickognize_candidates must be an array"
    if any(not isinstance(row, dict)
           or not isinstance(row.get("id"), str)
           or not row["id"] for row in candidates):
        return f"group {group_id} Brickognize candidates must have string ids"
    candidate_ids = [row["id"] for row in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        return f"group {group_id} Brickognize candidate ids must be unique"
    if any(value not in candidate_ids for value in compared):
        return (f"group {group_id} compared_candidate_ids contains an unknown "
                "Brickognize candidate")
    fig_no = group.get("fig_no")
    catalog = group.get("catalog")
    if status == "verified":
        if group.get("status") != "success":
            return (f"group {group_id} verified identity requires a "
                    "provider-success group")
        if compared != candidate_ids:
            return (f"group {group_id} verified identity must compare all "
                    "Brickognize candidates in ranked order")
        if not isinstance(fig_no, str) or not fig_no:
            return f"group {group_id} verified identity requires fig_no"
        if fig_no not in candidate_ids:
            return (f"group {group_id} verified fig_no must be one of the "
                    "Brickognize candidates")
        if not isinstance(catalog, dict) or catalog.get("no") != fig_no:
            return (f"group {group_id} verified fig_no does not match catalog "
                    "number")
        if not isinstance(catalog.get("name"), str) or not catalog["name"].strip():
            return f"group {group_id} verified identity requires catalog name"
        image = catalog.get("thumbnail_url")
        if not isinstance(image, str) or not image.strip():
            return f"group {group_id} verified identity requires catalog image"
    elif fig_no is not None or catalog is not None:
        return (f"group {group_id} {status} verification must not carry fig_no "
                "or catalog")
    notes = group.get("condition_notes")
    if notes is not None and not isinstance(notes, str):
        return f"group {group_id} condition_notes must be a string or null"
    return None


def _clean_detections(group: dict[str, Any]) -> list[dict[str, Any]]:
    cleaned = []
    for raw in group["detections"]:
        detection = {key: deepcopy(raw.get(key)) for key in DETECTION_FIELDS}
        _validate_detected(detection, f"group {group['match_group_id']} detection")
        cleaned.append(detection)
    return cleaned


def _stage_failed_group(group: dict[str, Any], error: str) -> dict[str, Any]:
    try:
        detections = _clean_detections(group)
    except IdentificationArtifactError as exc:
        # A malformed detector row cannot be emitted as canonical
        # minifig_analysis. Keep the keyed raw evidence outside the canonical
        # entries so this group does not abort valid siblings.
        return {
            "stage_failed": True,
            "match_group_id": group.get("match_group_id"),
            "detections": deepcopy(group.get("detections")),
            "errors": [f"VerificationError: {error}; {exc}"],
        }
    return {
        "source_group_ids": [group["match_group_id"]],
        "detections": detections,
        "brickognize_candidates": deepcopy(
            group.get("brickognize_candidates") or []),
        "verification": {
            "status": "unverifiable",
            "reason": error,
            "compared_candidate_ids": [],
            "catalog_checked_at": None,
        },
        "fig_no": None,
        "catalog": None,
        "condition_notes": group.get("condition_notes")
        if isinstance(group.get("condition_notes"), str) else None,
        "null_value_reason": "stage_failed",
        "errors": [f"VerificationError: {error}"],
    }


def _verified_group(group: dict[str, Any]) -> dict[str, Any]:
    status = group["verification"]["status"]
    return {
        "source_group_ids": [group["match_group_id"]],
        "detections": _clean_detections(group),
        "brickognize_candidates": deepcopy(group["brickognize_candidates"]),
        "verification": deepcopy(group["verification"]),
        "fig_no": group.get("fig_no"),
        "catalog": deepcopy(group.get("catalog")),
        "condition_notes": group.get("condition_notes"),
        "null_value_reason": (
            None if status == "verified"
            else "unknown_identity" if status == "unknown"
            else "unverifiable"),
        "errors": [],
    }


def _suppress_listing_overlaps(
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    nodes = []
    for group_index, group in enumerate(groups):
        for detection in group["detections"]:
            nodes.append((group_index, detection))
    nodes.sort(key=lambda item: (
        -float(item[1]["detector_confidence"]),
        item[1]["crop_id"],
    ))
    kept = []
    for group_index, detection in nodes:
        duplicate = any(
            existing["source_photo_sha256"]
            == detection["source_photo_sha256"]
            and _same_identity_detection_duplicate(existing, detection)
            for _, existing in kept
        )
        if not duplicate:
            kept.append((group_index, detection))
    allowed = {detection["crop_id"] for _, detection in kept}
    output = []
    for group in groups:
        row = deepcopy(group)
        row["detections"] = [
            detection for detection in row["detections"]
            if detection["crop_id"] in allowed
        ]
        if row["detections"]:
            output.append(row)
    return output


def _entry_representative(groups: list[dict[str, Any]]) -> dict[str, Any]:
    choices = [(group, detection) for group in groups
               for detection in group["detections"]]
    return min(choices, key=lambda item: (
        -float(item[1]["detector_confidence"]),
        item[1]["crop_id"],
    ))[0]


def _final_group_id(groups: list[dict[str, Any]], fig_no: str | None) -> str:
    if len(groups) == 1:
        return groups[0]["source_group_ids"][0]
    encoded = json.dumps({
        "contract_version": "minifig-final-union-v1",
        "fig_no": fig_no,
        "crop_ids": sorted(
            detection["crop_id"] for group in groups
            for detection in group["detections"]),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "figfinal-v1-" + hashlib.sha256(encoded).hexdigest()


def _quantity(detections: list[dict[str, Any]]) -> int:
    counts: dict[str, int] = {}
    for detection in detections:
        photo = detection["source_photo_sha256"]
        counts[photo] = counts.get(photo, 0) + 1
    return max(counts.values())


def _same_identity_detection_duplicate(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    """Suppress a duplicate box without erasing simultaneous figures.

    IoU remains the exact 0.70 contract. Deeply nested detector splits are also
    duplicates only when the retained box has at least twice the confidence of
    the inner box. This preserves similarly confident, simultaneous detections
    just below the IoU boundary while removing the low-confidence inner crop
    emitted for the same physical figure.
    """
    if (minifig_detector.iou(left["box"], right["box"])
            >= minifig_detector.DUPLICATE_IOU_THRESHOLD):
        return True
    if not minifig_detector.boxes_duplicate(left["box"], right["box"]):
        return False
    high = max(float(left["detector_confidence"]),
               float(right["detector_confidence"]))
    low = min(float(left["detector_confidence"]),
              float(right["detector_confidence"]))
    return high > low and high >= 2 * low


def _representative_photo_quantity_basis(
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Choose one physical-lot view and the countable crops shown in it.

    Identity groups are evidence, not additive inventories: repeated listing
    photos show the same physical lot. Quantity therefore comes from the one
    photo with the greatest simultaneous globally de-duplicated detection
    count. Stable photo ID/hash ordering breaks ties. The entries themselves
    remain intact so every catalog-verification group stays auditable.
    """
    by_photo: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for detection in entry["detections"]:
            by_photo.setdefault(detection["source_photo_sha256"], []).append(detection)
    photo_hash, detections = min(
        by_photo.items(),
        key=lambda item: (
            -len(item[1]),
            min(row["photo_relative_id"] for row in item[1]),
            item[0],
        ),
    )
    return {
        "rule": minifig_analysis.REPRESENTATIVE_PHOTO_QUANTITY_RULE,
        "photo_relative_id": min(
            row["photo_relative_id"] for row in detections),
        "source_photo_sha256": photo_hash,
        "counted_crop_ids": sorted(row["crop_id"] for row in detections),
    }


def _merge_final_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for group in groups:
        status = group["verification"]["status"]
        key = ("fig:" + group["fig_no"]
               if status == "verified"
               else "group:" + group["source_group_ids"][0])
        buckets.setdefault(key, []).append(group)
    entries = []
    for raw_members in buckets.values():
        # Suppress duplicate boxes only inside one identity bucket. An
        # overlapping detection that the identifier resolved to another exact
        # fig_no (including a letter-suffix sibling) is conflicting evidence,
        # not permission to erase that independently verified group. Unknown
        # and unverifiable buckets are unique and therefore never merge merely
        # because their candidate signatures or boxes match.
        members = _suppress_listing_overlaps(raw_members)
        representative = _entry_representative(members)
        detections = [deepcopy(detection) for group in members
                      for detection in group["detections"]]
        notes = sorted({group["condition_notes"] for group in members
                        if isinstance(group.get("condition_notes"), str)
                        and group["condition_notes"]})
        errors = [error for group in members for error in group["errors"]]
        entry = {
            "match_group_id": _final_group_id(
                members, representative["fig_no"]),
            "detections": detections,
            "representative_crop_ref": min(
                detections,
                key=lambda row: (
                    -float(row["detector_confidence"]), row["crop_id"]),
            )["crop_ref"],
            "brickognize_candidates": deepcopy(
                representative["brickognize_candidates"]),
            "verification": deepcopy(representative["verification"]),
            "fig_no": representative["fig_no"],
            "catalog": deepcopy(representative["catalog"]),
            "quantity": None,
            "condition_notes": "; ".join(notes) if notes else None,
            "used": None,
            "unit_value": None,
            "extended_value": None,
            "null_value_reason": representative["null_value_reason"],
            "errors": errors,
        }
        entries.append(entry)
    listing_basis = _representative_photo_quantity_basis(entries)
    countable = set(listing_basis["counted_crop_ids"])
    for entry in entries:
        counted_crop_ids = sorted(
            detection["crop_id"] for detection in entry["detections"]
            if detection["crop_id"] in countable
        )
        entry["quantity"] = len(counted_crop_ids)
        entry["quantity_basis"] = {
            **listing_basis,
            "counted_crop_ids": counted_crop_ids,
        }
        if (entry["quantity"] == 0
                and entry["verification"]["status"] == "verified"):
            entry["null_value_reason"] = "evidence_only"
    return entries


def _prepared_listing(listing: dict[str, Any]) -> dict[str, Any]:
    base = {
        "listing_key": listing["listing_key"],
        "source_status": listing.get("status"),
        "source_reason": listing.get("reason"),
        "failed_groups": [],
    }
    if not listing["groups"]:
        return {
            **base,
            "blocked": True,
            "blocker": listing.get("reason") or "no minifigure groups",
            "entries": [],
        }
    groups = []
    failed_groups = []
    for group in listing["groups"]:
        error = _verification_error(group)
        row = (_stage_failed_group(group, error)
               if error is not None else _verified_group(group))
        if row.get("stage_failed") is True:
            failed_groups.append(row)
        else:
            groups.append(row)
    if not groups:
        return {
            **base,
            "failed_groups": failed_groups,
            "blocked": True,
            "blocker": "all minifigure groups failed verification",
            "entries": [],
        }
    return {
        **base,
        "failed_groups": failed_groups,
        "blocked": False,
        "blocker": None,
        "entries": _merge_final_groups(groups),
    }


def _apply_price(entry: dict[str, Any], outcome: object) -> None:
    if isinstance(outcome, Exception):
        entry["null_value_reason"] = (
            "price_lookup_failed"
            if isinstance(outcome, (minifig_sales.LookupFailed,
                                    minifig_sales.LookupNotFound))
            else "stage_failed")
        entry["errors"].append(
            f"{type(outcome).__name__}: {outcome}")
        return
    if not isinstance(outcome, dict):
        entry["null_value_reason"] = "stage_failed"
        entry["errors"].append(
            "PricingError: minifig pricer returned a non-object")
        return
    entry["used"] = deepcopy(outcome.get("used"))
    unit_value = outcome.get("unit_value")
    if unit_value is None:
        entry["null_value_reason"] = "zero_sales"
        return
    if (not isinstance(unit_value, (int, float))
            or isinstance(unit_value, bool)
            or not math.isfinite(float(unit_value))
            or float(unit_value) < 0):
        entry["null_value_reason"] = "stage_failed"
        entry["errors"].append(
            f"PricingError: invalid unit_value {unit_value!r}")
        return
    entry["unit_value"] = float(unit_value)
    entry["extended_value"] = minifig_analysis.round_cents(
        float(unit_value) * entry["quantity"])
    entry["null_value_reason"] = None


def _result_from_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
    failed_groups = deepcopy(prepared.get("failed_groups") or [])
    reason = prepared.get("source_reason")
    if reason is None and failed_groups:
        reason = f"{len(failed_groups)} minifigure groups failed verification"
    if prepared["blocked"]:
        return {
            "listing_key": prepared["listing_key"],
            "blocked": True,
            "blocker": prepared["blocker"],
            "reason": reason or prepared["blocker"],
            "failed_groups": failed_groups,
            "minifig_analysis": None,
            "figure_count": None,
            "figure_count_source": None,
            "identified_count": 0,
            "unknown_count": 0,
            "priced_subtotal": 0.0,
            "sold_count": None,
            "pricing_complete": False,
            "status": "blocked",
        }
    normalized = [minifig_analysis.normalize_entry(entry)
                  for entry in prepared["entries"]]
    errors = [
        f"entry {index}: {error}"
        for index, entry in enumerate(normalized)
        for error in minifig_analysis.entry_errors(entry)
    ] + minifig_analysis.batch_errors(normalized)
    if errors:
        raise IdentificationArtifactError(
            "final minifig_analysis violates canonical invariants: "
            + "; ".join(errors))
    unknown = minifig_analysis.unknown_count(normalized)
    complete = (unknown == 0
                and not failed_groups
                and prepared.get("source_reason") is None
                and prepared.get("source_status") == "success"
                and all(
                    entry["quantity"] == 0
                    or (entry["unit_value"] is not None and not entry["errors"])
                    for entry in normalized))
    return {
        "listing_key": prepared["listing_key"],
        "reason": reason,
        "failed_groups": failed_groups,
        "minifig_analysis": normalized,
        "figure_count": minifig_analysis.figure_count(normalized),
        "figure_count_source": "detection",
        "identified_count": minifig_analysis.identified_count(normalized),
        "unknown_count": unknown,
        "priced_subtotal": minifig_analysis.round_cents(
            minifig_analysis.priced_subtotal(normalized)),
        "sold_count": minifig_analysis.sold_count(normalized),
        "pricing_complete": complete,
        "status": "success",
    }


def price_batch(
    identification_artifact: dict[str, Any],
    *,
    workers: int = 4,
    refresh: bool = False,
    pricer: Callable[..., dict[str, Any]] = minifig_sales.summarize_fig,
    clock: Callable[[], float] = time.monotonic,
    executor_factory: Callable[..., Any] = ThreadPoolExecutor,
) -> dict[str, Any]:
    if type(workers) is not int or not 1 <= workers <= PRICE_MAX_WORKERS:
        raise IdentificationArtifactError(
            f"workers must be an integer in 1..{PRICE_MAX_WORKERS}")
    artifact = _validate_price_artifact(identification_artifact)
    prepared = [_prepared_listing(listing) for listing in artifact["listings"]]
    targets = [entry for listing in prepared if not listing["blocked"]
               for entry in listing["entries"]
               if entry["verification"]["status"] == "verified"
               and entry["quantity"] > 0
               and not entry["errors"]]
    target_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in targets:
        target_groups.setdefault(entry["fig_no"], []).append(entry)
    unique_targets = [entries[0] for entries in target_groups.values()]
    if unique_targets:
        def run(entry):
            try:
                outcome = pricer(
                    entry["fig_no"], entry["catalog"], refresh=refresh)
            except Exception as exc:
                outcome = exc
            return {"status": "success", "reason": None, "outcome": outcome}

        stage = run_batch_stage(
            "price",
            unique_targets,
            run,
            min(workers, len(unique_targets)),
            None,
            clock=clock,
            executor_factory=executor_factory,
        )
        for entries, resolved in zip(target_groups.values(), stage["results"]):
            for entry in entries:
                _apply_price(entry, resolved["outcome"])
        wall_seconds = stage["summary"]["wall_seconds"]
        serial_equivalent_seconds = stage["summary"][
            "serial_equivalent_seconds"]
    else:
        wall_seconds = 0.0
        serial_equivalent_seconds = 0.0
    results = [_result_from_prepared(listing) for listing in prepared]
    summary = {
        "listing_count": len(results),
        "success_count": sum(row["status"] == "success" for row in results),
        "partial_count": 0,
        "blocked_count": sum(row["status"] == "blocked" for row in results),
        "entry_count": sum(len(row.get("minifig_analysis") or [])
                           for row in results),
        "priced_entry_count": sum(
            entry["unit_value"] is not None for row in results
            for entry in (row.get("minifig_analysis") or [])),
        "workers": workers,
        "wall_seconds": round(wall_seconds, 6),
        "serial_equivalent_seconds": round(serial_equivalent_seconds, 6),
    }
    return {"results": results, "summary": summary}


def price_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    workers: int = 4,
    refresh: bool = False,
    pricer: Callable[..., dict[str, Any]] = minifig_sales.summarize_fig,
    clock: Callable[[], float] = time.monotonic,
    executor_factory: Callable[..., Any] = ThreadPoolExecutor,
) -> dict[str, Any]:
    source = Path(input_path).resolve(strict=False)
    destination = Path(output_path).resolve(strict=False)
    if source == destination:
        raise IdentificationArtifactError(
            "input and output must be different paths")
    artifact = load_price_input(input_path)
    report = price_batch(
        artifact,
        workers=workers,
        refresh=refresh,
        pricer=pricer,
        clock=clock,
        executor_factory=executor_factory,
    )
    atomic_write_json(output_path, report["results"])
    return report["summary"]
