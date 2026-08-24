import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

from legoscout_cli.pricing import listing_images


def test_normalize_image_url_replaces_shopgoodwill_path_separators():
    raw = (
        "https://shopgoodwillimages.azureedge.net/production/8\\Item\\"
        "2026-08-08\\052d2241-74d3-4b3a-b275-061fb9e84f0fenco_08081.jpg"
    )

    assert listing_images.normalize_image_url(raw) == (
        "https://shopgoodwillimages.azureedge.net/production/8/Item/"
        "2026-08-08/052d2241-74d3-4b3a-b275-061fb9e84f0fenco_08081.jpg"
    )


def _run_image_fetch(monkeypatch, capsys, tmp_path, urls, responses,
                     body=b"x" * 8001, expected_exit=0):
    def fake_fetch(url, dest=None):
        code, content_type = responses[url]
        if code == "200":
            assert dest is not None
            Path(dest).write_bytes(body[url] if isinstance(body, dict) else body)
        return code, content_type

    argv = ["listing_images", "--urls", *urls]

    monkeypatch.setattr(listing_images, "OUT_ROOT", str(tmp_path))
    monkeypatch.setattr(listing_images, "fetch", fake_fetch)
    monkeypatch.setattr(sys, "argv", argv)

    assert listing_images.main() == expected_exit
    return json.loads(capsys.readouterr().out)


def test_explicit_urls_are_not_limited_by_the_default_cap(monkeypatch, capsys,
                                                            tmp_path):
    urls = ["https://images.example.test/%s.webp" % number
            for number in range(15)]
    payload = _run_image_fetch(
        monkeypatch, capsys, tmp_path, urls,
        {url: ("200", "image/webp") for url in urls})

    assert payload["count"] == len(urls)
    assert len(payload["images"]) == len(urls)
    assert [result["source_url"] for result in payload["results"]] == urls
    assert {result["status"] for result in payload["results"]} == {"saved"}


def test_image_results_report_each_url_that_fails(monkeypatch, capsys,
                                                   tmp_path):
    saved = "https://images.example.test/saved.webp"
    failed = "https://images.example.test/failed.webp"
    payload = _run_image_fetch(
        monkeypatch, capsys, tmp_path, [saved, failed],
        {saved: ("200", "image/webp"), failed: ("404", "text/html")})

    assert [result["source_url"] for result in payload["results"]] == [
        saved, failed]
    assert [result["status"] for result in payload["results"]] == [
        "saved", "failed"]


def test_small_valid_thumbnail_is_skipped_not_failed(monkeypatch, capsys,
                                                      tmp_path):
    thumbnail = "https://images.example.test/thumbnail.webp"
    product = "https://images.example.test/product.webp"
    payload = _run_image_fetch(
        monkeypatch, capsys, tmp_path, [thumbnail, product],
        {thumbnail: ("200", "image/webp"), product: ("200", "image/webp")},
        body={thumbnail: b"x" * 6218, product: b"x" * 8001})

    assert payload["count"] == 1
    assert [result["status"] for result in payload["results"]] == [
        "skipped_thumbnail", "saved"]
    assert payload["results"][0]["bytes"] == 6218
    assert not list(Path(payload["dir"]).glob("*thumbnail.webp"))


def _large_jpeg_bytes():
    image = Image.effect_noise((512, 512), 100).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_generic_mime_accepts_decoder_verified_jpeg(monkeypatch, capsys,
                                                     tmp_path):
    url = "https://shopgoodwillimages.example.test/lot.jpg"
    jpeg_bytes = _large_jpeg_bytes()

    assert len(jpeg_bytes) > 67 * 1024
    payload = _run_image_fetch(
        monkeypatch, capsys, tmp_path, [url],
        {url: ("200", "application/octet-stream")}, body=jpeg_bytes)

    assert payload["count"] == 1
    assert payload["results"][0]["status"] == "saved"
    assert payload["images"][0].endswith(".jpg")


def test_generic_mime_rejects_non_image_bytes(monkeypatch, capsys, tmp_path):
    url = "https://images.example.test/not-an-image.jpg"
    payload = _run_image_fetch(
        monkeypatch, capsys, tmp_path, [url],
        {url: ("200", "application/octet-stream")}, body=b"x" * 70000,
        expected_exit=1)

    assert payload["images"] == []
    assert payload["results"][0]["status"] == "failed"
    assert "verified generic image bytes" in payload["results"][0]["error"]


def test_fetch_failure_reports_json_and_exits_nonzero(monkeypatch, capsys,
                                                       tmp_path):
    url = "https://images.example.test/failure.webp"

    def failed_fetch(_url, dest=None):
        assert dest is not None
        raise listing_images.FetchError("curl exited 6 for the image")

    monkeypatch.setattr(listing_images, "OUT_ROOT", str(tmp_path))
    monkeypatch.setattr(listing_images, "fetch", failed_fetch)
    monkeypatch.setattr(sys, "argv", ["listing_images", "--urls", url])

    assert listing_images.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0
    assert payload["results"] == [{
        "source_url": url,
        "normalized_url": url,
        "status": "failed",
        "http_status": None,
        "content_type": None,
        "bytes": 0,
        "error": "curl exited 6 for the image",
    }]


def test_joined_urls_are_rejected_before_fetch(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(listing_images, "OUT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        listing_images, "fetch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a joined URL reached fetch")))
    monkeypatch.setattr(sys, "argv", [
        "listing_images", "--urls",
        "https://images.example.test/a.jpg\thttps://images.example.test/b.jpg"])

    assert listing_images.main() == 1
    assert "one URL with no whitespace" in capsys.readouterr().err
