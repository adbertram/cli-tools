"""Regression tests for featured image resolution during publishing."""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

import ata_blog_cli.client as client_module
from ata_blog_cli.client import AtaBlogClient, ClientError
from ata_blog_cli.commands import notion_page


# Live-schema types for the Notion properties the publish path writes. Mirrors
# `notion database schema 2a317112-d9c8-42ee-a4d4-a2b8a5a20818`.
_PUBLISH_PROPERTY_TYPES = {
    "Status": "status",
    "Published URL": "url",
    "Publish Date": "date",
}


def test_notion_page_publish_unknown_tag_exits_nonzero(monkeypatch):
    """CLI publish validation errors must fail the process for shell loops/cron."""

    class FakeClient:
        def publish_article(self, *args, **kwargs):
            raise ClientError("Unknown static corpus tags name: 'SOC 2'")

    monkeypatch.setattr(notion_page, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(
        notion_page.app,
        [
            "publish",
            "31b5d9c85b2b814298a0ea98cb7d78f4",
            "--auto-schedule",
        ],
    )

    assert result.exit_code != 0
    assert "Error: Unknown static corpus tags name: 'SOC 2'" in result.output


def test_resolves_conventional_featured_image_when_option_is_omitted(tmp_path, monkeypatch):
    """Headless publish should attach the pipeline image without a manual flag."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    image_path = tmp_path / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)

    assert AtaBlogClient._resolve_featured_image(page_id, None) == image_path


def test_conventional_featured_image_lookup_ignores_cwd(tmp_path, monkeypatch):
    """The due publisher runs from any directory; the lookup root is the repository."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    repository = tmp_path / "repository"
    image_path = repository / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    elsewhere = tmp_path / "elsewhere"
    # A same-named image under the working directory must not be picked up.
    decoy = elsewhere / "posts" / page_id / "featured_image.webp"
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"decoy-bytes")
    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", repository)
    monkeypatch.chdir(elsewhere)

    assert AtaBlogClient._resolve_featured_image(page_id, None) == image_path


def test_prefers_conventional_webp_featured_image_when_available(tmp_path, monkeypatch):
    """Optimized WebP output should be used before the PNG source."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    post_dir = tmp_path / "posts" / page_id
    post_dir.mkdir(parents=True)
    png_path = post_dir / "featured_image.png"
    webp_path = post_dir / "featured_image.webp"
    png_path.write_bytes(b"png-bytes")
    webp_path.write_bytes(b"webp-bytes")
    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)

    assert AtaBlogClient._resolve_featured_image(page_id, None) == webp_path


def test_reports_actionable_blocker_when_no_conventional_featured_image_exists(
    tmp_path, monkeypatch
):
    """Missing pipeline image should block before any publish attempt."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)

    with pytest.raises(ClientError) as exc_info:
        AtaBlogClient._resolve_featured_image(page_id, None)

    message = str(exc_info.value)
    assert "Featured image is required for publishing" in message
    assert f"{tmp_path}/posts/{page_id}/featured_image.webp" in message
    assert "--featured-image PATH" in message


def test_explicit_featured_image_path_still_validates(tmp_path):
    """Manual featured image selection remains supported."""

    image_path = tmp_path / "selected.jpg"
    image_path.write_bytes(b"jpg-bytes")

    assert AtaBlogClient._resolve_featured_image("page-id", str(image_path)) == image_path
