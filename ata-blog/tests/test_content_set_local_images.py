"""Tests for local-image upload + markdown rewrite in `notion-page content set`.

The flow under test:
  1. content_set reads a markdown file
  2. It scans for `![alt](relative/path)` and `<img src="...">` refs whose path
     is NOT http/https and which resolves to a real file on disk
  3. Each local image is uploaded via the WordPress media CLI
     (`utils.images.upload_to_wordpress`, which shells out to `wordpress media upload`)
  4. The markdown is rewritten so each local path becomes the returned
     WordPress source_url
  5. The rewritten markdown is what gets pushed to Notion

The tests mock the wordpress CLI subprocess call and assert the final markdown
that would be passed to Notion contains https:// URLs instead of local paths.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ata_blog_cli.utils import images as images_mod
from ata_blog_cli.utils.images import (
    find_local_image_refs,
    is_remote_url,
    process_local_images_for_wordpress,
)


def _wp_subprocess_result(source_url: str, media_id: int = 42):
    """Fake CompletedProcess matching the `wordpress media upload` JSON shape."""
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = json.dumps({"id": media_id, "source_url": source_url})
    fake.stderr = ""
    return fake


def test_is_remote_url_distinguishes_local_and_remote():
    assert is_remote_url("https://example.com/a.png") is True
    assert is_remote_url("http://example.com/a.png") is True
    assert is_remote_url("images/local.png") is False
    assert is_remote_url("/abs/path/a.png") is False


def test_find_local_image_refs_resolves_relative_paths(tmp_path: Path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    img1 = images_dir / "one.png"
    img1.write_bytes(b"fake-png-1")
    img2 = images_dir / "two.png"
    img2.write_bytes(b"fake-png-2")

    md_path = tmp_path / "post.md"
    md_text = (
        "# Heading\n\n"
        "![first](images/one.png)\n\n"
        '<img src="images/two.png" alt="second"/>\n\n'
        "![remote](https://cdn.example.com/already-remote.png)\n\n"
        "![missing](images/does-not-exist.png)\n"
    )
    md_path.write_text(md_text)

    refs = find_local_image_refs(md_text, md_path.parent)

    # Both local files (markdown + html img) found; remote and missing skipped.
    found_paths = [p for (_, _, p) in refs]
    assert img1.resolve() in found_paths
    assert img2.resolve() in found_paths
    assert len(refs) == 2


def test_find_local_image_refs_skips_missing_files(tmp_path: Path):
    md = "![a](images/nope.png)\n"
    refs = find_local_image_refs(md, tmp_path)
    assert refs == []


def test_process_local_images_uploads_and_rewrites_markdown(tmp_path: Path):
    """End-to-end on the helper: mock the WordPress CLI, assert rewritten md."""
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "diagram.png").write_bytes(b"png-bytes")
    (images_dir / "screenshot.png").write_bytes(b"png-bytes-2")

    md_text = (
        "Intro.\n\n"
        "![Diagram](images/diagram.png)\n\n"
        '<img src="images/screenshot.png" alt="Shot" />\n\n'
        "![External](https://cdn.example.com/keep-me.png)\n"
    )

    wp_urls = {
        "diagram.png": "https://wp.example.com/wp-content/uploads/2026/05/diagram.png",
        "screenshot.png": "https://wp.example.com/wp-content/uploads/2026/05/screenshot.png",
    }

    def fake_run(cmd, **_kwargs):
        # cmd[0:3] = ["wordpress", "media", "upload"]; cmd[3] = absolute file path
        assert cmd[:3] == ["wordpress", "media", "upload"]
        uploaded_path = Path(cmd[3])
        return _wp_subprocess_result(wp_urls[uploaded_path.name])

    with patch.object(images_mod.subprocess, "run", side_effect=fake_run) as mock_run:
        rewritten, uploaded = process_local_images_for_wordpress(
            md_text, base_dir=tmp_path, verbose=False
        )

    assert uploaded == 2
    assert mock_run.call_count == 2

    # Local paths must be gone, replaced by https URLs.
    assert "images/diagram.png" not in rewritten
    assert "images/screenshot.png" not in rewritten
    assert wp_urls["diagram.png"] in rewritten
    assert wp_urls["screenshot.png"] in rewritten

    # Remote URL must be untouched.
    assert "https://cdn.example.com/keep-me.png" in rewritten


def test_process_local_images_noop_when_no_local_refs(tmp_path: Path):
    md = "![remote](https://cdn.example.com/x.png)\n"
    with patch.object(images_mod.subprocess, "run") as mock_run:
        rewritten, uploaded = process_local_images_for_wordpress(
            md, base_dir=tmp_path, verbose=False
        )
    assert uploaded == 0
    assert rewritten == md
    mock_run.assert_not_called()


def test_content_set_pushes_rewritten_markdown_to_notion(tmp_path: Path):
    """The integration test the bug report asks for.

    Mocks the wordpress CLI and the notion client; asserts the file path that
    ultimately gets handed to `client.set_article_content` contains the
    rewritten markdown (i.e. an https:// URL instead of the local path).
    """
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "dlp-template-selection.png").write_bytes(b"png")
    md_path = tmp_path / "post_revision_4.md"
    md_path.write_text(
        "# DLP Guide\n\n"
        "![Template selection screen](images/dlp-template-selection.png)\n"
    )

    wp_url = "https://wp.example.com/wp-content/uploads/2026/05/dlp-template-selection.png"

    def fake_run(cmd, **_kwargs):
        assert cmd[:3] == ["wordpress", "media", "upload"]
        return _wp_subprocess_result(wp_url)

    # The runner invokes Typer; easier to call the command function directly
    # in unit tests since we want to assert exactly which file path is forwarded
    # to client.set_article_content.
    from ata_blog_cli.commands import notion_page as notion_page_mod

    captured = {}

    fake_client = MagicMock()

    def fake_set_article_content(page_id, file_path):
        captured["page_id"] = page_id
        captured["forwarded_path"] = file_path
        captured["forwarded_markdown"] = Path(file_path).read_text()
        return {"success": True}

    fake_client.set_article_content.side_effect = fake_set_article_content

    with patch.object(images_mod.subprocess, "run", side_effect=fake_run), \
         patch.object(notion_page_mod, "get_client", return_value=fake_client):
        notion_page_mod.content_set(page_id="abc123", file=str(md_path))

    # The markdown handed to Notion must have the WP URL, not the local path.
    assert "forwarded_markdown" in captured, "client.set_article_content was never called"
    assert "images/dlp-template-selection.png" not in captured["forwarded_markdown"]
    assert wp_url in captured["forwarded_markdown"]
    # And the file we forwarded is NOT the original (it's a temp file we wrote)
    assert captured["forwarded_path"] != str(md_path)
