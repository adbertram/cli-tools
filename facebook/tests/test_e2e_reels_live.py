"""Live end-to-end test: publish a Page Reel draft, poll its status, always delete it.

Opt-in only. Run from the facebook tool directory's source checkout:

    FACEBOOK_E2E=1 FACEBOOK_E2E_PAGE_ID=<page id> \\
        uv run --project facebook pytest facebook/tests/test_e2e_reels_live.py -m e2e -v -s

FACEBOOK_E2E_PROFILE selects the Graph API auth profile (default: graph, the
profile name documented in the README). The Reel is saved as a Page draft, so it
is never published to the Page feed, and it is deleted in a ``finally`` block
whether the test passes or fails.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

if os.environ.get("FACEBOOK_E2E") != "1":
    pytest.skip("Live Facebook e2e disabled; set FACEBOOK_E2E=1", allow_module_level=True)

FACEBOOK = Path(sys.executable).parent / "facebook"
PROFILE = os.environ.get("FACEBOOK_E2E_PROFILE", "graph")
POLL_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 5
FAILED_VIDEO_STATUSES = {"error", "expired", "upload_failed"}


def _page_id() -> str:
    page_id = os.environ.get("FACEBOOK_E2E_PAGE_ID")
    if not page_id:
        pytest.fail("FACEBOOK_E2E_PAGE_ID is required (see `facebook pages list --profile graph`).")
    return page_id


def _facebook(*args: str) -> subprocess.CompletedProcess:
    assert FACEBOOK.is_file(), f"worktree facebook launcher missing: {FACEBOOK}"
    return subprocess.run(
        [str(FACEBOOK), *args, "--profile", PROFILE],
        capture_output=True,
        text=True,
        timeout=600,
    )


def _facebook_json(*args: str) -> dict:
    result = _facebook(*args)
    assert result.returncode == 0, f"facebook {' '.join(args)} failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.fixture
def reel_clip(tmp_path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.fail("ffmpeg is required to generate the test Reel clip.")
    clip = tmp_path / "e2e-reel.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(clip),
        ],
        check=True,
    )
    return clip


def _wait_until_processed(video_id: str, page_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        status = _facebook_json("reels", "status", video_id, "--page", page_id)["status"]
        video_status = status["video_status"]
        print(f"reel {video_id} status: {json.dumps(status)}", file=sys.stderr)
        if video_status in FAILED_VIDEO_STATUSES:
            pytest.fail(f"Reel {video_id} reached terminal failure status: {status}")
        if video_status == "ready":
            return status
        if time.monotonic() > deadline:
            pytest.fail(f"Reel {video_id} not ready after {POLL_TIMEOUT_SECONDS}s: {status}")
        time.sleep(POLL_INTERVAL_SECONDS)


def test_reel_draft_publish_status_and_delete(reel_clip):
    page_id = _page_id()
    video_id = None
    try:
        publish = _facebook(
            "reels", "publish", str(reel_clip),
            "--page", page_id,
            "--draft",
            "--description", "facebook-cli e2e test reel (auto-deleted)",
        )
        if publish.returncode != 0:
            created = re.search(r"\[video_id=(\d+)\]", publish.stderr)
            video_id = created.group(1) if created else None
            pytest.fail(f"reels publish failed: {publish.stderr}")
        result = json.loads(publish.stdout)
        video_id = result["video_id"]
        print(f"published draft reel video_id={video_id}", file=sys.stderr)
        assert result["page_id"] == page_id
        assert result["video_state"] == "DRAFT"

        status = _wait_until_processed(video_id, page_id)
        assert status["publishing_phase"]["publish_status"] == "draft"
    finally:
        if video_id:
            deleted = _facebook_json("reels", "delete", video_id, "--page", page_id, "--yes")
            assert deleted == {
                "page_id": page_id,
                "page_name": deleted["page_name"],
                "video_id": video_id,
                "deleted": True,
            }
            print(f"deleted reel video_id={video_id}", file=sys.stderr)

    gone = _facebook("reels", "status", video_id, "--page", page_id)
    assert gone.returncode == 1, gone.stdout
    assert "does not exist" in gone.stderr, gone.stderr
