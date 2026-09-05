"""Tests for the notion-page unpublish command logic."""

from __future__ import annotations

import json
import subprocess

import pytest

from ata_blog_cli.client import AtaBlogClient, ClientError


# Live schema property types for the artifact fields under test, mirroring the
# real ATA Blog Notion database.
_SCHEMA_PROPERTY_TYPES = {
    "Published URL": "url",
    "X Post URL": "url",
    "LinkedIn Post URL": "url",
    "Publish Date": "date",
    "Promoted": "checkbox",
    "Status": "status",
}


class FakeConfig:
    notion_database_id = "2a317112-d9c8-42ee-a4d4-a2b8a5a20818"


def _make_client():
    """Build a client with a stubbed schema and recorded notion/WP calls."""
    client = object.__new__(AtaBlogClient)
    client.config = FakeConfig()
    client._property_types_cache = dict(_SCHEMA_PROPERTY_TYPES)
    client.notion_calls = []
    client.wordpress_calls = []

    def fake_run_notion(args, timeout=60):
        client.notion_calls.append(args)
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({"ok": True}), stderr=""
        )

    def fake_run_wordpress(args, timeout=60):
        client.wordpress_calls.append(args)
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({"ok": True}), stderr=""
        )

    client._run_notion = fake_run_notion
    client._run_wordpress = fake_run_wordpress
    # Live statuses path (used to validate the target status).
    client.get_valid_statuses = lambda: ["Draft", "Published", "Idea"]
    return client


# --- id-kind detection -------------------------------------------------------


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("31b5d9c8-5b2b-812f-935c-d753aa60315f", "notion_page"),
        ("31b5d9c85b2b812f935cd753aa60315f", "notion_page"),
        ("26985", "wordpress_id"),
        ("https://adamtheautomator.com/my-post/", "wordpress_url"),
        ("http://example.com/foo", "wordpress_url"),
        ("my-post-slug", "slug"),
        ("identity-proofing-service-desk", "slug"),
    ],
)
def test_detect_id_kind(identifier, expected):
    assert AtaBlogClient.detect_id_kind(identifier) == expected


def test_detect_id_kind_rejects_empty():
    with pytest.raises(ClientError, match="must not be empty"):
        AtaBlogClient.detect_id_kind("   ")


def test_slug_from_url():
    assert (
        AtaBlogClient._slug_from_url("https://adamtheautomator.com/my-post/")
        == "my-post"
    )
    assert (
        AtaBlogClient._slug_from_url("https://adamtheautomator.com/my-post")
        == "my-post"
    )


def test_slug_from_url_rejects_pathless():
    with pytest.raises(ClientError, match="Cannot derive a slug"):
        AtaBlogClient._slug_from_url("https://adamtheautomator.com/")


# --- data-driven artifact field clearing ------------------------------------


def test_artifact_fields_clear_to_typed_payloads():
    """update_article must send typed nulls/empties + checkbox bool."""
    client = _make_client()

    client.update_article(
        "page123",
        status="Draft",
        properties=dict(AtaBlogClient.UNPUBLISH_ARTIFACT_FIELDS),
    )

    # One notion update call, carrying the --properties JSON payload.
    assert len(client.notion_calls) == 1
    args = client.notion_calls[0]
    assert args[:4] == ["database", "page", "update", "page123"]
    assert "--status" in args and "Status:Draft" in args
    idx = args.index("--properties")
    payload = json.loads(args[idx + 1])
    assert payload == {
        "Published URL": {"url": None},
        "X Post URL": {"url": None},
        "LinkedIn Post URL": {"url": None},
        "Publish Date": {"date": None},
        "Promoted": {"checkbox": False},
    }


def test_artifact_field_set_matches_spec():
    """The data-driven artifact set must not touch protected fields."""
    fields = set(AtaBlogClient.UNPUBLISH_ARTIFACT_FIELDS)
    assert fields == {
        "Published URL",
        "X Post URL",
        "LinkedIn Post URL",
        "Publish Date",
        "Promoted",
    }
    protected = {"Keywords", "Tags", "Category", "Schema Type", "Stage Date"}
    assert not (fields & protected)


# --- resolution --------------------------------------------------------------


def test_resolve_from_notion_page_with_published_url():
    client = _make_client()
    client.get_article = lambda pid: {
        "id": pid,
        "Published URL": "https://adamtheautomator.com/my-post/",
    }
    client._wordpress_post_by_slug = lambda slug: (
        {"id": 555, "slug": slug, "status": "publish",
         "link": "https://adamtheautomator.com/my-post/"}
        if slug == "my-post"
        else None
    )

    resolved = client.resolve_unpublish_target("31b5d9c85b2b812f935cd753aa60315f")
    assert resolved["id_kind"] == "notion_page"
    assert resolved["wordpress_post"]["id"] == 555
    assert resolved["notion_page"]["id"] == "31b5d9c85b2b812f935cd753aa60315f"


def test_resolve_from_notion_page_without_published_url():
    """A reverted page (no Published URL) resolves WP side as absent."""
    client = _make_client()
    client.get_article = lambda pid: {"id": pid, "Published URL": None}

    resolved = client.resolve_unpublish_target("31b5d9c85b2b812f935cd753aa60315f")
    assert resolved["wordpress_post"] is None


def test_resolve_from_wordpress_id_fails_when_no_notion_match():
    client = _make_client()
    client._run_wordpress = lambda args, timeout=60: subprocess.CompletedProcess(
        args, 0,
        stdout=json.dumps({"id": 26985, "link": "https://x/p/"}),
        stderr="",
    )
    client._notion_page_by_published_url = lambda url: None

    with pytest.raises(ClientError, match="Could not resolve a Notion page"):
        client.resolve_unpublish_target("26985")


# --- dry-run makes zero mutating calls --------------------------------------


def test_dry_run_makes_no_mutating_calls():
    client = _make_client()
    client.get_article = lambda pid: {
        "id": pid,
        "Published URL": "https://adamtheautomator.com/my-post/",
    }
    client._wordpress_post_by_slug = lambda slug: {
        "id": 555, "slug": slug, "status": "publish",
        "link": "https://adamtheautomator.com/my-post/",
    }

    summary = client.unpublish_article(
        "31b5d9c85b2b812f935cd753aa60315f", dry_run=True
    )

    assert summary["dry_run"] is True
    assert summary["wordpress"] == {"post_id": 555, "action": "trashed"}
    assert summary["notion"]["status"] == "Draft"
    assert summary["notion"]["cleared_fields"] == list(
        AtaBlogClient.UNPUBLISH_ARTIFACT_FIELDS
    )
    # No notion update and no wordpress delete should have been issued.
    assert client.notion_calls == []
    assert all(c[:2] != ["posts", "delete"] for c in client.wordpress_calls)


def test_real_run_trashes_and_resets():
    client = _make_client()
    client.get_article = lambda pid: {
        "id": pid,
        "Published URL": "https://adamtheautomator.com/my-post/",
    }
    client._wordpress_post_by_slug = lambda slug: {
        "id": 555, "slug": slug, "status": "publish",
        "link": "https://adamtheautomator.com/my-post/",
    }

    summary = client.unpublish_article(
        "31b5d9c85b2b812f935cd753aa60315f", dry_run=False
    )

    assert summary["wordpress"] == {"post_id": 555, "action": "trashed"}
    # WordPress delete issued (trash, no --force).
    delete_calls = [c for c in client.wordpress_calls if c[:2] == ["posts", "delete"]]
    assert delete_calls == [["posts", "delete", "555"]]
    # Notion update issued with the artifact payload.
    assert len(client.notion_calls) == 1


def test_force_permanently_deletes():
    client = _make_client()
    client.get_article = lambda pid: {
        "id": pid,
        "Published URL": "https://adamtheautomator.com/my-post/",
    }
    client._wordpress_post_by_slug = lambda slug: {
        "id": 555, "slug": slug, "status": "publish",
        "link": "https://adamtheautomator.com/my-post/",
    }

    summary = client.unpublish_article(
        "31b5d9c85b2b812f935cd753aa60315f", force=True, dry_run=False
    )

    assert summary["wordpress"]["action"] == "deleted"
    delete_calls = [c for c in client.wordpress_calls if c[:2] == ["posts", "delete"]]
    assert delete_calls == [["posts", "delete", "555", "--force"]]


def test_keep_wordpress_skips_delete():
    client = _make_client()
    client.get_article = lambda pid: {
        "id": pid,
        "Published URL": "https://adamtheautomator.com/my-post/",
    }
    client._wordpress_post_by_slug = lambda slug: {
        "id": 555, "slug": slug, "status": "publish",
        "link": "https://adamtheautomator.com/my-post/",
    }

    summary = client.unpublish_article(
        "31b5d9c85b2b812f935cd753aa60315f", keep_wordpress=True, dry_run=False
    )

    assert summary["wordpress"] == {"post_id": 555, "action": "skipped"}
    assert all(c[:2] != ["posts", "delete"] for c in client.wordpress_calls)
    # Notion reset still happens.
    assert len(client.notion_calls) == 1


def test_invalid_status_rejected_before_resolution():
    client = _make_client()
    called = {"resolved": False}

    def _resolve(_id):
        called["resolved"] = True
        return {}

    client.resolve_unpublish_target = _resolve

    with pytest.raises(ClientError, match="Invalid status"):
        client.unpublish_article("page", status="Bogus", dry_run=True)
    assert called["resolved"] is False
