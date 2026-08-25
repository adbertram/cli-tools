"""Durable minifigure detection artifacts.

This module consumes only classifier-saved local photo paths. It never fetches
listing media. Later minifigure stages extend this module's artifact pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

from . import minifig_detector

DETECTION_ARTIFACT_VERSION = 1
DETECTION_ARTIFACT_KIND = "minifig_detection"
DETECTION_INPUT_KEYS = frozenset({
    "listing_key",
    "saved_photo_paths",
    "observations",
})

DetectorFn = Callable[[str, Sequence[str]], list[dict[str, Any]]]
CropWriter = Callable[[str, dict[str, Any], str], str]


class DetectionInputError(ValueError):
    """The classifier hand-off is invalid or unreadable."""


class DetectionBatchError(ValueError):
    """The detector violated its batch result contract."""


class DetectionOutputError(OSError):
    """The durable artifact could not be atomically written."""


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
    return "partial", f"{skipped} of {len(photos)} photos skipped"


def _summary(listings: list[dict[str, Any]]) -> dict[str, int]:
    photos = [photo for listing in listings for photo in listing["photos"]]
    return {
        "listing_count": len(listings),
        "success_count": sum(row["status"] == "success" for row in listings),
        "partial_count": sum(row["status"] == "partial" for row in listings),
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
    if detector_name not in minifig_detector.DETECTOR_LOADERS:
        raise DetectionInputError(f"unknown detector: {detector_name}")
    flat_paths = [path for listing in listings
                  for path in listing["saved_photo_paths"]]
    raw_rows = detector_fn(detector_name, flat_paths) if flat_paths else []
    if not isinstance(raw_rows, list) or len(raw_rows) != len(flat_paths):
        raise DetectionBatchError(
            "detector batch must return exactly one result per saved photo")

    output_listings = []
    cursor = 0
    for listing in listings:
        photos = []
        for index, path in enumerate(listing["saved_photo_paths"], start=1):
            raw = raw_rows[cursor]
            cursor += 1
            if not isinstance(raw, dict) or raw.get("path") != path:
                raise DetectionBatchError(
                    "detector result path/order does not match input")
            photos.append(_photo_result(
                path,
                raw,
                photo_relative_id=f"photo-{index:04d}",
                detector_name=detector_name,
                crop_root=crop_root,
                crop_writer=crop_writer,
            ))
        status, reason = _listing_status(photos)
        output_listings.append({
            "listing_key": listing["listing_key"],
            "observations": listing["observations"],
            "status": status,
            "reason": reason,
            "photos": photos,
        })

    return {
        "version": DETECTION_ARTIFACT_VERSION,
        "kind": DETECTION_ARTIFACT_KIND,
        "detector": {
            "name": detector_name,
            "contract_version": minifig_detector.DETECTOR_CONTRACT_VERSION,
        },
        "listings": output_listings,
        "summary": _summary(output_listings),
    }


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> None:
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
