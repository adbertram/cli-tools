"""Brickognize legacy minifigure prediction adapter.

The deprecated provider endpoint is isolated here so the rest of LegoScout owns
stable, versioned evidence rather than provider request details.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence

import requests

from ..paths import BRICKOGNIZE_MINIFIG_CACHE
from . import json_cache

ENDPOINT = "https://api.brickognize.com/predict/figs/"
CONTRACT_VERSION = "brickognize-legacy-figs-v1"
USER_AGENT = "LegoScout/0.1 (+mailto:adam@brickbuddy.io)"
DEFAULT_TIMEOUT = 30.0
DEFAULT_WORKERS = 2
MAX_WORKERS = 2
RETRY_DELAYS = (0.25, 0.5)

PostFn = Callable[..., Any]
SleepFn = Callable[[float], None]
ExecutorFactory = Callable[..., Any]


class BrickognizeError(ValueError):
    """Base provider adapter error."""


class BrickognizeConfigurationError(BrickognizeError):
    """A request or scheduler option is outside the locked contract."""


class BrickognizeHTTPError(BrickognizeError):
    """The provider returned a non-success status."""


class BrickognizeSchemaError(BrickognizeError):
    """The provider or cache response violates the recorded schema."""


def _number(value: object, label: str, *, low: float, high: float) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(float(value))):
        raise BrickognizeSchemaError(f"{label} must be a finite number")
    normalized = float(value)
    if not low <= normalized <= high:
        raise BrickognizeSchemaError(f"{label} must be in {low:g}..{high:g}")
    return normalized


def validate_options(
    *,
    workers: int = DEFAULT_WORKERS,
    top_k: int = 10,
    min_similarity: float = 0.5,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
        raise BrickognizeConfigurationError(
            f"workers must be an integer in 1..{MAX_WORKERS}")
    if type(top_k) is not int or not 1 <= top_k <= 50:
        raise BrickognizeConfigurationError(
            "top_k must be an integer in 1..50")
    if (not isinstance(min_similarity, (int, float))
            or isinstance(min_similarity, bool)
            or not math.isfinite(float(min_similarity))
            or not 0.0 <= float(min_similarity) <= 1.0):
        raise BrickognizeConfigurationError(
            "min_similarity must be a finite number in 0..1")
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not math.isfinite(float(timeout)) or float(timeout) <= 0):
        raise BrickognizeConfigurationError(
            "timeout must be a positive finite number")


def crop_sha256(crop_bytes: bytes) -> str:
    return hashlib.sha256(crop_bytes).hexdigest()


def _contract(
    crop_bytes: bytes,
    *,
    endpoint: str,
    contract_version: str,
    top_k: int,
    min_similarity: float,
) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "contract_version": contract_version,
        "crop_sha256": crop_sha256(crop_bytes),
        "top_k_items": top_k,
        "min_similarity_items": float(min_similarity),
    }


def cache_key(
    crop_bytes: bytes,
    *,
    top_k: int,
    min_similarity: float,
    endpoint: str = ENDPOINT,
    contract_version: str = CONTRACT_VERSION,
) -> str:
    payload = json.dumps(_contract(
        crop_bytes,
        endpoint=endpoint,
        contract_version=contract_version,
        top_k=top_k,
        min_similarity=min_similarity,
    ), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "brickognize-v1-" + hashlib.sha256(payload).hexdigest()


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrickognizeSchemaError(f"{label} must be an object")
    return value


def _required_string(row: dict[str, Any], field: str, label: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise BrickognizeSchemaError(
            f"{label} {field} must be a non-empty string")
    return value


def _normalize_bounding_box(value: object) -> dict[str, float]:
    row = _required_object(value, "bounding_box")
    required = {
        "left", "upper", "right", "lower",
        "image_width", "image_height", "score",
    }
    missing = sorted(required - set(row))
    if missing:
        raise BrickognizeSchemaError(
            f"bounding_box missing fields: {', '.join(missing)}")
    normalized = {
        name: _number(row[name], f"bounding_box {name}", low=0.0,
                      high=1.0 if name == "score" else float("inf"))
        for name in required
    }
    if normalized["right"] < normalized["left"]:
        raise BrickognizeSchemaError("bounding_box right must be >= left")
    if normalized["lower"] < normalized["upper"]:
        raise BrickognizeSchemaError("bounding_box lower must be >= upper")
    return normalized


def _normalize_external_sites(value: object, index: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise BrickognizeSchemaError(
            f"item {index} external_sites must be an array")
    sites = []
    for site_index, raw in enumerate(value):
        row = _required_object(
            raw, f"item {index} external_sites[{site_index}]")
        _required_string(row, "name", f"item {index} external site")
        _required_string(row, "url", f"item {index} external site")
        sites.append(copy.deepcopy(row))
    return sites


def _normalize_item(value: object, index: int) -> dict[str, Any]:
    row = _required_object(value, f"item {index}")
    _required_string(row, "id", "item")
    _required_string(row, "name", f"item {index}")
    _required_string(row, "img_url", f"item {index}")
    item_type = _required_string(row, "type", f"item {index}")
    if item_type != "fig":
        raise BrickognizeSchemaError(
            f"item {index} type must be 'fig'")
    category = row.get("category")
    if category is not None and not isinstance(category, str):
        raise BrickognizeSchemaError(
            f"item {index} category must be a string or null")
    _number(row.get("score"), f"item {index} score", low=0.0, high=1.0)
    _normalize_external_sites(row.get("external_sites"), index)
    return copy.deepcopy(row)


def normalize_response(payload: object) -> dict[str, Any]:
    """Validate one recorded/live legacy-search response without reshaping it."""
    row = _required_object(payload, "response")
    _required_string(row, "listing_id", "response")
    _normalize_bounding_box(row.get("bounding_box"))
    items = row.get("items")
    if not isinstance(items, list):
        raise BrickognizeSchemaError("response items must be an array")
    for index, item in enumerate(items):
        _normalize_item(item, index)
    return copy.deepcopy(row)


def _mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    raise BrickognizeConfigurationError(
        "query_image crop must be JPEG or PNG")


def _transient_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def _request_bytes(
    path: Path,
    crop_bytes: bytes,
    *,
    top_k: int,
    min_similarity: float,
    timeout: float,
    post: PostFn,
    sleep: SleepFn,
) -> dict[str, Any]:
    mime = _mime(path)
    transient_exceptions = (requests.Timeout, requests.ConnectionError)
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            response = post(
                ENDPOINT,
                params={
                    "top_k_items": top_k,
                    "min_similarity_items": float(min_similarity),
                },
                files=[("query_image", (path.name, crop_bytes, mime))],
                headers={"User-Agent": USER_AGENT},
                timeout=float(timeout),
            )
        except transient_exceptions as exc:
            if attempt < len(RETRY_DELAYS):
                sleep(RETRY_DELAYS[attempt])
                continue
            raise BrickognizeHTTPError(
                f"provider request failed after {attempt + 1} attempts: "
                f"{type(exc).__name__}: {exc}") from exc

        status = getattr(response, "status_code", None)
        if not isinstance(status, int):
            raise BrickognizeHTTPError(
                "provider response has no integer status_code")
        if status != 200:
            if _transient_status(status) and attempt < len(RETRY_DELAYS):
                sleep(RETRY_DELAYS[attempt])
                continue
            raise BrickognizeHTTPError(
                f"provider returned HTTP {status} after {attempt + 1} attempts")
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise BrickognizeSchemaError(
                f"provider response is not valid JSON: {exc}") from exc
        normalized = normalize_response(payload)
        return {
            "contract": _contract(
                crop_bytes,
                endpoint=ENDPOINT,
                contract_version=CONTRACT_VERSION,
                top_k=top_k,
                min_similarity=min_similarity,
            ),
            "response": normalized,
        }
    raise AssertionError("retry loop exhausted without returning or raising")


def request_prediction(
    crop_path: str | Path,
    *,
    top_k: int = 10,
    min_similarity: float = 0.5,
    timeout: float = DEFAULT_TIMEOUT,
    post: PostFn = requests.post,
    sleep: SleepFn = time.sleep,
) -> dict[str, Any]:
    validate_options(
        workers=DEFAULT_WORKERS,
        top_k=top_k,
        min_similarity=min_similarity,
        timeout=timeout,
    )
    path = Path(crop_path)
    try:
        crop_bytes = path.read_bytes()
    except OSError as exc:
        raise BrickognizeConfigurationError(
            f"unable to read crop {path}: {type(exc).__name__}: {exc}") from exc
    return _request_bytes(
        path,
        crop_bytes,
        top_k=top_k,
        min_similarity=min_similarity,
        timeout=timeout,
        post=post,
        sleep=sleep,
    )


def _cached_prediction(
    value: object,
    *,
    expected_contract: dict[str, Any],
    cache_path: str,
) -> dict[str, Any]:
    try:
        row = _required_object(value, "cached prediction")
        contract = _required_object(row.get("contract"), "cached contract")
        if contract != expected_contract:
            raise BrickognizeSchemaError(
                "cached contract does not match its content-addressed key")
        response = normalize_response(row.get("response"))
        return {"contract": copy.deepcopy(contract), "response": response}
    except BrickognizeSchemaError as exc:
        raise json_cache.CorruptCache(
            f"Cache entry in {cache_path} violates the Brickognize contract: "
            f"{exc}") from exc


def predict_many(
    crop_paths: Sequence[str],
    *,
    workers: int = DEFAULT_WORKERS,
    top_k: int = 10,
    min_similarity: float = 0.5,
    timeout: float = DEFAULT_TIMEOUT,
    cache_path: str = BRICKOGNIZE_MINIFIG_CACHE,
    post: PostFn = requests.post,
    sleep: SleepFn = time.sleep,
    executor_factory: ExecutorFactory = ThreadPoolExecutor,
) -> list[dict[str, Any]]:
    """Resolve cache hits, then schedule only misses with at most two workers."""
    validate_options(
        workers=workers,
        top_k=top_k,
        min_similarity=min_similarity,
        timeout=timeout,
    )
    cache = json_cache.read(cache_path)
    rows: list[dict[str, Any] | None] = [None] * len(crop_paths)
    misses = []
    for index, raw_path in enumerate(crop_paths):
        path = Path(raw_path)
        try:
            crop_bytes = path.read_bytes()
            _mime(path)
        except (OSError, BrickognizeConfigurationError) as exc:
            rows[index] = {
                "path": str(path),
                "status": "skipped",
                "reason": f"{type(exc).__name__}: {exc}",
                "cached": False,
                "prediction": None,
            }
            continue
        key = cache_key(
            crop_bytes,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        contract = _contract(
            crop_bytes,
            endpoint=ENDPOINT,
            contract_version=CONTRACT_VERSION,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        if key in cache:
            prediction = _cached_prediction(
                cache[key], expected_contract=contract, cache_path=cache_path)
            rows[index] = {
                "path": str(path),
                "status": "success",
                "reason": None,
                "cached": True,
                "prediction": prediction,
            }
        else:
            misses.append((index, path, crop_bytes, key))

    if misses:
        with executor_factory(max_workers=min(workers, len(misses))) as pool:
            futures = [(index, path, key, pool.submit(
                _request_bytes,
                path,
                crop_bytes,
                top_k=top_k,
                min_similarity=min_similarity,
                timeout=timeout,
                post=post,
                sleep=sleep,
            )) for index, path, crop_bytes, key in misses]
            for index, path, key, future in futures:
                try:
                    prediction = future.result()
                except Exception as exc:
                    rows[index] = {
                        "path": str(path),
                        "status": "skipped",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "cached": False,
                        "prediction": None,
                    }
                    continue
                json_cache.update(cache_path, {key: prediction})
                rows[index] = {
                    "path": str(path),
                    "status": "success",
                    "reason": None,
                    "cached": False,
                    "prediction": prediction,
                }

    if any(row is None for row in rows):
        raise AssertionError("prediction scheduler left an unresolved crop")
    return [row for row in rows if row is not None]
