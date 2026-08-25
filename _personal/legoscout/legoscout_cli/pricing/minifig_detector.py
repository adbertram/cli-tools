"""Warm minifigure detector seam and deterministic crop creation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image

DETECTOR_CONTRACT_VERSION = "v1"
DUPLICATE_IOU_THRESHOLD = 0.70
GROUNDING_DINO_MODEL = "IDEA-Research/grounding-dino-tiny"
GROUNDING_DINO_REVISION = "a2bb814dd30d776dcf7e30523b00659f4f141c71"
GROUNDING_DINO_WEIGHTS_SHA256 = (
    "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3"
)
GROUNDING_DINO_PROMPT = "lego minifigure."
GROUNDING_DINO_THRESHOLD = 0.25

RawBatch = list[object]
DetectBatch = Callable[[list[str]], RawBatch]
DetectorLoader = Callable[[], DetectBatch]


class DetectorError(ValueError):
    """Detector contract error."""


class CropWriteError(OSError):
    """A crop could not be encoded and atomically promoted."""


def _is_finite_number(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _normalized_box(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise DetectorError("detection box must contain four coordinates")
    if not all(_is_finite_number(coord) for coord in value):
        raise DetectorError("detection box coordinates must be finite")
    box = [float(coord) for coord in value]
    if not all(0.0 <= coord <= 1.0 for coord in box):
        raise DetectorError("detection box coordinates must be in 0..1")
    x1, y1, x2, y2 = box
    if x2 < x1 or y2 < y1:
        raise DetectorError("detection box is inverted")
    if x2 == x1 or y2 == y1:
        raise DetectorError("detection box has zero-area")
    return box


def stable_crop_id(photo_bytes: bytes, box: Sequence[float]) -> str:
    """Return a path-independent ID from photo bytes, box, and contract."""
    normalized = _normalized_box(box)
    photo_hash = hashlib.sha256(photo_bytes).hexdigest()
    payload = json.dumps(
        {
            "contract": DETECTOR_CONTRACT_VERSION,
            "photo_sha256": photo_hash,
            "box": [format(coord, ".15g") for coord in normalized],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"figcrop-{DETECTOR_CONTRACT_VERSION}-{digest}"


def iou(left: Sequence[float], right: Sequence[float]) -> float:
    """Intersection-over-union for two normalized boxes."""
    lx1, ly1, lx2, ly2 = _normalized_box(left)
    rx1, ry1, rx2, ry2 = _normalized_box(right)
    width = max(0.0, min(lx2, rx2) - max(lx1, rx1))
    height = max(0.0, min(ly2, ry2) - max(ly1, ry1))
    intersection = width * height
    left_area = (lx2 - lx1) * (ly2 - ly1)
    right_area = (rx2 - rx1) * (ry2 - ry1)
    return intersection / (left_area + right_area - intersection)


def suppress_overlaps(
    detections: list[dict[str, Any]],
    threshold: float = DUPLICATE_IOU_THRESHOLD,
) -> list[dict[str, Any]]:
    """Suppress duplicate boxes, keeping confidence then crop-ID order."""
    ranked = sorted(
        detections,
        key=lambda row: (-row["confidence"], row["crop_id"]),
    )
    kept: list[dict[str, Any]] = []
    for candidate in ranked:
        if all(iou(candidate["box"], existing["box"]) < threshold
               for existing in kept):
            kept.append(candidate)
    return sorted(
        kept,
        key=lambda row: (*row["box"], row["crop_id"]),
    )


def normalize_detections(
    raw_detections: object,
    photo_bytes: bytes,
) -> list[dict[str, Any]]:
    """Validate, identify, suppress, and sort one image's detections."""
    if not isinstance(raw_detections, list):
        raise DetectorError("detections must be a list")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_detections):
        if not isinstance(raw, dict):
            raise DetectorError(f"detection {index} must be an object")
        box = _normalized_box(raw.get("box"))
        confidence = raw.get("confidence")
        if not _is_finite_number(confidence):
            raise DetectorError(f"detection {index} confidence must be finite")
        confidence_value = float(confidence)
        if not 0.0 <= confidence_value <= 1.0:
            raise DetectorError(f"detection {index} confidence must be in 0..1")
        normalized.append({
            "crop_id": stable_crop_id(photo_bytes, box),
            "box": box,
            "confidence": confidence_value,
            "class": "minifigure",
        })
    return suppress_overlaps(normalized)


def _load_grounding_dino_tiny() -> DetectBatch:
    """Load the benchmark winner once and return its warm batch callable."""
    import torch
    from transformers import (
        AutoModelForZeroShotObjectDetection,
        AutoProcessor,
    )

    processor = AutoProcessor.from_pretrained(
        GROUNDING_DINO_MODEL, revision=GROUNDING_DINO_REVISION)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(
        GROUNDING_DINO_MODEL, revision=GROUNDING_DINO_REVISION)
    model.eval()

    def run(paths: list[str]) -> RawBatch:
        rows: RawBatch = []
        for path in paths:
            try:
                with Image.open(path) as source:
                    image = source.convert("RGB")
                inputs = processor(
                    images=image,
                    text=GROUNDING_DINO_PROMPT,
                    return_tensors="pt",
                )
                with torch.no_grad():
                    outputs = model(**inputs)
                result = processor.post_process_grounded_object_detection(
                    outputs,
                    input_ids=inputs.input_ids,
                    threshold=GROUNDING_DINO_THRESHOLD,
                    text_threshold=GROUNDING_DINO_THRESHOLD,
                    target_sizes=[image.size[::-1]],
                )[0]
                width, height = image.size
                boxes = [{
                    "box": [
                        xyxy[0] / width,
                        xyxy[1] / height,
                        xyxy[2] / width,
                        xyxy[3] / height,
                    ],
                    "confidence": confidence,
                } for xyxy, confidence in zip(
                    result["boxes"].tolist(),
                    result["scores"].tolist(),
                )]
                rows.append({"path": path, "detections": boxes})
            except Exception as exc:
                rows.append({
                    "path": path,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return rows

    return run


DETECTOR_LOADERS: dict[str, DetectorLoader] = {
    "grounding-dino-tiny": _load_grounding_dino_tiny,
}


def load_detector(
    name: str,
    loaders: Mapping[str, DetectorLoader] | None = None,
) -> DetectBatch:
    """Load exactly one named detector."""
    registry = DETECTOR_LOADERS if loaders is None else loaders
    loader = registry.get(name)
    if loader is None:
        raise DetectorError(f"unknown detector: {name}")
    try:
        detector = loader()
    except Exception as exc:
        raise DetectorError(
            f"detector {name} load failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not callable(detector):
        raise DetectorError(f"detector {name} loader did not return a callable")
    return detector


def _skipped(path: str, reason: str) -> dict[str, Any]:
    return {
        "path": path,
        "status": "skipped",
        "reason": reason,
        "detections": [],
    }


def detect_many(
    name: str,
    paths: Sequence[str],
    loaders: Mapping[str, DetectorLoader] | None = None,
) -> list[dict[str, Any]]:
    """Run one warm detector batch and isolate malformed image results."""
    input_paths = [str(path) for path in paths]
    try:
        backend = load_detector(name, loaders)
    except DetectorError as exc:
        return [_skipped(path, str(exc)) for path in input_paths]

    try:
        rows = backend(input_paths)
    except Exception as exc:
        reason = f"detector batch failed: {type(exc).__name__}: {exc}"
        return [_skipped(path, reason) for path in input_paths]

    if not isinstance(rows, list):
        return [_skipped(path, "detector output must be a list")
                for path in input_paths]

    output: list[dict[str, Any]] = []
    for index, path in enumerate(input_paths):
        if index >= len(rows):
            output.append(_skipped(path, "detector output omitted image row"))
            continue
        row = rows[index]
        if not isinstance(row, dict):
            output.append(_skipped(path, "detector image row must be an object"))
            continue
        if row.get("path") != path:
            output.append(_skipped(path, "detector image row path mismatch"))
            continue
        if row.get("error"):
            output.append(_skipped(path, f"detector image failed: {row['error']}"))
            continue
        try:
            photo_bytes = Path(path).read_bytes()
            detections = normalize_detections(
                row.get("detections"), photo_bytes)
        except (OSError, DetectorError) as exc:
            output.append(_skipped(path, str(exc)))
            continue
        output.append({
            "path": path,
            "status": "success",
            "reason": None,
            "detections": detections,
        })
    return output


def write_crop(
    image_path: str,
    detection: Mapping[str, Any],
    crop_root: str,
) -> str:
    """Encode and atomically write one content-addressed JPEG/PNG crop."""
    crop_id = detection.get("crop_id")
    if not isinstance(crop_id, str) or not crop_id.startswith(
            f"figcrop-{DETECTOR_CONTRACT_VERSION}-"):
        raise CropWriteError("detection has invalid crop_id")
    box = _normalized_box(detection.get("box"))
    root = Path(crop_root)
    digest = crop_id.rsplit("-", 1)[-1]

    try:
        with Image.open(image_path) as source:
            width, height = source.size
            pixels = (
                math.floor(box[0] * width),
                math.floor(box[1] * height),
                math.ceil(box[2] * width),
                math.ceil(box[3] * height),
            )
            output_format = "PNG" if source.format == "PNG" else "JPEG"
            suffix = ".png" if output_format == "PNG" else ".jpg"
            relative = Path(digest[:2]) / f"{crop_id}{suffix}"
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(
                prefix=f".{crop_id}-", suffix=".tmp",
                dir=destination.parent,
            )
            os.close(handle)
            temp = Path(temp_name)
            try:
                crop = source.crop(pixels)
                if output_format == "JPEG":
                    crop = crop.convert("RGB")
                    crop.save(
                        temp,
                        format="JPEG",
                        quality=95,
                        subsampling=0,
                        optimize=False,
                        progressive=False,
                    )
                else:
                    crop.save(
                        temp,
                        format="PNG",
                        optimize=False,
                        compress_level=9,
                    )
                os.replace(temp, destination)
            except Exception:
                temp.unlink(missing_ok=True)
                raise
    except Exception as exc:
        if isinstance(exc, CropWriteError):
            raise
        raise CropWriteError(f"crop write failed: {exc}") from exc

    return relative.as_posix()
