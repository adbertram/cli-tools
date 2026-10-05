"""Regression tests for featured image resolution during publishing."""

from __future__ import annotations

import hashlib
import json
import subprocess
from types import SimpleNamespace

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


def test_resolves_conventional_featured_image_when_page_id_is_dashed(tmp_path, monkeypatch):
    """The scheduled publisher passes dashed Notion IDs; lookup must use the undashed folder."""

    dashed_page_id = "3075d9c8-5b2b-8183-b1f2-c3f391257a46"
    undashed_page_id = "3075d9c85b2b8183b1f2c3f391257a46"
    image_path = tmp_path / "posts" / undashed_page_id / "featured_image.webp"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"webp-bytes")
    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)

    assert AtaBlogClient._resolve_featured_image(dashed_page_id, None) == image_path


def test_missing_featured_image_error_lists_undashed_folder_for_dashed_page_id(
    tmp_path, monkeypatch
):
    """The blocker message must point at the real (undashed) folder, not the dashed input."""

    dashed_page_id = "3075d9c8-5b2b-8183-b1f2-c3f391257a46"
    undashed_page_id = "3075d9c85b2b8183b1f2c3f391257a46"
    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)

    with pytest.raises(ClientError) as exc_info:
        AtaBlogClient._resolve_featured_image(dashed_page_id, None)

    message = str(exc_info.value)
    assert f"{tmp_path}/posts/{undashed_page_id}/featured_image.webp" in message
    assert dashed_page_id not in message


def test_explicit_featured_image_path_still_validates(tmp_path):
    """Manual featured image selection remains supported."""

    image_path = tmp_path / "selected.jpg"
    image_path.write_bytes(b"jpg-bytes")

    assert AtaBlogClient._resolve_featured_image("page-id", str(image_path)) == image_path


# --- recovery from R2 when scheduling and publishing run on different hosts -

_PAGE_ID = "3495d9c85b2b81eebac8e532046b5b58"


def _md5_hex(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def test_schedule_uploads_resolved_image_to_its_page_keyed_r2_object(tmp_path, monkeypatch):
    """Scheduling mirrors the resolved image so another host can recover it."""

    client = AtaBlogClient.__new__(AtaBlogClient)
    image_path = tmp_path / "featured_image.webp"
    image_path.write_bytes(b"webp-bytes")
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        assert command[1:4] == ["r2", "objects", "put"]
        return SimpleNamespace(stdout=json.dumps({"key": command[5]}))

    monkeypatch.setattr(client, "_run_checked_command", run)

    client._upload_scheduled_featured_image(_PAGE_ID, image_path)

    assert commands[0][4] == "ata-blog-media"
    assert commands[0][5] == f"wp-content/uploads/publisher/scheduled/{_PAGE_ID}.webp"
    assert commands[0][7] == str(image_path)


def test_publish_recovers_scheduled_image_from_r2_when_no_local_copy_exists(
    tmp_path, monkeypatch
):
    """The due publisher's host has no local pipeline output for this post,
    but the scheduling host already mirrored it to R2; publish must recover it
    instead of failing with 'Featured image is required for publishing'."""

    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)
    key = f"wp-content/uploads/publisher/scheduled/{_PAGE_ID}.webp"
    remote_bytes = b"recovered-webp-bytes"
    remote_etag = _md5_hex(remote_bytes)

    client = AtaBlogClient.__new__(AtaBlogClient)

    def run(command, **_kwargs):
        if command[1:4] == ["r2", "objects", "list"]:
            if command[6] == key:
                return SimpleNamespace(
                    stdout=json.dumps(
                        [{"key": key, "size": len(remote_bytes), "etag": remote_etag}]
                    )
                )
            return SimpleNamespace(stdout=json.dumps([]))
        assert command[1:4] == ["r2", "objects", "get"]
        assert command[5] == key
        output_path = tmp_path / "posts" / _PAGE_ID / "featured_image.webp"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(remote_bytes)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(client, "_run_checked_command", run)

    resolved = client._resolve_featured_image_with_recovery(_PAGE_ID, None)

    expected_path = tmp_path / "posts" / _PAGE_ID / "featured_image.webp"
    assert resolved == expected_path
    assert resolved.read_bytes() == remote_bytes


def test_publish_recovery_rejects_downloaded_image_that_does_not_match_r2_etag(
    tmp_path, monkeypatch
):
    """A truncated or corrupted download must not silently publish bad bytes:
    verify it against the R2 object's recorded size/ETag before accepting it."""

    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)
    key = f"wp-content/uploads/publisher/scheduled/{_PAGE_ID}.webp"
    remote_bytes = b"recovered-webp-bytes"

    client = AtaBlogClient.__new__(AtaBlogClient)

    def run(command, **_kwargs):
        if command[1:4] == ["r2", "objects", "list"]:
            if command[6] == key:
                return SimpleNamespace(
                    stdout=json.dumps(
                        [{"key": key, "size": len(remote_bytes), "etag": _md5_hex(remote_bytes)}]
                    )
                )
            return SimpleNamespace(stdout=json.dumps([]))
        assert command[1:4] == ["r2", "objects", "get"]
        output_path = tmp_path / "posts" / _PAGE_ID / "featured_image.webp"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"truncated-and-wrong-bytes")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(client, "_run_checked_command", run)

    with pytest.raises(ClientError, match="does not match its R2 object"):
        client._resolve_featured_image_with_recovery(_PAGE_ID, None)

    assert not (tmp_path / "posts" / _PAGE_ID / "featured_image.webp").exists()


def test_publish_recovery_leaves_original_error_when_nothing_was_ever_scheduled(
    tmp_path, monkeypatch
):
    """No R2 object was ever uploaded for this page: the original local-lookup
    blocker must still be raised, unchanged."""

    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)
    client = AtaBlogClient.__new__(AtaBlogClient)

    def run(command, **_kwargs):
        assert command[1:4] == ["r2", "objects", "list"]
        return SimpleNamespace(stdout=json.dumps([]))

    monkeypatch.setattr(client, "_run_checked_command", run)

    with pytest.raises(ClientError, match="Featured image is required for publishing"):
        client._resolve_featured_image_with_recovery(_PAGE_ID, None)


def test_explicit_missing_featured_image_path_skips_r2_recovery(tmp_path, monkeypatch):
    """A caller-supplied --featured-image that is missing must fail exactly
    as before; recovery only applies to the implicit conventional lookup."""

    client = AtaBlogClient.__new__(AtaBlogClient)

    def run(command, **_kwargs):
        pytest.fail(f"unexpected R2 call for an explicit --featured-image: {command}")

    monkeypatch.setattr(client, "_run_checked_command", run)
    missing_path = str(tmp_path / "does-not-exist.png")

    with pytest.raises(ClientError, match=f"Featured image not found: {missing_path}"):
        client._resolve_featured_image_with_recovery(_PAGE_ID, missing_path)


# --- backfilling pages Scheduled before the R2 mirror existed --------------


def test_backfill_mirrors_local_images_for_pages_scheduled_before_the_mirror_existed(
    tmp_path, monkeypatch
):
    """A page `Scheduled` before `_upload_scheduled_featured_image` shipped has
    no R2 object; the backfill must mirror its still-local image so a later
    off-host `--status publish` run can recover it."""

    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)
    page_id = "a" * 32
    image_path = tmp_path / "posts" / page_id / "featured_image.webp"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"local-bytes")

    client = AtaBlogClient.__new__(AtaBlogClient)
    client.list_articles = lambda **_kwargs: [{"id": page_id}]

    put_commands = []

    def run(command, **_kwargs):
        if command[1:4] == ["r2", "objects", "list"]:
            return SimpleNamespace(stdout=json.dumps([]))
        assert command[1:4] == ["r2", "objects", "put"]
        put_commands.append(command)
        return SimpleNamespace(stdout=json.dumps({"key": command[5]}))

    monkeypatch.setattr(client, "_run_checked_command", run)

    result = client.backfill_scheduled_featured_images()

    assert result == {"mirrored": [page_id], "already_mirrored": [], "no_local_image": []}
    assert put_commands[0][5] == f"wp-content/uploads/publisher/scheduled/{page_id}.webp"


def test_backfill_skips_pages_already_mirrored(tmp_path, monkeypatch):
    """A page already mirrored to R2 must not be re-uploaded."""

    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)
    page_id = "b" * 32
    image_path = tmp_path / "posts" / page_id / "featured_image.webp"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"local-bytes")
    key = f"wp-content/uploads/publisher/scheduled/{page_id}.webp"

    client = AtaBlogClient.__new__(AtaBlogClient)
    client.list_articles = lambda **_kwargs: [{"id": page_id}]

    def run(command, **_kwargs):
        if command[1:4] == ["r2", "objects", "list"]:
            return SimpleNamespace(stdout=json.dumps([{"key": key, "size": 11}]))
        pytest.fail(f"unexpected R2 write for an already-mirrored page: {command}")

    monkeypatch.setattr(client, "_run_checked_command", run)

    result = client.backfill_scheduled_featured_images()

    assert result == {"mirrored": [], "already_mirrored": [page_id], "no_local_image": []}


def test_backfill_skips_pages_with_no_local_image_on_this_host(tmp_path, monkeypatch):
    """A page whose image only exists on a different host must be reported,
    not treated as an error that aborts the whole backfill."""

    monkeypatch.setattr(client_module, "STATIC_REPOSITORY_ROOT", tmp_path)
    page_id = "c" * 32

    client = AtaBlogClient.__new__(AtaBlogClient)
    client.list_articles = lambda **_kwargs: [{"id": page_id}]

    def run(command, **_kwargs):
        pytest.fail(f"unexpected R2 call for a page with no local image: {command}")

    monkeypatch.setattr(client, "_run_checked_command", run)

    result = client.backfill_scheduled_featured_images()

    assert result == {"mirrored": [], "already_mirrored": [], "no_local_image": [page_id]}
