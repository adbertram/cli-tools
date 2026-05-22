"""Tests for local eBay storage behavior."""

import json

from ebay_cli import storage


def _configure_storage_paths(monkeypatch, tmp_path):
    storage_dir = tmp_path / ".ebay"
    monkeypatch.setattr(storage, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(storage, "IMAGES_FILE", storage_dir / "images.json")
    monkeypatch.setattr(storage, "TEMPLATES_FILE", storage_dir / "templates.json")
    monkeypatch.setattr(storage, "DRAFTS_FILE", storage_dir / "drafts.json")
    return storage_dir


def test_get_all_images_prunes_expired_records(monkeypatch, tmp_path):
    storage_dir = _configure_storage_paths(monkeypatch, tmp_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage.IMAGES_FILE.write_text(
        json.dumps(
            {
                "images": [
                    {
                        "image_id": "expired",
                        "imageUrl": "https://example.com/expired.jpg",
                        "expirationDate": "2026-01-01T00:00:00Z",
                        "source": "file",
                        "original": "/tmp/expired.jpg",
                        "uploaded_at": "2025-12-01T00:00:00Z",
                    },
                    {
                        "image_id": "active",
                        "imageUrl": "https://example.com/active.jpg",
                        "expirationDate": "2099-12-31T00:00:00Z",
                        "source": "file",
                        "original": "/tmp/active.jpg",
                        "uploaded_at": "2026-05-01T00:00:00Z",
                    },
                ]
            }
        )
    )

    image_storage = storage.ImageStorage()

    images = image_storage.get_all_images()

    assert images == [
        {
            "image_id": "active",
            "imageUrl": "https://example.com/active.jpg",
            "expirationDate": "2099-12-31T00:00:00Z",
            "source": "file",
            "original": "/tmp/active.jpg",
            "uploaded_at": "2026-05-01T00:00:00Z",
        }
    ]
    assert json.loads(storage.IMAGES_FILE.read_text()) == {"images": images}


def test_get_image_skips_expired_records(monkeypatch, tmp_path):
    storage_dir = _configure_storage_paths(monkeypatch, tmp_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage.IMAGES_FILE.write_text(
        json.dumps(
            {
                "images": [
                    {
                        "image_id": "expired",
                        "imageUrl": "https://example.com/expired.jpg",
                        "expirationDate": "2026-01-01T00:00:00Z",
                        "source": "file",
                        "original": "/tmp/expired.jpg",
                        "uploaded_at": "2025-12-01T00:00:00Z",
                    }
                ]
            }
        )
    )

    image_storage = storage.ImageStorage()

    assert image_storage.get_image("expired") is None
    assert json.loads(storage.IMAGES_FILE.read_text()) == {"images": []}
