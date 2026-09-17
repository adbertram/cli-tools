"""Regression tests for local-image upload to the static site's media bucket.

Every local image referenced by post markdown goes through the publisher's own
content-addressed R2 path: the file goes straight into the canonical media
bucket under a `wp-content/uploads/publisher/<sha256><ext>` key and the site's
media edge serves it. It deliberately does NOT reuse the inline *mirror* path,
which downloads bytes from the live site origin and enumerates derivatives
from the media inventory; a brand-new local image exists at neither.

These tests pin that the key is content-addressed, that an upload verifies in
R2 before its URL is returned, that markdown is rewritten to the public URL,
that an already-present object is recovered without a second write, and that
every failure raises instead of falling back to another destination.

Hermetic: no network, no Cloudflare calls; the `cloudflare` CLI is stubbed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from ata_blog_cli.utils import images


_BUCKET = "ata-blog-media"
_ORIGIN = "https://adamtheautomator.com"
_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 fake-image-bytes"
_SHA = hashlib.sha256(_BYTES).hexdigest()
_KEY = f"wp-content/uploads/publisher/{_SHA}.webp"


def _image(tmp_path, name: str = "diagram.webp", data: bytes = _BYTES):
    path = tmp_path / name
    path.write_bytes(data)
    return path


class _CloudflareStub:
    """Stand-in for the `cloudflare` CLI backed by an in-memory bucket."""

    def __init__(self, objects: dict | None = None):
        self.objects = dict(objects or {})
        self.calls: list[list[str]] = []

    def __call__(self, cmd, capture_output, text, timeout):
        assert cmd[0] == "cloudflare"
        self.calls.append(cmd)
        if cmd[1:4] == ["r2", "objects", "list"]:
            prefix = cmd[cmd.index("--prefix") + 1]
            stdout = json.dumps(
                [
                    {"key": key, "size": len(value)}
                    for key, value in sorted(self.objects.items())
                    if key.startswith(prefix)
                ]
            )
            return subprocess.CompletedProcess(cmd, 0, stdout, "")
        if cmd[1:4] == ["r2", "objects", "put"]:
            key = cmd[5]
            file_path = cmd[cmd.index("--file") + 1]
            with open(file_path, "rb") as handle:
                self.objects[key] = handle.read()
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"key": key}), "")
        raise AssertionError(f"unexpected cloudflare invocation: {cmd}")

    def put_calls(self):
        return [cmd for cmd in self.calls if cmd[1:4] == ["r2", "objects", "put"]]


@pytest.fixture
def cloudflare(monkeypatch):
    stub = _CloudflareStub()
    monkeypatch.setattr(images.subprocess, "run", stub)
    return stub


def test_object_key_is_content_addressed(tmp_path) -> None:
    assert images.static_media_object_key(_image(tmp_path)) == _KEY


def test_identical_bytes_under_different_names_share_one_key(tmp_path) -> None:
    first = images.static_media_object_key(_image(tmp_path, "a.webp"))
    second = images.static_media_object_key(_image(tmp_path, "b.webp"))
    assert first == second


def test_extension_is_normalized_into_the_key(tmp_path) -> None:
    key = images.static_media_object_key(_image(tmp_path, "shot.PNG"))
    assert key == f"wp-content/uploads/publisher/{_SHA}.png"


def test_upload_writes_to_r2_and_returns_the_public_url(tmp_path, cloudflare) -> None:
    result = images.upload_to_static_media(_image(tmp_path))

    assert result == {
        "key": _KEY,
        "url": f"{_ORIGIN}/{_KEY}",
        "size": len(_BYTES),
        "recovered": False,
    }
    assert cloudflare.objects[_KEY] == _BYTES

    put = cloudflare.put_calls()
    assert len(put) == 1
    assert put[0][:6] == ["cloudflare", "r2", "objects", "put", _BUCKET, _KEY]
    assert put[0][put[0].index("--content-type") + 1] == "image/webp"


def test_upload_only_runs_the_cloudflare_cli(tmp_path, cloudflare) -> None:
    """Every subprocess an upload spawns is the `cloudflare` CLI."""
    images.upload_to_static_media(_image(tmp_path))
    assert all(cmd[0] == "cloudflare" for cmd in cloudflare.calls)


def test_upload_recovers_an_already_present_object_without_rewriting(
    tmp_path, cloudflare
) -> None:
    cloudflare.objects[_KEY] = _BYTES

    result = images.upload_to_static_media(_image(tmp_path))

    assert result["recovered"] is True
    assert result["url"] == f"{_ORIGIN}/{_KEY}"
    assert cloudflare.put_calls() == []


def test_upload_raises_when_the_cloudflare_command_fails(tmp_path, monkeypatch) -> None:
    def failing(cmd, capture_output, text, timeout):
        if cmd[1:4] == ["r2", "objects", "list"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return subprocess.CompletedProcess(cmd, 1, "", "bucket not found")

    monkeypatch.setattr(images.subprocess, "run", failing)

    with pytest.raises(RuntimeError, match="Static media upload failed"):
        images.upload_to_static_media(_image(tmp_path))


def test_upload_raises_when_the_object_does_not_verify(tmp_path, monkeypatch) -> None:
    """A put that reports success but leaves no object must not return a URL."""

    def silent(cmd, capture_output, text, timeout):
        if cmd[1:4] == ["r2", "objects", "list"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"key": _KEY}), "")

    monkeypatch.setattr(images.subprocess, "run", silent)

    with pytest.raises(RuntimeError, match="did not verify in R2"):
        images.upload_to_static_media(_image(tmp_path))


def test_upload_raises_when_stored_bytes_differ_from_local(tmp_path, monkeypatch) -> None:
    stub = _CloudflareStub({_KEY: b"different-bytes"})
    monkeypatch.setattr(images.subprocess, "run", stub)

    with pytest.raises(RuntimeError, match="but the local file is"):
        images.upload_to_static_media(_image(tmp_path))


def test_upload_raises_for_a_missing_file(tmp_path, cloudflare) -> None:
    with pytest.raises(RuntimeError, match="does not exist"):
        images.upload_to_static_media(tmp_path / "absent.webp")


def test_upload_raises_for_an_undeterminable_content_type(tmp_path, cloudflare) -> None:
    with pytest.raises(RuntimeError, match="Could not determine image content type"):
        images.upload_to_static_media(_image(tmp_path, "diagram.unknownext"))


def test_markdown_local_refs_are_rewritten_to_public_urls(tmp_path, cloudflare) -> None:
    _image(tmp_path)
    markdown = (
        "Intro text.\n\n"
        "![A diagram](diagram.webp)\n\n"
        "![Remote](https://adamtheautomator.com/wp-content/uploads/2026/06/x.png)\n"
    )

    rewritten, uploaded = images.upload_local_images(
        markdown, base_dir=tmp_path, verbose=False
    )

    assert uploaded == 1
    assert f"![A diagram]({_ORIGIN}/{_KEY})" in rewritten
    # The remote URL is left alone.
    assert "https://adamtheautomator.com/wp-content/uploads/2026/06/x.png" in rewritten


def test_markdown_with_no_local_refs_makes_no_cloudflare_calls(tmp_path, cloudflare) -> None:
    markdown = "![Remote](https://adamtheautomator.com/wp-content/uploads/2026/06/x.png)\n"

    rewritten, uploaded = images.upload_local_images(
        markdown, base_dir=tmp_path, verbose=False
    )

    assert (rewritten, uploaded) == (markdown, 0)
    assert cloudflare.calls == []


def test_rewritten_urls_are_excluded_from_the_inline_mirror_path(
    tmp_path, cloudflare
) -> None:
    """A publisher-prefixed URL must not be treated as an inline mirror.

    `_find_inline_static_media_urls` skips `wp-content/uploads/publisher/`
    because those objects are already in R2 and have no origin copy to
    download. Uploading inline images under that prefix is what makes the two
    paths compose instead of collide.
    """
    from ata_blog_cli.client import AtaBlogClient

    _image(tmp_path)
    rewritten, _ = images.upload_local_images(
        "![d](diagram.webp)\n", base_dir=tmp_path, verbose=False
    )

    assert AtaBlogClient._find_inline_static_media_urls(
        AtaBlogClient.__new__(AtaBlogClient), rewritten
    ) == []
