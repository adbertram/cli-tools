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


def _fake_service_returning(channel_items):
    """Build a fake YouTube service whose channels().list returns channel_items."""

    class FakeRequest:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class FakeChannelsResource:
        def list(self, **kwargs):
            return FakeRequest({"items": channel_items})

    class FakeService:
        def channels(self):
            return FakeChannelsResource()

    class FakeClient:
        def get_youtube_service(self):
            return FakeService()

    return FakeClient()


def _channel_item(channel_id, title):
    return {
        "id": channel_id,
        "snippet": {"title": title, "customUrl": f"@{title.lower().replace(' ', '')}"},
        "statistics": {"subscriberCount": "1", "videoCount": "2", "viewCount": "3"},
        "contentDetails": {"relatedPlaylists": {"uploads": f"UU{channel_id}"}},
        "brandingSettings": {"image": {}},
    }


def _patch_profiles(monkeypatch, profile_channels, failing=None):
    """Wire up multi-profile aggregation.

    profile_channels: {profile_name: [channel_item, ...]}
    failing: {profile_name: exception_message} for profiles whose token errors.
    """
    failing = failing or {}
    monkeypatch.setattr(channels, "_all_profile_names", lambda: list(profile_channels.keys()))

    def fake_get_api_client(profile=None):
        if profile in failing:
            raise RuntimeError(failing[profile])
        return _fake_service_returning(profile_channels.get(profile, []))

    monkeypatch.setattr(channels, "get_api_client", fake_get_api_client)


def test_channels_list_aggregates_across_profiles(monkeypatch):
    _patch_profiles(
        monkeypatch,
        {
            "adam": [_channel_item("UC_ADAM", "Adam Bertram")],
            "brick": [_channel_item("UC_BRICK", "Brick Buddy")],
            "farm": [_channel_item("UC_FARM", "Geek Farm Life")],
        },
    )

    result = runner.invoke(app, ["channels", "list"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert {c["id"] for c in payload} == {"UC_ADAM", "UC_BRICK", "UC_FARM"}
    by_id = {c["id"]: c["profile"] for c in payload}
    assert by_id == {"UC_ADAM": "adam", "UC_BRICK": "brick", "UC_FARM": "farm"}


def test_channels_list_dedupes_channels_shared_across_profiles(monkeypatch):
    _patch_profiles(
        monkeypatch,
        {
            "brick_a": [_channel_item("UC_BRICK", "Brick Buddy")],
            "brick_b": [_channel_item("UC_BRICK", "Brick Buddy")],
        },
    )

    result = runner.invoke(app, ["channels", "list"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    # First profile wins the annotation.
    assert payload[0]["profile"] == "brick_a"


def test_aggregate_single_profile_skips_enumeration(monkeypatch):
    """When a profile is passed, only that profile is queried (no enumeration)."""
    called_profiles = []

    monkeypatch.setattr(
        channels,
        "_all_profile_names",
        lambda: (_ for _ in ()).throw(AssertionError("must not enumerate profiles")),
    )

    def fake_get_api_client(profile=None):
        called_profiles.append(profile)
        return _fake_service_returning([_channel_item("UC_FARM", "Geek Farm Life")])

    monkeypatch.setattr(channels, "get_api_client", fake_get_api_client)

    rows, errors = channels._aggregate_owned_channels("farm")

    assert errors == []
    assert len(rows) == 1
    assert rows[0]["profile"] == "farm"
    assert called_profiles == ["farm"]


def test_channels_list_reports_failing_profile_and_exits_nonzero(monkeypatch):
    _patch_profiles(
        monkeypatch,
        {
            "good": [_channel_item("UC_GOOD", "Good Channel")],
            "bad": [],
        },
        failing={"bad": "invalid_grant: Token has been expired or revoked."},
    )

    result = runner.invoke(app, ["channels", "list"])

    # Good channel still returned, but failure is reported loudly and exit is nonzero.
    assert result.exit_code == 1
    assert "Profile 'bad' failed" in result.stderr
    assert "expired or revoked" in result.stderr
    payload = json.loads(result.stdout)
    assert [c["id"] for c in payload] == ["UC_GOOD"]


def test_channels_list_aggregated_limit_caps_total(monkeypatch):
    _patch_profiles(
        monkeypatch,
        {
            "a": [_channel_item("UC_A", "A")],
            "b": [_channel_item("UC_B", "B")],
            "c": [_channel_item("UC_C", "C")],
        },
    )

    result = runner.invoke(app, ["channels", "list", "--limit", "2"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 2


def test_channels_get_searches_across_profiles(monkeypatch):
    _patch_profiles(
        monkeypatch,
        {
            "adam": [_channel_item("UC_ADAM", "Adam Bertram")],
            "farm": [_channel_item("UC_FARM", "Geek Farm Life")],
        },
    )

    result = runner.invoke(app, ["channels", "get", "UC_FARM"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["id"] == "UC_FARM"
    assert payload["profile"] == "farm"


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
