"""Coverage for eBay listing video support (Media API)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ebay_cli import video as video_mod
from ebay_cli.commands import inventory, listings, videos
from ebay_cli.video import (
    MAX_VIDEO_BYTES,
    MAX_VIDEO_MB,
    VIDEO_EXTENSIONS,
    PreparedVideo,
    VideoError,
    _is_upload_compatible,
    prepare_video_for_upload,
)

MP4_CONTAINER = "mov,mp4,m4a,3gp,3g2,mj2"

# ffprobe stream layout of a real iPhone .mov (agent-issues #1381): hevc video,
# apple_apac spatial audio, AAC audio, then a data track.
IPHONE_STREAMS = [
    {"index": 0, "codec_name": "hevc", "codec_type": "video"},
    {"index": 1, "codec_name": "apple_apac", "codec_type": "audio"},
    {"index": 2, "codec_name": "aac", "codec_type": "audio"},
    {"index": 3, "codec_type": "data"},
]
DECODABLE = frozenset({"hevc", "h264", "aac", "pcm_s16le"})


def _maps(command: list[str]) -> list[str]:
    return [command[i + 1] for i, arg in enumerate(command) if arg == "-map"]


def _prepared(tmp_path: Path, *, transcoded: bool = True) -> PreparedVideo:
    """A PreparedVideo backed by a real temp file so cleanup is observable."""
    work_dir = tmp_path / "transcode"
    work_dir.mkdir()
    output = work_dir / "clip.mp4"
    output.write_bytes(b"x" * 4096)
    return PreparedVideo(
        path=str(output),
        size=4096,
        source_codec="hevc" if transcoded else "h264",
        output_codec="h264",
        transcoded=transcoded,
        temp_dir=str(work_dir) if transcoded else None,
    )


def _listing_client() -> MagicMock:
    client = MagicMock()
    client.create_offer.return_value = {"offerId": "OFFER-1"}
    client.publish_offer.return_value = {"listingId": "110000000001"}
    return client


def _listing_create_args(extra: list[str]) -> list[str]:
    return [
        "create",
        "--sku", "EBAY-VIDEO-TEST",
        "--title", "Video test listing",
        "--description", "Testing video attach",
        "--price", "19.99",
        "--category", "175673",
        "--format", "FIXED_PRICE",
        "--fulfillment-policy", "F-POLICY",
        "--payment-policy", "P-POLICY",
        "--return-policy", "R-POLICY",
        "--location", "warehouse-1",
        "--weight", "2.5",
        "--dimensions", "10x8x6",
        "--publish",
        *extra,
    ]


def _inventory_item(**product_extra) -> dict:
    product = {"title": "Video attach test", "imageUrls": []}
    product.update(product_extra)
    return {
        "sku": "EBAY-VIDEO-ATTACH",
        "locale": "en_US",
        "condition": "USED_GOOD",
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "product": product,
    }


# =============================================================================
# Folder scanning
# =============================================================================


def test_folder_scans_keep_videos_out_of_images_and_pick_first_video(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"img")
    (tmp_path / "photo.png").write_bytes(b"img")
    (tmp_path / "notes.txt").write_text("not media")
    (tmp_path / "clip.mov").write_bytes(b"vid")
    (tmp_path / "later.mp4").write_bytes(b"vid")

    images = listings._scan_folder_for_images(str(tmp_path))

    assert [Path(path).name for path in images] == ["photo.jpg", "photo.png"]
    assert listings._scan_folder_for_video(str(tmp_path)) == str(
        (tmp_path / "clip.mov").absolute()
    )


def test_folder_scans_return_no_video_when_folder_has_only_images(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"img")

    assert listings._scan_folder_for_video(str(tmp_path)) is None


def test_video_extensions_never_overlap_image_extensions():
    assert VIDEO_EXTENSIONS.isdisjoint(listings.IMAGE_EXTENSIONS)


# =============================================================================
# videos create / get commands
# =============================================================================


def test_videos_create_uploads_prepared_size_and_prints_video_id(runner, tmp_path):
    source = tmp_path / "source.mov"
    source.write_bytes(b"source-bytes")
    prepared = _prepared(tmp_path)
    temp_dir = prepared.temp_dir
    client = MagicMock()
    client.create_video.return_value = "VID-123"

    with patch(
        "ebay_cli.commands.videos.prepare_video_for_upload", return_value=prepared
    ), patch("ebay_cli.commands.videos.get_client", return_value=client):
        result = runner.invoke(videos.app, ["create", str(source)])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["videoId"] == "VID-123"
    assert payload["size"] == 4096
    assert payload["transcoded"] is True
    assert payload["sourceCodec"] == "hevc"
    assert payload["outputCodec"] == "h264"
    client.create_video.assert_called_once_with(
        title="source", size=4096, description=None
    )
    client.upload_video.assert_called_once_with("VID-123", prepared.path)
    assert not Path(temp_dir).exists(), "the transcode temp dir must be cleaned up"


def test_videos_create_uses_title_and_description_overrides(runner, tmp_path):
    source = tmp_path / "source.mov"
    source.write_bytes(b"source-bytes")
    prepared = _prepared(tmp_path)
    client = MagicMock()
    client.create_video.return_value = "VID-9"

    with patch(
        "ebay_cli.commands.videos.prepare_video_for_upload", return_value=prepared
    ), patch("ebay_cli.commands.videos.get_client", return_value=client):
        result = runner.invoke(
            videos.app,
            [
                "create",
                str(source),
                "--title",
                "Bulk lot walkthrough",
                "--description",
                "Close up of minifigures",
                "--table",
            ],
        )

    assert result.exit_code == 0, result.stderr
    client.create_video.assert_called_once_with(
        title="Bulk lot walkthrough", size=4096, description="Close up of minifigures"
    )
    assert "VID-9" in result.stdout


def test_videos_create_rejects_missing_file_without_calling_api(runner, tmp_path):
    client = MagicMock()

    with patch("ebay_cli.commands.videos.get_client", return_value=client):
        result = runner.invoke(videos.app, ["create", str(tmp_path / "missing.mov")])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Video file not found" in result.stderr
    client.create_video.assert_not_called()


def test_videos_create_reports_tool_failure_without_uploading(runner, tmp_path):
    source = tmp_path / "broken.mov"
    source.write_bytes(b"broken")
    client = MagicMock()

    with patch(
        "ebay_cli.commands.videos.prepare_video_for_upload",
        side_effect=VideoError("Missing required tool(s): ffmpeg"),
    ), patch("ebay_cli.commands.videos.get_client", return_value=client):
        result = runner.invoke(videos.app, ["create", str(source)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Missing required tool(s): ffmpeg" in result.stderr
    client.create_video.assert_not_called()
    client.upload_video.assert_not_called()


def test_videos_get_returns_media_status_json(runner):
    client = MagicMock()
    client.get_video.return_value = {
        "videoId": "VID-1",
        "status": "PROCESSING",
        "statusMessage": "Video is being processed",
        "size": 4096,
        "title": "Walkthrough",
        "expirationDate": "2026-10-20T00:00:00.000Z",
    }

    with patch("ebay_cli.commands.videos.get_client", return_value=client):
        result = runner.invoke(videos.app, ["get", "VID-1"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "PROCESSING"
    assert payload["videoId"] == "VID-1"
    client.get_video.assert_called_once_with("VID-1")


def test_videos_get_table_shows_status(runner):
    client = MagicMock()
    client.get_video.return_value = {
        "videoId": "VID-1",
        "status": "LIVE",
        "statusMessage": "ok",
        "size": 4096,
        "title": "Walkthrough",
        "expirationDate": "2026-10-20T00:00:00.000Z",
    }

    with patch("ebay_cli.commands.videos.get_client", return_value=client):
        result = runner.invoke(videos.app, ["get", "VID-1", "--table"])

    assert result.exit_code == 0, result.stderr
    assert "LIVE" in result.stdout


# =============================================================================
# Transcoder decisions
# =============================================================================


def test_prepare_video_keeps_h264_mp4_without_transcoding(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"a" * 32)
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        video_mod, "probe_video", lambda path: ("h264", MP4_CONTAINER)
    )

    def fail_run(*args, **kwargs):
        raise AssertionError("ffmpeg must not run for an already-compliant H.264 MP4")

    monkeypatch.setattr(video_mod.subprocess, "run", fail_run)

    prepared = prepare_video_for_upload(str(source))

    assert prepared.transcoded is False
    assert prepared.path == str(source)
    assert prepared.size == 32
    assert prepared.temp_dir is None
    assert source.read_bytes() == b"a" * 32


def test_prepare_video_transcodes_hevc_mov_to_h264_mp4(tmp_path, monkeypatch):
    source = tmp_path / "IMG_0107.mov"
    source.write_bytes(b"h" * 64)
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        video_mod,
        "probe_video",
        lambda path: ("h264", MP4_CONTAINER) if path.endswith(".mp4") else ("hevc", MP4_CONTAINER),
    )
    monkeypatch.setattr(video_mod, "probe_streams", lambda path: IPHONE_STREAMS)
    monkeypatch.setattr(video_mod, "decodable_codecs", lambda: DECODABLE)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        Path(command[-1]).write_bytes(b"o" * 128)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_mod.subprocess, "run", fake_run)

    prepared = prepare_video_for_upload(str(source))

    assert prepared.transcoded is True
    assert prepared.source_codec == "hevc"
    assert prepared.output_codec == "h264"
    assert prepared.size == 128
    assert prepared.path.endswith(".mp4")
    assert source.read_bytes() == b"h" * 64, "the source file must never be modified"
    assert commands[0][0] == "ffmpeg"
    assert "libx264" in commands[0]
    assert _maps(commands[0]) == ["0:v:0", "0:2"], "map the video and the AAC track only"
    assert "-an" not in commands[0]

    temp_dir = prepared.temp_dir
    prepared.cleanup()
    assert not Path(temp_dir).exists()


def test_prepare_video_fails_clearly_when_ffmpeg_tools_are_missing(tmp_path, monkeypatch):
    source = tmp_path / "clip.mov"
    source.write_bytes(b"x")
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: None)

    with pytest.raises(VideoError) as excinfo:
        prepare_video_for_upload(str(source))

    assert "ffprobe, ffmpeg" in str(excinfo.value)


def test_prepare_video_rejects_output_over_media_api_limit(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"a" * 64)
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(video_mod, "probe_video", lambda path: ("h264", "mp4"))
    monkeypatch.setattr(video_mod, "MAX_VIDEO_BYTES", 10)

    with pytest.raises(VideoError) as excinfo:
        prepare_video_for_upload(str(source))

    message = str(excinfo.value)
    assert "10-byte" in message
    assert f"({MAX_VIDEO_MB} MB) limit" in message


def test_select_audio_stream_skips_apple_apac_for_the_aac_track():
    assert video_mod.select_audio_stream(IPHONE_STREAMS, DECODABLE) == 2


def test_select_audio_stream_returns_none_when_no_audio_is_decodable():
    streams = [s for s in IPHONE_STREAMS if s.get("codec_name") != "aac"]
    assert video_mod.select_audio_stream(streams, DECODABLE) is None
    assert video_mod.select_audio_stream(IPHONE_STREAMS[:1], DECODABLE) is None


def test_decodable_codecs_reads_the_decode_flag_from_ffmpeg_codecs(monkeypatch):
    listing = "\n".join([
        "Codecs:",
        " D..... = Decoding supported",
        " .E.... = Encoding supported",
        " -------",
        " DEV.LS hevc                 H.265 / HEVC",
        " DEA.L. aac                  AAC (Advanced Audio Coding)",
        " ..A.L. apple_apac           Apple Positional Audio Codec",
        " .EA.L. encode_only          Encoder without decoder",
    ])
    monkeypatch.setattr(
        video_mod.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=listing, stderr=""),
    )
    video_mod.decodable_codecs.cache_clear()
    try:
        assert video_mod.decodable_codecs() == frozenset({"hevc", "aac"})
    finally:
        video_mod.decodable_codecs.cache_clear()


def test_transcode_drops_audio_with_warning_when_none_is_decodable(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "IMG_0200.mov"
    source.write_bytes(b"h" * 64)
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        video_mod,
        "probe_video",
        lambda path: ("h264", MP4_CONTAINER) if path.endswith(".mp4") else ("hevc", MP4_CONTAINER),
    )
    monkeypatch.setattr(
        video_mod,
        "probe_streams",
        lambda path: [s for s in IPHONE_STREAMS if s.get("codec_name") != "aac"],
    )
    monkeypatch.setattr(video_mod, "decodable_codecs", lambda: DECODABLE)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        Path(command[-1]).write_bytes(b"o" * 16)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_mod.subprocess, "run", fake_run)

    prepared = prepare_video_for_upload(str(source))
    prepared.cleanup()

    assert _maps(commands[0]) == ["0:v:0"]
    assert "-an" in commands[0]
    assert "-c:a" not in commands[0]
    assert "no audio" in capsys.readouterr().err


def _synthesize_iphone_mov(path: Path) -> None:
    """Build a .mov with the iPhone stream layout and a real apple_apac track.

    No ffmpeg build encodes apple_apac, so a PCM track (fourcc ``sowt``) is
    written and its sample-entry fourcc patched to ``apac``; ffmpeg then reads
    it as apple_apac and has no decoder for it, exactly like an iPhone file.
    """
    import subprocess

    base = path.with_name("base.mov")
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx265", "-c:a:0", "pcm_s16le", "-c:a:1", "aac",
            "-timecode", "00:00:00:00", "-f", "mov", str(base),
        ],
        check=True,
        capture_output=True,
    )
    data = base.read_bytes()
    assert data.count(b"sowt") == 1
    path.write_bytes(data.replace(b"sowt", b"apac"))


@pytest.mark.skipif(
    not (video_mod.shutil.which("ffmpeg") and video_mod.shutil.which("ffprobe")),
    reason="needs local ffmpeg and ffprobe",
)
def test_real_ffmpeg_transcodes_iphone_mov_with_undecodable_apple_apac(tmp_path):
    source = tmp_path / "IMG_0300.mov"
    try:
        _synthesize_iphone_mov(source)
    except Exception as exc:  # e.g. an ffmpeg build without libx265
        pytest.skip(f"cannot synthesize the iPhone-style fixture: {exc}")
    streams = video_mod.probe_streams(str(source))
    if [s.get("codec_name") for s in streams[:3]] != ["hevc", "apple_apac", "aac"]:
        pytest.skip(f"this ffmpeg build does not report apple_apac: {streams}")
    assert "apple_apac" not in video_mod.decodable_codecs()

    prepared = prepare_video_for_upload(str(source))
    try:
        output_streams = video_mod.probe_streams(prepared.path)
        assert prepared.output_codec == "h264"
        assert [(s["codec_type"], s.get("codec_name")) for s in output_streams][:2] == [
            ("video", "h264"),
            ("audio", "aac"),
        ]
    finally:
        prepared.cleanup()


def test_media_api_video_limit_is_the_documented_150_mb():
    assert MAX_VIDEO_MB == 150
    assert MAX_VIDEO_BYTES == 157_286_400


def test_upload_compatibility_accepts_h264_mov_and_mp4_only():
    assert _is_upload_compatible("h264", "mov,mp4,m4a,3gp,3g2,mj2") is True
    assert _is_upload_compatible("h264", "mp4") is True
    assert _is_upload_compatible("h264", "matroska,webm") is False
    assert _is_upload_compatible("hevc", "mov,mp4,m4a,3gp,3g2,mj2") is False


# =============================================================================
# Media API client boundaries
# =============================================================================


def _ebay_client_with_token():
    """An EbayClient whose config and token manager are stubbed."""
    from ebay_cli import client as client_mod

    config = MagicMock()
    config.api_base_url = "https://api.ebay.com"
    config.access_token = "test-token"

    with patch.object(client_mod, "TokenManager") as tokens_cls:
        tokens_cls.return_value.is_expired.return_value = False
        return client_mod.EbayClient(config=config)


def test_upload_prepared_video_declares_and_sends_the_same_size():
    client = MagicMock()
    client.create_video.return_value = "VID-X"
    prepared = PreparedVideo(
        path="/tmp/clip.mp4",
        size=1234,
        source_codec="hevc",
        output_codec="h264",
        transcoded=True,
    )

    video_id = video_mod.upload_prepared_video(
        client, prepared, title="Walkthrough", description="Close up"
    )

    assert video_id == "VID-X"
    client.create_video.assert_called_once_with(
        title="Walkthrough", size=1234, description="Close up"
    )
    client.upload_video.assert_called_once_with("VID-X", "/tmp/clip.mp4")


def test_client_create_video_sends_contract_payload_and_reads_location():
    from ebay_cli import client as client_mod

    ebay = _ebay_client_with_token()
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        response = MagicMock()
        response.status_code = 201
        response.ok = True
        response.headers = {
            "Location": "https://apim.ebay.com/commerce/media/v1_beta/video/VID-LOC"
        }
        return response

    with patch.object(client_mod.requests, "post", fake_post):
        video_id = ebay.create_video(title="Walkthrough", size=4096, description="Close up")

    assert video_id == "VID-LOC"
    assert captured["url"] == "https://apim.ebay.com/commerce/media/v1_beta/video"
    # classification is an array in the Media API schema; a bare string is
    # rejected with "Could not serialize field [classification]".
    assert captured["json"] == {
        "title": "Walkthrough",
        "size": 4096,
        "classification": ["ITEM"],
        "description": "Close up",
    }


def test_client_upload_video_declares_the_file_size_as_content_length(tmp_path):
    from ebay_cli import client as client_mod

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"z" * 777)
    ebay = _ebay_client_with_token()
    captured = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        return response

    with patch.object(client_mod.requests, "post", fake_post):
        result = ebay.upload_video("VID-1", str(video))

    assert captured["url"] == (
        "https://apim.ebay.com/commerce/media/v1_beta/video/VID-1/upload"
    )
    assert captured["headers"]["Content-Type"] == "application/octet-stream"
    assert captured["headers"]["Content-Length"] == "777"
    assert result == {"video_id": "VID-1", "status_code": 200, "size": 777}


# =============================================================================
# Listing creation with a video
# =============================================================================


def test_listings_create_attaches_video_to_inventory_item_and_warns(runner, tmp_path):
    source = tmp_path / "clip.mov"
    source.write_bytes(b"video-bytes")
    prepared = _prepared(tmp_path)
    temp_dir = prepared.temp_dir
    client = _listing_client()
    client.create_video.return_value = "VID-1"

    with patch(
        "ebay_cli.commands.listings.prepare_video_for_upload", return_value=prepared
    ), patch("ebay_cli.commands.listings.get_client", return_value=client):
        result = runner.invoke(
            listings.app, _listing_create_args(["--video", str(source)])
        )

    assert result.exit_code == 0, result.stderr
    inventory_payload = client.create_or_update_inventory_item.call_args.args[1]
    assert inventory_payload["product"]["videoIds"] == ["VID-1"]
    client.create_video.assert_called_once_with(title="clip", size=4096, description=None)
    client.upload_video.assert_called_once_with("VID-1", prepared.path)
    assert json.loads(result.stdout)["sku"] == "EBAY-VIDEO-TEST"

    assert "expire 30 days after upload" in result.stderr
    assert "iOS and Android apps" in result.stderr
    assert not Path(temp_dir).exists(), "the transcode temp dir must be cleaned up"


def test_listings_create_video_folder_picks_video_and_ignores_album_photos(
    runner, tmp_path
):
    album = tmp_path / "album"
    album.mkdir()
    (album / "photo.jpg").write_bytes(b"img")
    (album / "clip.mov").write_bytes(b"vid")
    prepared = _prepared(tmp_path)
    client = _listing_client()
    client.create_video.return_value = "VID-2"

    with patch(
        "ebay_cli.commands.listings.prepare_video_for_upload", return_value=prepared
    ) as prepare, patch("ebay_cli.commands.listings.get_client", return_value=client):
        result = runner.invoke(
            listings.app, _listing_create_args(["--video-folder", str(album)])
        )

    assert result.exit_code == 0, result.stderr
    prepare.assert_called_once_with(str((album / "clip.mov").absolute()))
    client.upload_image_from_file.assert_not_called()
    inventory_payload = client.create_or_update_inventory_item.call_args.args[1]
    assert inventory_payload["product"]["videoIds"] == ["VID-2"]


def test_listings_create_warns_and_continues_when_video_folder_has_no_video(
    runner, tmp_path
):
    album = tmp_path / "album"
    album.mkdir()
    (album / "photo.jpg").write_bytes(b"img")
    client = _listing_client()

    with patch("ebay_cli.commands.listings.prepare_video_for_upload") as prepare, patch(
        "ebay_cli.commands.listings.get_client", return_value=client
    ):
        result = runner.invoke(
            listings.app, _listing_create_args(["--video-folder", str(album)])
        )

    assert result.exit_code == 0, result.stderr
    prepare.assert_not_called()
    inventory_payload = client.create_or_update_inventory_item.call_args.args[1]
    assert "videoIds" not in inventory_payload["product"]
    assert "No video found in folder" in result.stderr
    assert "expire 30 days after upload" not in result.stderr


# =============================================================================
# Inventory item video attachment
# =============================================================================


def test_inventory_update_attaches_video_id_and_returns_verified_item(runner):
    client = MagicMock()
    client.get_inventory_item.side_effect = [
        _inventory_item(),
        _inventory_item(videoIds=["VID-777"]),
    ]

    with patch("ebay_cli.commands.inventory.get_client", return_value=client):
        result = runner.invoke(
            inventory.app,
            ["update", "EBAY-VIDEO-ATTACH", "--video-id", "VID-777"],
        )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["product"]["videoIds"] == ["VID-777"]
    client.create_or_update_inventory_item.assert_called_once_with(
        "EBAY-VIDEO-ATTACH",
        {
            "condition": "USED_GOOD",
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
            "product": {
                "title": "Video attach test",
                "imageUrls": [],
                "videoIds": ["VID-777"],
            },
        },
    )


def test_inventory_update_fails_when_video_readback_does_not_match(runner):
    client = MagicMock()
    client.get_inventory_item.side_effect = [_inventory_item(), _inventory_item()]

    with patch("ebay_cli.commands.inventory.get_client", return_value=client):
        result = runner.invoke(
            inventory.app,
            ["update", "EBAY-VIDEO-ATTACH", "--video-id", "VID-777"],
        )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "video update was not applied" in result.stderr


def test_inventory_create_attaches_video_id(runner):
    client = MagicMock()
    client.get_inventory_item.return_value = _inventory_item(videoIds=["VID-42"])

    with patch("ebay_cli.commands.inventory.get_client", return_value=client):
        result = runner.invoke(
            inventory.app,
            ["create", "EBAY-VIDEO-CREATE", "--title", "Video create", "--video-id", "VID-42"],
        )

    assert result.exit_code == 0, result.stderr
    payload = client.create_or_update_inventory_item.call_args.args[1]
    assert payload["product"]["videoIds"] == ["VID-42"]
