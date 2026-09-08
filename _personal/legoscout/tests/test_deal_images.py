from __future__ import annotations

import io
import os
import time
from pathlib import Path

import pytest
from PIL import Image

from legoscout_cli.pricing import deal_images


def _jpeg_bytes(width, height, *, noisy=True) -> bytes:
    """A JPEG of the given size. Noisy by default -- a solid-color JPEG this
    small compresses to under 1KB, well under MIN_RAW_BYTES, which made every
    "this should succeed" fixture read as an undersized thumbnail instead.
    Built from `os.urandom` (not a per-pixel Python loop, which took several
    seconds at 4000x2000); no assertion depends on reproducible pixels."""
    if noisy:
        image = Image.frombytes(
            "RGB", (width, height), os.urandom(width * height * 3))
    else:
        image = Image.new("RGB", (width, height), "red")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _fake_fetch(monkeypatch, body_by_url, content_type="image/jpeg"):
    def fake_fetch(url, dest=None):
        if url not in body_by_url:
            raise deal_images.listing_images.FetchError("no such fixture url: %s" % url)
        body = body_by_url[url]
        if body is None:
            return "404", ""
        Path(dest).write_bytes(body)
        return "200", content_type
    monkeypatch.setattr(deal_images.listing_images, "fetch", fake_fetch)


# --- downscale_and_encode ----------------------------------------------------

def test_downscale_and_encode_never_upscales_a_small_image():
    small = _jpeg_bytes(100, 80)
    encoded = deal_images.downscale_and_encode(small, max_dimension=1600)
    with Image.open(io.BytesIO(encoded)) as image:
        assert image.size == (100, 80)
        assert image.format == "WEBP"


FIXTURES = Path(__file__).parent / "fixtures" / "deal_images"


def test_downscale_and_encode_never_grows_an_already_small_well_compressed_source():
    # Regression: live smoke testing (2026-09-07) found a real Craigslist CDN
    # photo -- already resized to 555x450 (under the downscale cap) and
    # already efficiently JPEG-compressed -- came out LARGER at the default
    # WebP quality (59128 -> 65066 bytes, +10%). This is that exact photo (a
    # bulk LEGO lot, publicly crawled), which is what makes it reproduce: a
    # synthetic noise image compresses so much worse as JPEG that WebP always
    # looks artificially good against it.
    raw = (FIXTURES / "craigslist_already_compressed_thumbnail.jpg").read_bytes()
    encoded = deal_images.downscale_and_encode(raw)
    assert len(encoded) <= len(raw)


def test_downscale_and_encode_shrinks_a_large_image_to_the_cap():
    large = _jpeg_bytes(4000, 2000)
    encoded = deal_images.downscale_and_encode(large, max_dimension=1600)
    with Image.open(io.BytesIO(encoded)) as image:
        assert max(image.size) <= 1600
        assert image.size[0] / image.size[1] == pytest.approx(2.0, rel=0.02)


# --- stable_image_id / write_image -------------------------------------------

def test_write_image_is_content_addressed_and_deterministic(tmp_path):
    encoded = deal_images.downscale_and_encode(_jpeg_bytes(200, 150))
    first = deal_images.write_image(encoded, str(tmp_path))
    second = deal_images.write_image(encoded, str(tmp_path))

    assert first == second
    assert first.endswith(".webp")
    assert (tmp_path / first).read_bytes() == encoded


def test_write_image_rewrite_refreshes_mtime_for_gc_purposes(tmp_path):
    import os
    encoded = deal_images.downscale_and_encode(_jpeg_bytes(200, 150))
    relative = deal_images.write_image(encoded, str(tmp_path))
    destination = tmp_path / relative
    old_time = time.time() - 30 * 86400
    os.utime(destination, (old_time, old_time))

    deal_images.write_image(encoded, str(tmp_path))

    assert destination.stat().st_mtime > old_time + 1


# --- download_batch -----------------------------------------------------------

def test_download_batch_saves_downscaled_smaller_files_and_returns_paths(
        monkeypatch, tmp_path):
    raw = _jpeg_bytes(3000, 2000)
    _fake_fetch(monkeypatch, {"https://example.test/a.jpg": raw})

    results = deal_images.download_batch(
        [{"listing_key": "ebay|1", "image_urls": ["https://example.test/a.jpg"]}],
        str(tmp_path / "store"))

    assert len(results) == 1
    row = results[0]
    assert row["listing_key"] == "ebay|1"
    assert row["status"] == "success"
    assert len(row["image_local_ids"]) == 1
    assert row["image_local_ids"][0] is not None
    path = row["image_local_paths"][0]
    assert Path(path).exists()
    assert Path(path).stat().st_size < len(raw)
    with Image.open(path) as image:
        assert max(image.size) <= deal_images.DEAL_IMAGE_MAX_DIMENSION


def test_download_batch_returns_null_for_a_failed_url(monkeypatch, tmp_path):
    _fake_fetch(monkeypatch, {"https://example.test/missing.jpg": None})

    results = deal_images.download_batch(
        [{"listing_key": "ebay|1",
          "image_urls": ["https://example.test/missing.jpg"]}],
        str(tmp_path / "store"))

    row = results[0]
    assert row["image_local_ids"] == [None]
    assert row["image_local_paths"] == [None]
    assert row["image_results"][0]["status"] == "failed"


def test_download_batch_rejects_undersized_images_as_thumbnails(monkeypatch, tmp_path):
    tiny = _jpeg_bytes(10, 10, noisy=False)
    assert len(tiny) <= deal_images.MIN_RAW_BYTES
    _fake_fetch(monkeypatch, {"https://example.test/tiny.jpg": tiny})

    results = deal_images.download_batch(
        [{"listing_key": "ebay|1", "image_urls": ["https://example.test/tiny.jpg"]}],
        str(tmp_path / "store"))

    row = results[0]
    assert row["image_local_ids"] == [None]
    assert row["image_results"][0]["status"] == "skipped_thumbnail"


def test_download_batch_caps_images_per_listing(monkeypatch, tmp_path):
    raw = _jpeg_bytes(200, 150)
    urls = ["https://example.test/%d.jpg" % i for i in range(5)]
    _fake_fetch(monkeypatch, {url: raw for url in urls})

    results = deal_images.download_batch(
        [{"listing_key": "ebay|1", "image_urls": urls}],
        str(tmp_path / "store"), max_images_per_listing=2)

    row = results[0]
    assert row["image_results"][0]["status"] == "saved"
    assert row["image_results"][1]["status"] == "saved"
    for skipped in row["image_results"][2:]:
        assert skipped["status"] == "skipped_limit"
        assert skipped["image_local_id"] is None


def test_download_batch_treats_empty_image_urls_as_a_no_op(tmp_path):
    results = deal_images.download_batch(
        [{"listing_key": "ebay|1", "image_urls": []},
         {"listing_key": "ebay|2", "image_urls": None}],
        str(tmp_path / "store"))

    assert [row["status"] for row in results] == ["success", "success"]
    assert [row["image_local_ids"] for row in results] == [[], []]


def test_download_batch_isolates_a_malformed_record(monkeypatch, tmp_path):
    raw = _jpeg_bytes(200, 150)
    _fake_fetch(monkeypatch, {"https://example.test/a.jpg": raw})

    results = deal_images.download_batch(
        [{"listing_key": "ebay|1", "image_urls": ["https://example.test/a.jpg"]},
         {"image_urls": ["https://example.test/a.jpg"]}],  # missing listing_key
        str(tmp_path / "store"))

    assert results[0]["status"] == "success"
    assert results[1]["status"] == "blocked"


def test_download_batch_isolates_a_non_list_image_urls_field(tmp_path):
    results = deal_images.download_batch(
        [{"listing_key": "ebay|1", "image_urls": "not-a-list"}],
        str(tmp_path / "store"))

    assert results[0]["status"] == "blocked"
    assert results[0]["listing_key"] == "ebay|1"


def test_download_batch_deduplicates_identical_photos_across_listings(
        monkeypatch, tmp_path):
    raw = _jpeg_bytes(200, 150)
    _fake_fetch(monkeypatch, {
        "https://example.test/a.jpg": raw,
        "https://example.test/mirror.jpg": raw,
    })
    store = str(tmp_path / "store")

    results = deal_images.download_batch(
        [{"listing_key": "ebay|1", "image_urls": ["https://example.test/a.jpg"]},
         {"listing_key": "facebook|1",
          "image_urls": ["https://example.test/mirror.jpg"]}],
        store)

    assert results[0]["image_local_ids"] == results[1]["image_local_ids"]


def test_download_batch_rejects_non_list_records(tmp_path):
    with pytest.raises(deal_images.DealImageError):
        deal_images.download_batch({"listing_key": "ebay|1"}, str(tmp_path))


# --- gc -------------------------------------------------------------------

def test_gc_reports_without_deleting_by_default(tmp_path):
    store = tmp_path / "store" / "ab"
    store.mkdir(parents=True)
    stale = store / "dealimg-old.webp"
    stale.write_bytes(b"data")
    old_time = time.time() - (deal_images.DEAL_IMAGE_RETENTION_DAYS + 1) * 86400
    import os
    os.utime(stale, (old_time, old_time))

    report = deal_images.gc(str(tmp_path / "store"), apply=False)

    assert report["scanned"] == 1
    assert report["expired"] == ["ab/dealimg-old.webp"]
    assert report["deleted"] == []
    assert stale.exists()


def test_gc_deletes_only_expired_files_when_applied(tmp_path):
    store = tmp_path / "store" / "ab"
    store.mkdir(parents=True)
    fresh = store / "dealimg-fresh.webp"
    fresh.write_bytes(b"data")
    stale = store / "dealimg-old.webp"
    stale.write_bytes(b"data")
    old_time = time.time() - (deal_images.DEAL_IMAGE_RETENTION_DAYS + 1) * 86400
    import os
    os.utime(stale, (old_time, old_time))

    report = deal_images.gc(str(tmp_path / "store"), apply=True)

    assert report["deleted"] == ["ab/dealimg-old.webp"]
    assert fresh.exists()
    assert not stale.exists()


def test_gc_against_a_missing_root_does_not_crash(tmp_path):
    report = deal_images.gc(str(tmp_path / "never-created"), apply=True)
    assert report == {
        "image_root": str(tmp_path / "never-created"),
        "older_than_days": deal_images.DEAL_IMAGE_RETENTION_DAYS,
        "applied": True,
        "scanned": 0,
        "expired": [],
        "deleted": [],
    }
