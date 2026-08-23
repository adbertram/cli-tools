import json

from typer.testing import CliRunner

from youtube_cli.chapter_validation import validate_chapters_description
from youtube_cli.commands import channel
from youtube_cli.main import app


runner = CliRunner()


def test_validate_chapters_description_accepts_valid_chapter_list():
    result = validate_chapters_description(
        "Overview\n\n00:00 Intro\n00:12 Setup\n02:05 Demo\n"
    )

    assert result["valid"] is True
    assert result["chapter_count"] == 3
    assert result["chapters"] == [
        {"line": 3, "timestamp": "00:00", "start_seconds": 0, "title": "Intro"},
        {"line": 4, "timestamp": "00:12", "start_seconds": 12, "title": "Setup"},
        {"line": 5, "timestamp": "02:05", "start_seconds": 125, "title": "Demo"},
    ]
    assert result["issues"] == []


def test_validate_chapters_description_rejects_missing_zero_start():
    result = validate_chapters_description("00:05 Intro\n00:20 Setup\n00:40 Demo")

    assert result["valid"] is False
    assert result["issues"][0]["code"] == "first_timestamp_not_zero"


def test_validate_chapters_description_rejects_less_than_three_timestamps():
    result = validate_chapters_description("00:00 Intro\n00:20 Setup")

    assert result["valid"] is False
    assert result["issues"][0]["code"] == "too_few_chapters"


def test_validate_chapters_description_rejects_short_chapter_gap():
    result = validate_chapters_description("00:00 Intro\n00:09 Setup\n00:30 Demo")

    assert result["valid"] is False
    assert result["issues"][0]["code"] == "chapter_too_short"
    assert result["issues"][0]["line"] == 1


def test_validate_chapters_description_checks_last_chapter_when_duration_is_supplied():
    result = validate_chapters_description(
        "00:00 Intro\n00:20 Setup\n00:40 Demo",
        duration_seconds=45,
    )

    assert result["valid"] is False
    assert result["issues"][0]["code"] == "last_chapter_too_short"


def test_videos_chapters_validate_outputs_validation_json():
    result = runner.invoke(
        app,
        [
            "videos",
            "chapters",
            "validate",
            "--description",
            "00:00 Intro\n00:12 Setup\n02:05 Demo",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["chapter_count"] == 3


def test_channel_videos_upload_include_recommended_chapters_returns_ai_instruction(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake video")
    monkeypatch.setattr(
        channel,
        "get_api_client",
        lambda profile=None: (_ for _ in ()).throw(AssertionError("API client should not be created")),
    )

    result = runner.invoke(
        app,
        [
            "channel",
            "videos",
            "upload",
            str(video_path),
            "--title",
            "Demo video",
            "--description",
            "This video covers setup and a demo.",
            "--include-recommended-chapters",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["type"] == "ai_instruction"
    assert payload["command"] == "channel videos upload"
    assert payload["action_id"] == "recommend_video_chapters"
    assert payload["structured_context"]["description"] == "This video covers setup and a demo."
    assert payload["structured_context"]["original_command"]["file"] == str(video_path)


def test_channel_videos_update_include_recommended_chapters_requires_description(monkeypatch):
    monkeypatch.setattr(
        channel,
        "get_api_client",
        lambda profile=None: (_ for _ in ()).throw(AssertionError("API client should not be created")),
    )

    result = runner.invoke(
        app,
        ["channel", "videos", "update", "abc123", "--include-recommended-chapters"],
    )

    assert result.exit_code == 1
    assert "requires --description" in result.stderr
