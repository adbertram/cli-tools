"""Tests for the notion-page unpublish command logic."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ata_blog_cli.client import AtaBlogClient, ClientError
from ata_blog_cli.commands import notion_page

PAGE_ID = "31b5d9c85b2b812f935cd753aa60315f"
STATIC_POST = Path("/corpus/notion-31b5d9c85b2b812f935cd753aa60315f-my-post.md")


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
    """Build a client with a stubbed schema, corpus lookups, and recorded calls."""
    client = object.__new__(AtaBlogClient)
    client.config = FakeConfig()
    client._property_types_cache = dict(_SCHEMA_PROPERTY_TYPES)
    client.notion_calls = []
    client.static_transactions = []

    def fake_run_notion(args, timeout=60):
        client.notion_calls.append(args)
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({"ok": True}), stderr=""
        )

    def fake_static_transaction(*, page_id, static_post, status):
        client.static_transactions.append((page_id, static_post, status))
        return {
            "deployment_id": "preview-id",
            "promotion_id": "production-id",
            "release_ref": {"release_id": "r", "contract_hash": "c"},
            "backup_path": "/profile/backup",
            "retired_transactions": [],
        }

    client._run_notion = fake_run_notion
    client._unpublish_static_transaction = fake_static_transaction
    # The corpus binds a static-originated post to its Notion page id and an
    # imported post to its slug.
    client._find_static_post_by_notion_page_id = (
        lambda page_id: STATIC_POST if page_id == PAGE_ID else None
    )
    client._find_static_post = lambda slug: STATIC_POST if slug == "my-post" else None
    # Live statuses path (used to validate the target status).
    client.get_valid_statuses = lambda: ["Draft", "Published", "Idea"]
    return client


# --- id-kind detection -------------------------------------------------------


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("31b5d9c8-5b2b-812f-935c-d753aa60315f", "notion_page"),
        ("31b5d9c85b2b812f935cd753aa60315f", "notion_page"),
        ("26985", "slug"),
        ("https://adamtheautomator.com/my-post/", "url"),
        ("http://example.com/foo", "url"),
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


def test_resolve_from_notion_page_binds_by_page_id():
    client = _make_client()
    client.get_article = lambda pid: {"id": "31b5d9c8-5b2b-812f-935c-d753aa60315f"}

    resolved = client.resolve_unpublish_target(PAGE_ID)

    assert resolved["id_kind"] == "notion_page"
    assert resolved["static_post"] == STATIC_POST


def test_resolve_imported_post_binds_by_published_url_slug():
    """An imported post carries no Notion page id, so its slug identifies it."""
    client = _make_client()
    client._find_static_post_by_notion_page_id = lambda page_id: None
    client.get_article = lambda pid: {
        "id": pid,
        "Published URL": "https://adamtheautomator.com/my-post/",
    }

    resolved = client.resolve_unpublish_target(PAGE_ID)

    assert resolved["slug"] == "my-post"
    assert resolved["static_post"] == STATIC_POST


def test_resolve_from_notion_page_absent_from_corpus():
    """A reverted page with no corpus record resolves the static side as absent."""
    client = _make_client()
    client._find_static_post_by_notion_page_id = lambda page_id: None
    client.get_article = lambda pid: {"id": pid, "Published URL": None}

    resolved = client.resolve_unpublish_target(PAGE_ID)

    assert resolved["static_post"] is None


@pytest.mark.parametrize(
    "identifier", ["https://adamtheautomator.com/my-post/", "my-post"]
)
def test_resolve_from_url_or_slug_finds_notion_page_by_published_url(identifier):
    client = _make_client()
    looked_up = []

    def by_url(url):
        looked_up.append(url)
        return {"id": PAGE_ID}

    client._notion_page_by_published_url = by_url

    resolved = client.resolve_unpublish_target(identifier)

    assert resolved["static_post"] == STATIC_POST
    assert looked_up == ["https://adamtheautomator.com/my-post/"]


def test_resolve_from_slug_fails_when_corpus_has_no_post():
    client = _make_client()
    with pytest.raises(ClientError, match="Could not resolve a static post"):
        client.resolve_unpublish_target("no-such-post")


def test_resolve_from_slug_fails_when_no_notion_match():
    client = _make_client()
    client._notion_page_by_published_url = lambda url: None

    with pytest.raises(ClientError, match="Could not resolve a Notion page"):
        client.resolve_unpublish_target("my-post")


# --- dry-run makes zero mutating calls --------------------------------------


def test_dry_run_makes_no_mutating_calls():
    client = _make_client()
    client.get_article = lambda pid: {"id": pid}

    summary = client.unpublish_article(PAGE_ID, dry_run=True)

    assert summary["dry_run"] is True
    assert summary["static"] == {
        "slug": None,
        "article_path": str(STATIC_POST),
        "action": "removed",
    }
    assert summary["notion"]["status"] == "Draft"
    assert summary["notion"]["cleared_fields"] == list(
        AtaBlogClient.UNPUBLISH_ARTIFACT_FIELDS
    )
    assert client.notion_calls == []
    assert client.static_transactions == []


def test_real_run_removes_the_static_post_through_the_transaction():
    client = _make_client()
    client.get_article = lambda pid: {"id": pid}

    summary = client.unpublish_article(PAGE_ID, status="Draft", dry_run=False)

    assert client.static_transactions == [(PAGE_ID, STATIC_POST, "Draft")]
    assert summary["static"]["action"] == "removed"
    assert summary["static"]["promotion_id"] == "production-id"
    assert summary["static"]["backup_path"] == "/profile/backup"
    # The transaction owns the Notion reset, so it is not issued a second time.
    assert client.notion_calls == []


def test_real_run_with_no_corpus_record_only_resets_notion():
    client = _make_client()
    client._find_static_post_by_notion_page_id = lambda page_id: None
    client.get_article = lambda pid: {"id": pid, "Published URL": None}

    summary = client.unpublish_article(PAGE_ID, dry_run=False)

    assert summary["static"]["action"] == "already_absent"
    assert client.static_transactions == []
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


# --- command surface ---------------------------------------------------------


class _RecordingClient:
    def __init__(self):
        self.calls = []

    def unpublish_article(self, identifier, *, status, dry_run):
        self.calls.append((identifier, status, dry_run))
        return {
            "dry_run": dry_run,
            "id_kind": "slug",
            "static": {"slug": "my-post", "article_path": "/x.md", "action": "removed"},
            "notion": {"page_id": PAGE_ID, "status": status, "cleared_fields": []},
        }


def test_command_declined_confirmation_never_mutates(monkeypatch):
    client = _RecordingClient()
    monkeypatch.setattr(notion_page, "get_client", lambda: client)

    result = CliRunner().invoke(notion_page.app, ["unpublish", "my-post"], input="n\n")

    assert result.exit_code == 1
    assert client.calls == [("my-post", "Draft", True)]


def test_command_yes_runs_without_prompt(monkeypatch):
    client = _RecordingClient()
    monkeypatch.setattr(notion_page, "get_client", lambda: client)

    result = CliRunner().invoke(notion_page.app, ["unpublish", "my-post", "--yes"])

    assert result.exit_code == 0
    assert client.calls == [("my-post", "Draft", False)]


def test_command_rejects_the_removed_force_option(monkeypatch):
    client = _RecordingClient()
    monkeypatch.setattr(notion_page, "get_client", lambda: client)

    result = CliRunner().invoke(
        notion_page.app, ["unpublish", "my-post", "--yes", "--force"]
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert client.calls == []
