"""Persistent, space-bounded storage for scraped listing photos, keyed to a deal.

`legoscout pricing images` (`listing_images.py`) fetches a listing's photos into
disposable per-run scratch so an agent can read a set number off a box; nothing
about that pass survives the run or ties back to the ledger. This module is the
downstream, deterministic step that runs once per classifier batch -- after
triage has already narrowed the crawl to the listings actually worth pricing --
and saves each one's photos permanently enough to reference from the ledger,
without saving so much that the store grows without bound:

  * Every photo is downscaled to at most `DEAL_IMAGE_MAX_DIMENSION` px on its
    long edge and re-encoded as WebP at `DEAL_IMAGE_WEBP_QUALITY` -- a multi-MB
    CDN original becomes tens of KB, with no loss that matters for reading a
    set number or counting minifigures in a photo.
  * Only the first `DEAL_IMAGE_MAX_PER_LISTING` photos of a listing are fetched
    at all -- enough for the classifier's own use, not a mirror of every angle
    a seller posted.
  * Storage is content-addressed (`legoscout_cli.pricing.content_store`), the
    same mechanic `minifig_detector.write_crop` uses -- identical bytes land at
    the same path once, however many listings show the same photo.
  * Nothing here is permanent. `gc()` deletes any file whose mtime is older
    than `DEAL_IMAGE_RETENTION_DAYS`; `write_image` always re-fetches and
    rewrites rather than checking for a cache hit, so a listing that's still
    being priced every run keeps its mtime fresh for free, and one that
    stops appearing ages out on its own.

    legoscout images download-batch --records batch.json --out result.json
    legoscout images gc --older-than-days 14 --apply
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from . import content_store
from . import listing_images
from .minifig_identification import run_batch_stage

DEAL_IMAGE_MAX_DIMENSION = 1600
DEAL_IMAGE_WEBP_QUALITY = 82
# One retry quality, used only when the primary quality doesn't shrink the
# source. Live-traffic smoke testing (2026-09-07) found Craigslist serves an
# already-resized, already-well-compressed 555x450 JPEG that re-encoded LARGER
# at quality 82 (59128 -> 65066 bytes, +10%) -- it's well under
# DEAL_IMAGE_MAX_DIMENSION so nothing downscales, and its own JPEG encoder had
# already done a comparable job. Quality 70 reliably wins on that exact photo
# (48848 bytes, 83% of the original); see downscale_and_encode.
DEAL_IMAGE_WEBP_FALLBACK_QUALITY = 70
# Pillow's slower, denser WebP compression effort -- same quality target,
# smaller output, no correctness tradeoff. Free on every image, not just the
# fallback case.
DEAL_IMAGE_WEBP_METHOD = 6
DEAL_IMAGE_MAX_PER_LISTING = 8
DEAL_IMAGE_RETENTION_DAYS = 14

# The floor `listing_images.discover_and_fetch` already uses to tell a real
# photo from a thumbnail/sprite -- reused so the two tools agree on what
# counts as "an actual product photo," not two independently-tuned numbers.
MIN_RAW_BYTES = 8000


class DealImageError(RuntimeError):
    """A download-batch record was malformed."""


def stable_image_id(webp_bytes: bytes) -> str:
    """Content-addressed ID of the STORED (downscaled, re-encoded) bytes."""
    return f"dealimg-{hashlib.sha256(webp_bytes).hexdigest()}"


def downscale_and_encode(
    raw_bytes: bytes,
    max_dimension: int = DEAL_IMAGE_MAX_DIMENSION,
    quality: int = DEAL_IMAGE_WEBP_QUALITY,
) -> bytes:
    """Downscale-only (never upscale) to `max_dimension` and WebP-encode.

    Retries once at `DEAL_IMAGE_WEBP_FALLBACK_QUALITY` when the primary
    quality doesn't beat the source's own byte count, and keeps whichever
    encoding is smaller -- a source already at or under `max_dimension` and
    already efficiently compressed (nothing to downscale, little redundancy
    left for WebP to find) can otherwise come out larger than it went in.
    Not a hard guarantee against every pathological input, just the fix for
    the case measured live.
    """
    with Image.open(io.BytesIO(raw_bytes)) as source:
        image = source.convert("RGB") if source.mode not in ("RGB", "RGBA") else source
        image = image.copy()
    image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    def _encode(q: int) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=q, method=DEAL_IMAGE_WEBP_METHOD)
        return buffer.getvalue()

    encoded = _encode(quality)
    if len(encoded) >= len(raw_bytes) and quality > DEAL_IMAGE_WEBP_FALLBACK_QUALITY:
        fallback = _encode(DEAL_IMAGE_WEBP_FALLBACK_QUALITY)
        if len(fallback) < len(encoded):
            encoded = fallback
    return encoded


def write_image(webp_bytes: bytes, image_root: str) -> str:
    """Content-addressed atomic write; always writes, no existence check."""
    image_id = stable_image_id(webp_bytes)
    digest = image_id.rsplit("-", 1)[-1]
    return content_store.write_sharded(
        image_root, digest, image_id, ".webp",
        lambda temp: temp.write_bytes(webp_bytes))


def _fetch_one(url: str, tmp_path: str) -> dict[str, Any]:
    """Fetch, verify, downscale, and store one photo URL. Never raises."""
    source_url = url
    normalized = listing_images.normalize_image_url(url)
    try:
        code, content_type = listing_images.fetch(normalized, dest=tmp_path)
    except listing_images.FetchError as exc:
        return {"url": source_url, "status": "failed", "error": str(exc),
                "image_local_id": None, "image_local_path": None}

    extension = listing_images.EXTENSION_BY_TYPE.get(content_type)
    if code == "200" and content_type == "application/octet-stream":
        extension = listing_images.verified_generic_image_extension(tmp_path)
    raw_bytes = Path(tmp_path).read_bytes() if os.path.exists(tmp_path) else b""

    if not (code == "200" and extension and len(raw_bytes) > MIN_RAW_BYTES):
        reason = ("need HTTP 200, a supported image Content-Type or verified "
                  "generic image bytes, and more than %d bytes" % MIN_RAW_BYTES)
        status = "skipped_thumbnail" if code == "200" and extension else "failed"
        return {"url": source_url, "status": status, "error": reason,
                "image_local_id": None, "image_local_path": None}

    try:
        webp_bytes = downscale_and_encode(raw_bytes)
    except (UnidentifiedImageError, OSError) as exc:
        return {"url": source_url, "status": "failed",
                "error": f"could not decode/re-encode image: {exc}",
                "image_local_id": None, "image_local_path": None}

    return {
        "url": source_url,
        "status": "saved",
        "error": None,
        "image_local_id": stable_image_id(webp_bytes),
        "webp_bytes": webp_bytes,
        "original_bytes": len(raw_bytes),
        "stored_bytes": len(webp_bytes),
    }


def _download_one_record(
    record: dict[str, Any],
    image_root: str,
    max_images_per_listing: int,
) -> dict[str, Any]:
    listing_key = record.get("listing_key")
    if not isinstance(listing_key, str) or not listing_key:
        raise DealImageError("record missing a non-empty listing_key")
    urls = record.get("image_urls") or []
    if not isinstance(urls, list):
        raise DealImageError(f"{listing_key}: image_urls must be an array")

    image_results: list[dict[str, Any]] = []
    for index, url in enumerate(urls):
        if index >= max_images_per_listing:
            image_results.append({
                "url": url, "status": "skipped_limit",
                "error": "not fetched because of the per-listing image cap "
                         "(%d)" % max_images_per_listing,
                "image_local_id": None, "image_local_path": None,
            })
            continue
        if not isinstance(url, str) or not url.strip():
            image_results.append({
                "url": url, "status": "failed", "error": "not a usable URL",
                "image_local_id": None, "image_local_path": None,
            })
            continue
        # `mkstemp` guarantees a unique path -- `download_batch` runs several
        # listings concurrently (`workers`), and a name built from just the
        # PID and image index collided across threads downloading their own
        # listing's first photo at the same time.
        handle, handle_path = tempfile.mkstemp(prefix="legoscout-dealimg-")
        os.close(handle)
        try:
            row = _fetch_one(url, handle_path)
        finally:
            if os.path.exists(handle_path):
                os.remove(handle_path)
        if row.get("status") == "saved":
            relative = write_image(row.pop("webp_bytes"), image_root)
            row["image_local_path"] = os.path.join(image_root, relative)
        image_results.append(row)

    return {
        "listing_key": listing_key,
        "status": "success",
        "reason": None,
        "image_local_ids": [row["image_local_id"] for row in image_results],
        "image_local_paths": [row["image_local_path"] for row in image_results],
        "image_results": image_results,
    }


def download_batch(
    records: list[dict[str, Any]],
    image_root: str,
    max_images_per_listing: int = DEAL_IMAGE_MAX_PER_LISTING,
    workers: int = 4,
) -> list[dict[str, Any]]:
    """Download, downscale, and persist every record's capped photo set.

    `records` is `[{"listing_key": ..., "image_urls": [...]}]`. Returns one
    result per input record, order preserved; a malformed record is isolated
    as a `blocked` result (via `run_batch_stage`) rather than aborting its
    siblings. `image_local_ids`/`image_local_paths` are positionally parallel
    to that record's `image_urls`; `image_local_ids` is what the ledger
    stores, `image_local_paths` is what an agent's Read tool can open.
    """
    if not isinstance(records, list):
        raise DealImageError("records must be a JSON array")
    report = run_batch_stage(
        "download_deal_images",
        records,
        process_one=lambda record: _download_one_record(
            record, image_root, max_images_per_listing),
        workers=max(1, workers),
        output_path=None,
    )
    return report["results"]


def gc(
    image_root: str,
    older_than_days: int = DEAL_IMAGE_RETENTION_DAYS,
    apply: bool = False,
) -> dict[str, Any]:
    """Report (and, with `apply`, delete) deal images older than the TTL."""
    root = Path(image_root)
    cutoff = time.time() - older_than_days * 86400
    scanned, expired, deleted = 0, [], []
    if root.is_dir():
        for path in root.rglob("*.webp"):
            scanned += 1
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                relative = path.relative_to(root).as_posix()
                expired.append(relative)
                if apply:
                    path.unlink(missing_ok=True)
                    deleted.append(relative)
    return {
        "image_root": str(root),
        "older_than_days": older_than_days,
        "applied": apply,
        "scanned": scanned,
        "expired": expired,
        "deleted": deleted if apply else [],
    }
