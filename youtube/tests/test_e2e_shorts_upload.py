"""Live end-to-end test: upload a YouTube Short through the CLI, then delete it.

Skipped unless ``YOUTUBE_E2E=1``. Uses the active ``youtube`` auth profile, so run
``youtube auth status`` first and ``youtube auth login`` if it is not authenticated.

Run:
    YOUTUBE_E2E=1 uv run --project youtube --with pytest python -m pytest youtube/tests -m e2e -v

Data API quota per run (https://developers.google.com/youtube/v3/determine_quota_cost):
- ``videos.insert``: 1 call from the separate 100/day upload bucket (older docs
  billed uploads at 1600 units of the 10,000-unit daily quota).
- ``videos.list``: 1 unit per ``channel videos get`` poll (a few per run).
- ``videos.delete``: 50 units.

The uploaded video is private and is always deleted in ``finally``, pass or fail.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("YOUTUBE_E2E") != "1", reason="set YOUTUBE_E2E=1 to run live e2e"),
]


def _cli(*args: str) -> subprocess.CompletedProcess:
    # `python -m` with cwd=TOOL_DIR runs this checkout's source, not the installed launcher.
    return subprocess.run(
        [sys.executable, "-m", "youtube_cli.main", *args],
        cwd=TOOL_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _make_vertical_clip(path: Path) -> None:
    assert shutil.which("ffmpeg"), "ffmpeg is required for the YouTube Shorts e2e test"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )


def test_shorts_upload_then_delete(tmp_path):
    clip = tmp_path / "e2e_short.mp4"
    _make_vertical_clip(clip)
    title = f"cli-tools e2e short {uuid.uuid4().hex[:8]}"

    upload = _cli("shorts", "upload", str(clip), "--title", title, "--description", "#Shorts e2e test", "--privacy", "private")
    assert upload.returncode == 0, upload.stderr
    video_id = json.loads(upload.stdout)["id"]
    print(f"uploaded video id: {video_id}")

    try:
        got = _cli("channel", "videos", "get", video_id)
        assert got.returncode == 0, got.stderr
        detail = json.loads(got.stdout)
        assert detail["id"] == video_id
        assert detail["title"] == title
        assert detail["status"]["privacy_status"] == "private"
        assert detail["status"]["upload_status"] in {"uploaded", "processed"}, detail["status"]
    finally:
        deleted = _cli("channel", "videos", "delete", video_id, "--yes")
        assert deleted.returncode == 0, deleted.stderr
        assert json.loads(deleted.stdout) == {"id": video_id, "deleted": True}

        for _ in range(10):
            gone = _cli("channel", "videos", "get", video_id)
            if gone.returncode == 1 and f"Video not found: {video_id}" in gone.stderr:
                break
            time.sleep(3)
        assert f"Video not found: {video_id}" in gone.stderr, (gone.returncode, gone.stdout, gone.stderr)
        print(f"deleted video id: {video_id}")
