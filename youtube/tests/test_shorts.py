from pathlib import Path

from youtube_cli.commands import shorts
from youtube_cli.models import PrivacyStatus


def test_shorts_upload_delegates_to_existing_channel_uploader(monkeypatch, tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_upload(**kwargs):
        captured.update(kwargs)
        return {"id": "VID1"}

    monkeypatch.setattr(shorts.channel, "videos_upload", fake_upload)

    result = shorts.shorts_upload(
        file=video,
        title="Short title",
        description="Description",
        tags=["one", "two"],
        category_id="22",
        privacy=PrivacyStatus.PRIVATE,
        publish_at=None,
        made_for_kids=False,
        thumbnail=None,
        profile="ata",
    )

    assert result == {"id": "VID1"}
    assert captured["file"] == video
    assert captured["title"] == "Short title"
    assert captured["tags"] == ["one", "two"]
    assert captured["privacy"] == PrivacyStatus.PRIVATE
    assert captured["include_recommended_chapters"] is False
    assert captured["profile"] == "ata"
