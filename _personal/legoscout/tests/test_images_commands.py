from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from legoscout_cli.main import app
from legoscout_cli.pricing import deal_images, listing_images

runner = CliRunner()


def _noisy_jpeg_bytes(width=200, height=150) -> bytes:
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_download_batch_leaf_is_registered():
    result = runner.invoke(app, ["images", "download-batch", "--help"])
    assert result.exit_code == 0, result.output


def test_gc_leaf_is_registered():
    result = runner.invoke(app, ["images", "gc", "--help"])
    assert result.exit_code == 0, result.output


def test_download_batch_reads_records_and_writes_both_out_and_stdout(
        monkeypatch, tmp_path):
    body = _noisy_jpeg_bytes()

    def fake_fetch(url, dest=None):
        Path(dest).write_bytes(body)
        return "200", "image/jpeg"
    monkeypatch.setattr(listing_images, "fetch", fake_fetch)

    records = tmp_path / "records.json"
    records.write_text(json.dumps([
        {"listing_key": "ebay|1", "image_urls": ["https://example.test/a.jpg"]},
    ]))
    out = tmp_path / "out.json"

    result = runner.invoke(app, [
        "images", "download-batch",
        "--records", str(records),
        "--out", str(out),
        "--image-root", str(tmp_path / "store"),
    ])

    assert result.exit_code == 0, result.output
    written = json.loads(out.read_text())
    stdout_payload = json.loads(result.output)
    assert written == stdout_payload
    assert written[0]["listing_key"] == "ebay|1"
    assert written[0]["image_local_ids"][0] is not None
    assert Path(written[0]["image_local_paths"][0]).exists()


def test_download_batch_respects_max_images_flag(monkeypatch, tmp_path):
    body = _noisy_jpeg_bytes()

    def fake_fetch(url, dest=None):
        Path(dest).write_bytes(body)
        return "200", "image/jpeg"
    monkeypatch.setattr(listing_images, "fetch", fake_fetch)

    records = tmp_path / "records.json"
    records.write_text(json.dumps([
        {"listing_key": "ebay|1",
         "image_urls": ["https://example.test/%d.jpg" % i for i in range(4)]},
    ]))
    out = tmp_path / "out.json"

    result = runner.invoke(app, [
        "images", "download-batch",
        "--records", str(records),
        "--out", str(out),
        "--image-root", str(tmp_path / "store"),
        "--max-images", "1",
    ])

    assert result.exit_code == 0, result.output
    written = json.loads(out.read_text())
    statuses = [row["status"] for row in written[0]["image_results"]]
    assert statuses == ["saved", "skipped_limit", "skipped_limit", "skipped_limit"]


def test_download_batch_fails_loudly_on_malformed_records_file(tmp_path):
    records = tmp_path / "records.json"
    records.write_text("not json")

    result = runner.invoke(app, [
        "images", "download-batch",
        "--records", str(records),
        "--out", str(tmp_path / "out.json"),
        "--image-root", str(tmp_path / "store"),
    ])

    assert result.exit_code != 0
    assert not (tmp_path / "out.json").exists()


def test_download_batch_fails_loudly_on_missing_records_file(tmp_path):
    result = runner.invoke(app, [
        "images", "download-batch",
        "--records", str(tmp_path / "does-not-exist.json"),
        "--out", str(tmp_path / "out.json"),
        "--image-root", str(tmp_path / "store"),
    ])

    assert result.exit_code != 0


def test_gc_dry_run_reports_without_deleting(tmp_path):
    store = tmp_path / "store" / "ab"
    store.mkdir(parents=True)
    stale = store / "dealimg-old.webp"
    stale.write_bytes(b"data")
    old_time = time.time() - (deal_images.DEAL_IMAGE_RETENTION_DAYS + 1) * 86400
    os.utime(stale, (old_time, old_time))

    result = runner.invoke(app, [
        "images", "gc", "--image-root", str(tmp_path / "store"),
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["applied"] is False
    assert payload["expired"] == ["ab/dealimg-old.webp"]
    assert stale.exists()


def test_gc_apply_deletes_expired_files(tmp_path):
    store = tmp_path / "store" / "ab"
    store.mkdir(parents=True)
    stale = store / "dealimg-old.webp"
    stale.write_bytes(b"data")
    old_time = time.time() - (deal_images.DEAL_IMAGE_RETENTION_DAYS + 1) * 86400
    os.utime(stale, (old_time, old_time))

    result = runner.invoke(app, [
        "images", "gc", "--apply", "--image-root", str(tmp_path / "store"),
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["deleted"] == ["ab/dealimg-old.webp"]
    assert not stale.exists()
