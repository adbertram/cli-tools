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
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Sequence

from ..paths import BRICKOGNIZE_MINIFIG_CACHE
from . import brickognize, minifig_detector

DETECTION_ARTIFACT_VERSION = 1
DETECTION_ARTIFACT_KIND = "minifig_detection"
IDENTIFICATION_ARTIFACT_VERSION = 1
IDENTIFICATION_ARTIFACT_KIND = "minifig_identification"
GROUP_CONTRACT_VERSION = "minifig-group-v1"
DETECTION_INPUT_KEYS = frozenset({
    "listing_key",
    "saved_photo_paths",
    "observations",
})

DetectorFn = Callable[[str, Sequence[str]], list[dict[str, Any]]]
CropWriter = Callable[[str, dict[str, Any], str], str]
Predictor = Callable[..., list[dict[str, Any]]]


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
    crop_ids = []
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
        if listing["status"] not in ("success", "partial", "skipped"):
            raise IdentificationArtifactError(f"{label} status is invalid")
        if listing["reason"] is not None and not isinstance(
                listing["reason"], str):
            raise IdentificationArtifactError(
                f"{label} reason must be a string or null")
        photos = listing["photos"]
        if not isinstance(photos, list):
            raise IdentificationArtifactError(
                f"{label} photos must be an array")
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

    duplicate_listings = sorted({key for key in listing_keys
                                 if listing_keys.count(key) > 1})
    if duplicate_listings:
        raise IdentificationArtifactError(
            "duplicate listing_key values: " + ", ".join(duplicate_listings))
    duplicate_crops = sorted({key for key in crop_ids
                              if crop_ids.count(key) > 1})
    if duplicate_crops:
        raise IdentificationArtifactError(
            "duplicate crop_id values: " + ", ".join(duplicate_crops))
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
    status = "skipped" if representative["status"] == "skipped" else "success"
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


def _listing_identification(
    listing: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for photo in listing["photos"]:
        for detection in photo["detections"]:
            row = evidence[detection["crop_id"]]
            signature = row["candidate_signature"]
            key = signature if signature is not None else (
                "isolated:" + detection["crop_id"])
            grouped.setdefault(key, []).append(row)
    groups = [_group_record(members) for members in grouped.values()]
    skipped_groups = sum(row["status"] == "skipped" for row in groups)
    if not groups:
        status = listing["status"]
        reason = listing["reason"]
    elif skipped_groups == len(groups):
        status = "skipped"
        reason = "all provider groups skipped"
    elif skipped_groups:
        status = "partial"
        reason = f"{skipped_groups} of {len(groups)} provider groups skipped"
    elif listing["status"] == "partial":
        status = "partial"
        reason = listing["reason"]
    else:
        status = "success"
        reason = None
    return {
        "listing_key": listing["listing_key"],
        "observations": deepcopy(listing["observations"]),
        "status": status,
        "reason": reason,
        "groups": groups,
    }


def _identification_summary(
    listings: list[dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, int]:
    groups = [group for listing in listings for group in listing["groups"]]
    rows = list(evidence.values())
    return {
        "listing_count": len(listings),
        "success_count": sum(row["status"] == "success" for row in listings),
        "partial_count": sum(row["status"] == "partial" for row in listings),
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
    detections = [
        detection
        for listing in artifact["listings"]
        for photo in listing["photos"]
        for detection in photo["detections"]
    ]
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

    evidence = {}
    for index, (detection, crop_path, raw) in enumerate(zip(
            detections, crop_paths, provider_rows)):
        base = {
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
        evidence[detection["crop_id"]] = base

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
