"""Regression tests for Notion article creation."""

from __future__ import annotations

import json
import subprocess
from typing import Any, cast

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


def test_create_article_sets_exact_idea_status_in_properties_by_default(monkeypatch):
    """A template's changed default must not move a new idea to Not Started."""
    client, captured = _client_with_captured_notion_call(monkeypatch)

    result = client.create_article(
        title="Microsoft Azure Certification Roadmap",
        excerpt="Choose the right certification path.",
        category="IT Ops",
        keywords="azure certification roadmap",
    )

    assert result == {"id": "created-page"}
    assert _properties_from_create_args(captured[0])["Status"] == {
        "status": {"name": "Idea"}
    }
    assert "--status" not in captured[0]


def test_create_article_sets_explicit_status_in_properties(monkeypatch):
    """Explicit status overrides use the same template-safe property payload."""
    client, captured = _client_with_captured_notion_call(monkeypatch)

    client.create_article(
        title="Article",
        excerpt="Description",
        category="Cloud",
        status="Good Idea",
    )

    assert _properties_from_create_args(captured[0])["Status"] == {
        "status": {"name": "Good Idea"}
    }
    assert "--status" not in captured[0]