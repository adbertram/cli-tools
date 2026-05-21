import json
import random

import pytest
from typer.testing import CliRunner
from PIL import Image

from youtube_cli.main import app
from youtube_cli.commands import channels
from youtube_cli.banner_images import (
    MAX_BANNER_BYTES,
    RECOMMENDED_BANNER_HEIGHT,
    RECOMMENDED_BANNER_WIDTH,
    prepare_banner_image,
)


runner = CliRunner()


def _save_image(path, size, image_format, color="navy", data=None):
    if data is None:
        image = Image.new("RGB", size, color)
    else:
        image = Image.frombytes("RGB", size, data)
    image.save(path, format=image_format)


def test_channels_create_help_lists_command():
    result = runner.invoke(app, ["channels", "create", "--help"])

    assert result.exit_code == 0
    assert "Explain how to create a YouTube channel" in result.stdout


def test_channels_create_fails_with_actionable_error():
    result = runner.invoke(app, ["channels", "create"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Creating YouTube channels is not supported by the YouTube Data API v3." in result.stderr
    assert "https://support.google.com/youtube/answer/1646861" in result.stderr


def test_channels_update_help_lists_banner_option():
    result = runner.invoke(app, ["channels", "update", "--help"])

    assert result.exit_code == 0
    assert "--banner-image" in result.stdout


def test_prepare_banner_image_rejects_too_small_image(tmp_path):
    banner_path = tmp_path / "small-banner.png"
    _save_image(banner_path, (2047, 1152), "PNG")

    with pytest.raises(ValueError) as excinfo:
        prepare_banner_image(banner_path)

    assert "Banner image is too small" in str(excinfo.value)
    assert "2047x1152" in str(excinfo.value)


def test_prepare_banner_image_normalizes_oversized_dimensions(tmp_path):
    banner_path = tmp_path / "oversized-banner.png"
    _save_image(banner_path, (4000, 3000), "PNG")

    prepared = prepare_banner_image(banner_path)

    assert prepared.path != banner_path
    assert prepared.mime_type == "image/jpeg"
    assert prepared.normalized is True
    with Image.open(prepared.path) as adjusted:
        assert adjusted.size == (RECOMMENDED_BANNER_WIDTH, RECOMMENDED_BANNER_HEIGHT)


def test_prepare_banner_image_compresses_oversized_file_under_limit(tmp_path):
    banner_path = tmp_path / "oversized-file.png"
    random_bytes = random.Random(0).randbytes(3200 * 1800 * 3)
    _save_image(banner_path, (3200, 1800), "PNG", data=random_bytes)

    assert banner_path.stat().st_size > MAX_BANNER_BYTES

    prepared = prepare_banner_image(banner_path)

    assert prepared.path.stat().st_size <= MAX_BANNER_BYTES
    with Image.open(prepared.path) as adjusted:
        assert adjusted.size == (RECOMMENDED_BANNER_WIDTH, RECOMMENDED_BANNER_HEIGHT)


def test_channels_update_fails_before_api_call_for_too_small_banner(monkeypatch, tmp_path):
    banner_path = tmp_path / "small-banner.png"
    _save_image(banner_path, (2047, 1152), "PNG")

    monkeypatch.setattr(
        channels,
        "get_api_client",
        lambda profile=None: (_ for _ in ()).throw(AssertionError("API client should not be created")),
    )

    result = runner.invoke(
        app,
        ["channels", "update", "UC123", "--banner-image", str(banner_path)],
    )

    assert result.exit_code == 1
    assert "Banner image is too small" in result.stderr


def test_channels_update_uploads_banner_and_formats_partial_update_response(monkeypatch, tmp_path):
    banner_path = tmp_path / "banner.png"
    _save_image(
        banner_path,
        (RECOMMENDED_BANNER_WIDTH, RECOMMENDED_BANNER_HEIGHT),
        "PNG",
    )

    class FakeRequest:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class FakeChannelBannersResource:
        def __init__(self):
            self.media_body = None

        def insert(self, media_body):
            self.media_body = media_body
            return FakeRequest({"url": "https://yt3.googleusercontent.com/banner-uploaded"})

    class FakeChannelsResource:
        def __init__(self):
            self.updated_body = None
            self.updated_part = None

        def list(self, **kwargs):
            return FakeRequest(
                {
                    "items": [
                        {
                            "id": "UC123",
                            "snippet": {"title": "Brick Channel", "customUrl": "@brick"},
                            "statistics": {"subscriberCount": "5", "videoCount": "2", "viewCount": "10"},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
                            "brandingSettings": {
                                "channel": {"title": "Brick Channel", "description": "Existing description"},
                                "image": {"bannerMobileImageUrl": "https://example.com/mobile"},
                            },
                        }
                    ]
                }
            )

        def update(self, *, part, body):
            self.updated_part = part
            self.updated_body = body
            return FakeRequest(
                {
                    "id": body["id"],
                    "brandingSettings": body["brandingSettings"],
                }
            )

    class FakeService:
        def __init__(self):
            self.channels_resource = FakeChannelsResource()
            self.channel_banners_resource = FakeChannelBannersResource()

        def channels(self):
            return self.channels_resource

        def channelBanners(self):
            return self.channel_banners_resource

    class FakeClient:
        def __init__(self, service):
            self.service = service

        def get_youtube_service(self):
            return self.service

    service = FakeService()
    monkeypatch.setattr(channels, "get_api_client", lambda profile=None: FakeClient(service))

    result = runner.invoke(
        app,
        ["channels", "update", "UC123", "--banner-image", str(banner_path)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["id"] == "UC123"
    assert payload["banner_external_url"] == "https://yt3.googleusercontent.com/banner-uploaded"
    assert service.channels_resource.updated_part == "brandingSettings"
    assert service.channels_resource.updated_body["brandingSettings"]["channel"]["description"] == "Existing description"
    assert (
        service.channels_resource.updated_body["brandingSettings"]["image"]["bannerMobileImageUrl"]
        == "https://example.com/mobile"
    )
    assert (
        service.channels_resource.updated_body["brandingSettings"]["image"]["bannerExternalUrl"]
        == "https://yt3.googleusercontent.com/banner-uploaded"
    )
    assert service.channel_banners_resource.media_body._filename == str(banner_path)
    assert service.channel_banners_resource.media_body.mimetype() == "image/png"
