"""Contract coverage for machine-readable eBay image uploads."""

import json
from unittest.mock import MagicMock

from typer.testing import CliRunner

from ebay_cli.commands import images
from ebay_cli.main import app


def _upload_response(index: int) -> dict:
    return {
        "image_id": f"image-{index}",
        "imageUrl": f"https://i.ebayimg.com/images/image-{index}.jpg",
        "expirationDate": "2026-12-31T00:00:00.000Z",
    }


def _stored_record(**kwargs) -> dict:
    return {
        "image_id": kwargs["image_id"],
        "imageUrl": kwargs["image_url"],
        "expirationDate": kwargs["expiration_date"],
        "source": kwargs["source"],
        "original": kwargs["original"],
    }


def test_image_upload_writes_all_uploaded_urls_as_json(monkeypatch):
    source_urls = [f"https://example.test/{index}.jpg" for index in range(24)]
    client = MagicMock()
    client.upload_image_from_url.side_effect = [_upload_response(index) for index in range(24)]
    storage = MagicMock()
    storage.add_image.side_effect = _stored_record
    monkeypatch.setattr(images, "get_client", lambda: client)
    monkeypatch.setattr(images, "ImageStorage", lambda: storage)

    result = CliRunner().invoke(
        app,
        [
            "seller", "images", "upload", "--url",
            ",".join(source_urls),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [record["imageUrl"] for record in payload["uploaded"]] == [
        f"https://i.ebayimg.com/images/image-{index}.jpg"
        for index in range(24)
    ]
    assert payload["errors"] == []
    assert payload["total_uploaded"] == 24
    assert payload["total_errors"] == 0
    assert client.upload_image_from_url.call_count == 24


def test_partial_file_upload_returns_json_and_fails(monkeypatch, tmp_path):
    paths = []
    for index in range(24):
        path = tmp_path / f"IMG_{index:04d}.jpeg"
        path.write_bytes(b"image")
        paths.append(path)

    client = MagicMock()
    client.upload_image_from_file.side_effect = [
        *[_upload_response(index) for index in range(20)],
        *[RuntimeError("media rejected image") for _ in range(4)],
    ]
    storage = MagicMock()
    storage.add_image.side_effect = _stored_record
    monkeypatch.setattr(images, "get_client", lambda: client)
    monkeypatch.setattr(images, "ImageStorage", lambda: storage)

    result = CliRunner().invoke(
        app,
        [
            "seller", "images", "upload", "--file",
            ",".join(str(path) for path in paths),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert [record["imageUrl"] for record in payload["uploaded"]] == [
        f"https://i.ebayimg.com/images/image-{index}.jpg"
        for index in range(20)
    ]
    assert payload["errors"] == [
        {"original": str(path), "error": "media rejected image"}
        for path in paths[20:]
    ]
    assert payload["total_uploaded"] == 20
    assert payload["total_errors"] == 4
    assert client.upload_image_from_file.call_count == 24
