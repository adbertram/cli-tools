"""Live e2e: publish a private TikTok video, poll its status, then delete it.

Skipped unless ``TIKTOK_E2E=1``. Drives the CLI from this source tree
(``python -m tiktok_cli.main``) against two real auth profiles:

- ``TIKTOK_E2E_API_PROFILE`` (default ``posting``): custom Content Posting API
  profile used by ``videos publish`` / ``videos status``.
- ``TIKTOK_E2E_BROWSER_PROFILE`` (default ``default``): browser_session profile
  used by ``videos list`` / ``videos delete``.

A SELF_ONLY Direct Post never returns a post id (``publicaly_available_post_id``
is only set for public, moderated posts), so the test captions the clip with a
unique nonce and finds the video id in ``videos list``. The cleanup fixture
deletes every video carrying the nonce and proves it is gone, on pass or fail.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("TIKTOK_E2E") != "1", reason="set TIKTOK_E2E=1 to run"),
]

API_PROFILE = os.environ.get("TIKTOK_E2E_API_PROFILE", "posting")
BROWSER_PROFILE = os.environ.get("TIKTOK_E2E_BROWSER_PROFILE", "default")
STATUS_TIMEOUT = 300
LIST_TIMEOUT = 180
POLL_SECONDS = 10
TERMINAL_STATUSES = {"PUBLISH_COMPLETE", "FAILED"}


def tiktok(*args: str, profile: str):
    """Run one CLI command from this source tree and return its JSON stdout."""
    cmd = [sys.executable, "-m", "tiktok_cli.main", *args, "--profile", profile]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, (
        f"tiktok {' '.join(args)} exited {result.returncode}: {result.stderr.strip()}"
    )
    return json.loads(result.stdout)


def videos_with_nonce(username: str, nonce: str) -> list[dict]:
    return tiktok(
        "videos", "list", "--username", username, "--limit", "30",
        "--filter", f"caption:contains:{nonce}",
        profile=BROWSER_PROFILE,
    )


def poll(fn, done, timeout: int):
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if done(value) or time.monotonic() >= deadline:
            return value
        time.sleep(POLL_SECONDS)


@pytest.fixture
def clip(tmp_path):
    """A 5 s 720x1280 30 fps H.264/AAC MP4 (TikTok: >=360 px, 23-60 fps)."""
    if shutil.which("ffmpeg") is None:
        pytest.fail("ffmpeg is required to build the e2e clip")
    path = tmp_path / "tiktok-e2e.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def published():
    """Track the post; teardown deletes every nonce match and proves it is gone."""
    from tiktok_cli.config import get_config
    from tiktok_cli.posting import TikTokPostingClient

    username = TikTokPostingClient(config=get_config(profile=API_PROFILE)).creator_info()[
        "creator_username"
    ]
    # Refuse to publish anything this run could not find and delete afterwards.
    videos_with_nonce(username, "preflight")
    state = {"username": username, "nonce": f"clie2e{uuid.uuid4().hex[:12]}", "attempted": False}
    yield state

    if not state["attempted"]:
        return
    matches = poll(
        lambda: videos_with_nonce(username, state["nonce"]), bool, LIST_TIMEOUT
    )
    for video in matches:
        deleted = tiktok("videos", "delete", video["id"], "--yes", profile=BROWSER_PROFILE)
        assert deleted == {"video_id": video["id"], "deleted": True}
    remaining = poll(
        lambda: videos_with_nonce(username, state["nonce"]), lambda v: not v, LIST_TIMEOUT
    )
    assert not remaining, f"LEFTOVER TikTok video(s) after delete: {remaining}"
    print(f"deleted and verified gone: {[v['id'] for v in matches]}")


def test_publish_status_and_delete(clip, published):
    published["attempted"] = True
    result = tiktok(
        "videos", "publish", str(clip),
        "--title", f"cli-tools e2e {published['nonce']}",
        "--privacy", "SELF_ONLY",
        profile=API_PROFILE,
    )
    publish_id = result["publish_id"]
    assert result["creator_username"] == published["username"]

    status = poll(
        lambda: tiktok("videos", "status", publish_id, profile=API_PROFILE),
        lambda s: s.get("status") in TERMINAL_STATUSES,
        STATUS_TIMEOUT,
    )
    assert status["status"] == "PUBLISH_COMPLETE", status

    videos = poll(
        lambda: videos_with_nonce(published["username"], published["nonce"]), bool, LIST_TIMEOUT
    )
    assert len(videos) == 1, videos
    print(f"publish_id={publish_id} video_id={videos[0]['id']}")
