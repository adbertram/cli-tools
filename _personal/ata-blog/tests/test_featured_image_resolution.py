"""Regression tests for featured image resolution during publishing."""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from ata_blog_cli.client import AtaBlogClient, ClientError
from ata_blog_cli.commands import notion_page


# Live-schema types for the Notion properties the publish path writes. Mirrors
# `notion database schema 2a317112-d9c8-42ee-a4d4-a2b8a5a20818`.
_PUBLISH_PROPERTY_TYPES = {
    "Status": "status",
    "Published URL": "url",
    "Publish Date": "date",
}


def test_notion_page_publish_missing_wordpress_tag_exits_nonzero(monkeypatch):
    """CLI publish validation errors must fail the process for shell loops/cron."""

    class FakeClient:
        def publish_article(self, *args, **kwargs):
            raise ClientError("WordPress tag(s) not found: Compliance, SOC 2")

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
    assert "Error: WordPress tag(s) not found: Compliance, SOC 2" in result.output


def test_resolves_conventional_featured_image_when_option_is_omitted(tmp_path, monkeypatch):
    """Headless publish should attach the pipeline image without a manual flag."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    image_path = tmp_path / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)

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
    monkeypatch.chdir(tmp_path)

    assert AtaBlogClient._resolve_featured_image(page_id, None) == webp_path


def test_reports_actionable_blocker_when_no_conventional_featured_image_exists(
    tmp_path, monkeypatch
):
    """Missing pipeline image should block before any WordPress publish attempt."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ClientError) as exc_info:
        AtaBlogClient._resolve_featured_image(page_id, None)

    message = str(exc_info.value)
    assert "Featured image is required for publishing" in message
    assert f"posts/{page_id}/featured_image.webp" in message
    assert "--featured-image PATH" in message


def test_explicit_featured_image_path_still_validates(tmp_path):
    """Manual featured image selection remains supported."""

    image_path = tmp_path / "selected.jpg"
    image_path.write_bytes(b"jpg-bytes")

    assert AtaBlogClient._resolve_featured_image("page-id", str(image_path)) == image_path


def test_resolve_tags_by_names_reports_all_missing_tags():
    """Bulk tag validation should report every Notion tag absent from WordPress."""

    client = object.__new__(AtaBlogClient)

    def fake_run_wordpress(args, timeout=60):
        if args == ["tags", "list", "--limit", "1000"]:
            tags = [
                {"id": 10, "name": "DevOps"},
                {"id": 11, "name": "Kubernetes"},
            ]
        else:
            tags = []
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(tags), stderr="")

    client._run_wordpress = fake_run_wordpress

    with pytest.raises(
        ClientError,
        match=r"WordPress tag\(s\) not found: Platform Engineering, Internal Developer Platform",
    ):
        client.resolve_tags_by_names([
            "DevOps",
            "Platform Engineering",
            "Kubernetes",
            "Internal Developer Platform",
        ])


def test_resolve_tags_by_names_falls_back_to_exact_filters_for_deep_catalog():
    """Tags absent from the first 1000-list page should resolve by exact filter."""

    client = object.__new__(AtaBlogClient)
    calls = []

    def fake_run_wordpress(args, timeout=60):
        calls.append(args)
        if args == ["tags", "list", "--limit", "1000"]:
            tags = [{"id": 10, "name": "DevOps"}]
        elif args == [
            "tags", "list", "--filter", "name:eq:Platform Engineering", "--limit", "1000"
        ]:
            tags = [{"id": 5649, "name": "Platform Engineering"}]
        elif args == ["tags", "list", "--filter", "name:eq:Security", "--limit", "1000"]:
            tags = [{"id": 5487, "name": "Security"}]
        else:
            pytest.fail(f"unexpected wordpress call: {args}")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(tags), stderr="")

    client._run_wordpress = fake_run_wordpress

    assert client.resolve_tags_by_names(["DevOps", "Platform Engineering", "Security"]) == [
        10,
        5649,
        5487,
    ]
    assert calls == [
        ["tags", "list", "--limit", "1000"],
        ["tags", "list", "--filter", "name:eq:Platform Engineering", "--limit", "1000"],
        ["tags", "list", "--filter", "name:eq:Security", "--limit", "1000"],
    ]


def test_publish_article_missing_wordpress_tag_blocks_before_side_effects(
    tmp_path, monkeypatch
):
    """Missing WordPress tags should fail readiness before media/upload/publish."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    image_path = tmp_path / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)

    client = object.__new__(AtaBlogClient)
    client._wordpress_checked = True
    # These tests pin the classic WordPress leg only. publish_article
    # dual-publishes whenever the P05/P13 handoff files exist on the machine,
    # so without this the harness would be routed into the static transaction
    # and would assert nothing about WordPress. Mirrors
    # test_static_publisher.py's dual-publish tests, which stub the same gate.
    # Dual-publish behavior is unchanged.
    client._static_cutover_active = lambda: False

    upload_calls = []

    def fake_upload_to_wordpress(path):
        upload_calls.append(path)
        return {"id": 123, "source_url": "https://example.com/featured.webp"}

    monkeypatch.setattr(
        "ata_blog_cli.utils.images.upload_to_wordpress",
        fake_upload_to_wordpress,
    )
    monkeypatch.setattr(
        "ata_blog_cli.utils.images.process_images_for_wordpress",
        lambda markdown_content, article_slug, verbose: markdown_content,
    )

    client.get_article = lambda _page_id: {
        "Title": "How to Secure Cloud Workloads",
        "Keywords": "cloud security",
        "Category": "Cloud",
        "Tags": "Azure,Platform Engineering",
        "Excerpt": "Secure cloud workloads.",
        "Schema Type": "TechArticle",
    }
    client.check_duplicate_post = lambda _slug: False
    client.resolve_category_by_name = lambda _name: 456

    def fake_resolve_tags_by_names(names):
        missing = [name for name in names if name == "Platform Engineering"]
        if missing:
            raise ClientError(f"WordPress tag(s) not found: {', '.join(missing)}")
        return [{"Azure": 10}[name] for name in names]

    client.resolve_tags_by_names = fake_resolve_tags_by_names
    client.find_next_schedule_slot = lambda: pytest.fail("schedule should not be reserved")
    client.get_article_markdown = lambda _page_id: pytest.fail("markdown should not be read")
    client._run_wordpress = lambda args: pytest.fail(f"wordpress should not run: {args}")
    client._run_notion = lambda args: pytest.fail(f"notion should not update: {args}")

    with pytest.raises(
        ClientError,
        match=r"WordPress tag\(s\) not found: Platform Engineering",
    ):
        client.publish_article(page_id, auto_schedule=True)

    assert upload_calls == []


def test_publish_article_reports_every_missing_wordpress_tag_at_once(
    tmp_path, monkeypatch
):
    """Publish readiness must resolve tags in bulk, not one name at a time.

    A per-name resolution loop raises on the first missing tag, so the operator
    fixes one tag, republishes, and hits the next one. The publish path must go
    through resolve_tags_by_names so a single failure names them all.
    """

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    image_path = tmp_path / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)

    client = object.__new__(AtaBlogClient)
    client._wordpress_checked = True
    client._static_cutover_active = lambda: False

    resolve_calls = []

    def fake_resolve_tags_by_names(names):
        resolve_calls.append(list(names))
        known = {"Azure": 10}
        missing = [name for name in names if name not in known]
        if missing:
            raise ClientError(f"WordPress tag(s) not found: {', '.join(missing)}")
        return [known[name] for name in names]

    monkeypatch.setattr(
        "ata_blog_cli.utils.images.upload_to_wordpress",
        lambda path: pytest.fail("featured image should not upload"),
    )

    client.get_article = lambda _page_id: {
        "Title": "How to Secure Cloud Workloads",
        "Keywords": "cloud security",
        "Category": "Cloud",
        "Tags": "Azure,Platform Engineering,Internal Developer Platform",
        "Excerpt": "Secure cloud workloads.",
        "Schema Type": "TechArticle",
    }
    client.check_duplicate_post = lambda _slug: False
    client.resolve_category_by_name = lambda _name: 456
    client.resolve_tags_by_names = fake_resolve_tags_by_names
    client.find_next_schedule_slot = lambda: pytest.fail("schedule should not be reserved")
    client.get_article_markdown = lambda _page_id: pytest.fail("markdown should not be read")
    client._run_wordpress = lambda args: pytest.fail(f"wordpress should not run: {args}")
    client._run_notion = lambda args: pytest.fail(f"notion should not update: {args}")

    with pytest.raises(
        ClientError,
        match=(
            r"WordPress tag\(s\) not found: "
            r"Platform Engineering, Internal Developer Platform"
        ),
    ):
        client.publish_article(page_id, auto_schedule=True)

    assert resolve_calls == [
        ["Azure", "Platform Engineering", "Internal Developer Platform"]
    ]


def test_publish_article_image_placeholder_blocks_before_side_effects(
    tmp_path, monkeypatch
):
    """IMAGE_PLACEHOLDER markers should fail before WordPress draft creation."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    image_path = tmp_path / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)

    client = object.__new__(AtaBlogClient)
    client._wordpress_checked = True
    # These tests pin the classic WordPress leg only. publish_article
    # dual-publishes whenever the P05/P13 handoff files exist on the machine,
    # so without this the harness would be routed into the static transaction
    # and would assert nothing about WordPress. Mirrors
    # test_static_publisher.py's dual-publish tests, which stub the same gate.
    # Dual-publish behavior is unchanged.
    client._static_cutover_active = lambda: False

    monkeypatch.setattr(
        "ata_blog_cli.utils.images.upload_to_wordpress",
        lambda path: pytest.fail("featured image should not upload"),
    )
    monkeypatch.setattr(
        "ata_blog_cli.utils.images.process_images_for_wordpress",
        lambda markdown_content, article_slug, verbose: pytest.fail("images should not process"),
    )

    client.get_article = lambda _page_id: {
        "Title": "How to Secure Cloud Workloads",
        "Keywords": "cloud security",
        "Category": "Cloud",
        "Tags": "Azure,Security",
        "Excerpt": "Secure cloud workloads.",
        "Schema Type": "TechArticle",
    }
    client.check_duplicate_post = lambda _slug: False
    client.resolve_category_by_name = lambda _name: 456
    client.resolve_tags_by_names = lambda names: [
        {"Azure": 10, "Security": 11}[name] for name in names
    ]
    client.find_next_schedule_slot = lambda: pytest.fail("schedule should not be reserved")
    client.get_article_markdown = (
        lambda _page_id: "# Article\n\nIMAGE_PLACEHOLDER: DevOps-to-MLOps skill map\n"
    )
    client._run_wordpress = lambda args: pytest.fail(f"wordpress should not run: {args}")
    client._run_notion = lambda args: pytest.fail(f"notion should not update: {args}")

    with pytest.raises(ClientError) as exc_info:
        client.publish_article(page_id, auto_schedule=True)

    message = str(exc_info.value)
    assert "IMAGE_PLACEHOLDER marker(s) remain in Notion article content" in message
    assert "line 3: IMAGE_PLACEHOLDER: DevOps-to-MLOps skill map" in message


def test_publish_article_shortens_long_notion_excerpt_before_wordpress_create(
    tmp_path, monkeypatch
):
    """Overlong Notion excerpts should not make headless publishing fail."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    image_path = tmp_path / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)

    client = object.__new__(AtaBlogClient)
    client._wordpress_checked = True
    # These tests pin the classic WordPress leg only. publish_article
    # dual-publishes whenever the P05/P13 handoff files exist on the machine,
    # so without this the harness would be routed into the static transaction
    # and would assert nothing about WordPress. Mirrors
    # test_static_publisher.py's dual-publish tests, which stub the same gate.
    # Dual-publish behavior is unchanged.
    client._static_cutover_active = lambda: False
    client._property_types_cache = dict(_PUBLISH_PROPERTY_TYPES)
    long_excerpt = " ".join(["Managed identity keeps AKS secrets safer"] * 14)

    monkeypatch.setattr(
        "ata_blog_cli.utils.images.upload_to_wordpress",
        lambda path: {"id": 123, "source_url": "https://example.com/featured.webp"},
    )
    monkeypatch.setattr(
        "ata_blog_cli.utils.images.process_images_for_wordpress",
        lambda markdown_content, article_slug, verbose: markdown_content,
    )

    client.get_article = lambda page_id: {
        "Title": "How to Secure Cloud Workloads",
        "Keywords": "cloud security",
        "Category": "Cloud",
        "Tags": "Azure,Security",
        "Excerpt": long_excerpt,
        "Schema Type": "TechArticle",
    }
    client.check_duplicate_post = lambda slug: False
    client.resolve_category_by_name = lambda name: 456
    client.resolve_tags_by_names = lambda names: [
        {"Azure": 10, "Security": 11}[name] for name in names
    ]
    client.get_article_markdown = lambda page_id: "# Article"

    create_excerpts = []

    def fake_run_wordpress(args, timeout=60):
        if args[:3] == ["posts", "get", "789"]:
            # publish_article re-reads the committed post to resolve its real
            # permalink instead of trusting the create response's link.
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {
                        "id": 789,
                        "status": "publish",
                        "slug": "post",
                        "link": "https://example.com/post",
                    }
                ),
                stderr="",
            )
        if args[:2] == ["posts", "create"]:
            excerpt = args[args.index("--excerpt") + 1]
            create_excerpts.append(excerpt)
            assert len(excerpt) <= 300
            assert len(excerpt) < len(long_excerpt)
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {
                        "id": 789,
                        "link": "https://example.com/post",
                        "date": "2026-06-12T09:00:00",
                    }
                ),
                stderr="",
            )
        if args[:2] == ["posts", "update"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps({"id": 789, "featured_media": 123}),
                stderr="",
            )
        raise AssertionError(args)

    notion_updates = []
    client._run_wordpress = fake_run_wordpress
    client._run_notion = lambda args, timeout=60: notion_updates.append(args) or subprocess.CompletedProcess(
        args, 0, stdout="{}", stderr=""
    )

    result = client.publish_article(page_id, status="publish")

    assert len(long_excerpt) > 300
    assert create_excerpts
    assert result["warnings"] == [
        "Excerpt shortened for WordPress SEO meta description: "
        f"{len(long_excerpt)} -> {len(create_excerpts[0])} characters"
    ]
    assert notion_updates == [
        [
            "database",
            "page",
            "update",
            page_id,
            "--status",
            "Status:Published",
            "--properties",
            json.dumps(
                {
                    "Published URL": {"url": "https://example.com/post"},
                    "Publish Date": {"date": {"start": "2026-06-12T09:00:00"}},
                }
            ),
        ]
    ]


def test_publish_article_auto_schedule_uses_conventional_featured_image(
    tmp_path, monkeypatch
):
    """Auto-scheduled publish should upload and attach the generated pipeline image."""

    page_id = "3495d9c85b2b81eebac8e532046b5b58"
    image_path = tmp_path / "posts" / page_id / "featured_image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)

    client = object.__new__(AtaBlogClient)
    client._wordpress_checked = True
    # These tests pin the classic WordPress leg only. publish_article
    # dual-publishes whenever the P05/P13 handoff files exist on the machine,
    # so without this the harness would be routed into the static transaction
    # and would assert nothing about WordPress. Mirrors
    # test_static_publisher.py's dual-publish tests, which stub the same gate.
    # Dual-publish behavior is unchanged.
    client._static_cutover_active = lambda: False
    client._property_types_cache = dict(_PUBLISH_PROPERTY_TYPES)

    uploaded_paths = []

    def fake_upload_to_wordpress(path):
        uploaded_paths.append(path)
        return {"id": 123, "source_url": "https://example.com/featured.webp"}

    monkeypatch.setattr(
        "ata_blog_cli.utils.images.upload_to_wordpress",
        fake_upload_to_wordpress,
    )
    monkeypatch.setattr(
        "ata_blog_cli.utils.images.process_images_for_wordpress",
        lambda markdown_content, article_slug, verbose: markdown_content,
    )

    client.get_article = lambda _page_id: {
        "Title": "How to Secure Cloud Workloads",
        "Keywords": "cloud security",
        "Category": "Cloud",
        "Tags": "Azure,Security",
        "Excerpt": "Secure cloud workloads.",
        "Schema Type": "TechArticle",
    }
    client.check_duplicate_post = lambda _slug: False
    client.resolve_category_by_name = lambda _name: 456
    client.resolve_tags_by_names = lambda names: [
        {"Azure": 10, "Security": 11}[name] for name in names
    ]
    client.find_next_schedule_slot = lambda: "2026-06-12T09:00:00"
    client.clear_schedule_reservation = lambda: None
    client.get_article_markdown = lambda _page_id: "# Article"

    def fake_run_wordpress(args):
        if args[:3] == ["posts", "get", "789"]:
            # A scheduled post has no permalink yet, so publish_article builds
            # its canonical URL from the post's own slug.
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {
                        "id": 789,
                        "status": "future",
                        "slug": "post",
                        "link": "https://example.com/?p=789",
                    }
                ),
                stderr="",
            )
        if args[:2] == ["posts", "create"]:
            assert "--featured-media" not in args
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {
                        "id": 789,
                        "link": "https://example.com/post",
                        "date": "2026-06-12T09:00:00",
                    }
                ),
                stderr="",
            )
        if args[:2] == ["posts", "update"]:
            assert args[-1] == "789"
            assert args[2:4] == ["--featured-media", "123"]
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps({"id": 789, "featured_media": 123}),
                stderr="",
            )
        raise AssertionError(args)

    notion_updates = []
    client._run_wordpress = fake_run_wordpress
    client._run_notion = lambda args: notion_updates.append(args) or subprocess.CompletedProcess(
        args, 0, stdout="{}", stderr=""
    )

    result = client.publish_article(page_id, auto_schedule=True)

    assert uploaded_paths == [image_path]
    assert result["status"] == "future"
    assert result["scheduled_date"] == "2026-06-12T09:00:00"
    assert result["featured_image"]["attached"] is True
    assert result["featured_image"]["media_id"] == 123
    assert notion_updates == [
        [
            "database",
            "page",
            "update",
            page_id,
            "--status",
            "Status:Published",
            "--properties",
            json.dumps(
                {
                    "Published URL": {"url": "https://example.com/post/"},
                    "Publish Date": {"date": {"start": "2026-06-12T09:00:00"}},
                }
            ),
        ]
    ]
