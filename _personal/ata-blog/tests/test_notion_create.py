"""Regression tests for Notion article creation."""

from __future__ import annotations

import json
import subprocess
from typing import Any, cast

import pytest

import ata_blog_cli.client as client_module
from ata_blog_cli.client import AtaBlogClient


def _client_with_captured_notion_call(monkeypatch):
    client = object.__new__(AtaBlogClient)
    cast(Any, client).config = type("Config", (), {"notion_database_id": "database-id"})()
    captured = []

    def fake_run_notion(args):
        captured.append(args)
        return subprocess.CompletedProcess(
            args, 0, stdout='{"id":"created-page"}', stderr=""
        )

    monkeypatch.setattr(client, "_run_notion", fake_run_notion)
    return client, captured


def _properties_from_create_args(args):
    return json.loads(args[args.index("--properties") + 1])


@pytest.fixture
def category_terms(tmp_path, monkeypatch):
    site = tmp_path / "static-site"
    terms_path = site / "src" / "data" / "terms.json"
    terms_path.parent.mkdir(parents=True)
    terms_path.write_text(
        json.dumps(
            {
                "categories": [{"id": 1, "name": "AI", "slug": "ai", "count": 0}],
                "tags": [],
            }
        )
    )
    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", site)


def test_create_article_sets_exact_idea_status_in_properties_by_default(monkeypatch, category_terms):
    """A template's changed default must not move a new idea to Not Started."""
    client, captured = _client_with_captured_notion_call(monkeypatch)

    result = client.create_article(
        title="Microsoft Azure Certification Roadmap",
        excerpt="Choose the right certification path.",
        category="AI",
        keywords="azure certification roadmap",
    )

    assert result == {"id": "created-page"}
    assert _properties_from_create_args(captured[0])["Status"] == {
        "status": {"name": "Idea"}
    }
    assert "--status" not in captured[0]
    assert _properties_from_create_args(captured[0])["Category"] == {
        "select": {"name": "AI"}
    }


def test_create_article_sets_explicit_status_in_properties(monkeypatch, category_terms):
    """Explicit status overrides use the same template-safe property payload."""
    client, captured = _client_with_captured_notion_call(monkeypatch)

    client.create_article(
        title="Article",
        excerpt="Description",
        category="AI",
        status="Good Idea",
    )

    assert _properties_from_create_args(captured[0])["Status"] == {
        "status": {"name": "Good Idea"}
    }
    assert "--status" not in captured[0]


def test_create_article_rejects_category_absent_from_static_taxonomy(monkeypatch, category_terms):
    client, captured = _client_with_captured_notion_call(monkeypatch)

    with pytest.raises(client_module.ClientError, match="Invalid category 'Cloud'. Must be one of: AI"):
        client.create_article(title="Article", excerpt="Description", category="Cloud")

    assert captured == []
