"""Regression tests for markdown content sent to Notion."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ata_blog_cli.client import (
    NOTION_CONTENT_WRITE_TIMEOUT_SECONDS,
    AtaBlogClient,
    ClientError,
)
from ata_blog_cli.commands import notion_page


def test_set_article_content_maps_text_code_fence_to_plain_text(tmp_path, monkeypatch):
    """Notion rejects code block language 'text'; the CLI must submit 'plain text'."""

    source = tmp_path / "post.md"
    source.write_text("# Title\n\n```text\nliteral output\n```\n", encoding="utf-8")

    client = object.__new__(AtaBlogClient)
    submitted_markdown = None
    submitted_timeout = None

    def fake_run_notion(args, timeout=60):
        nonlocal submitted_markdown, submitted_timeout
        assert args[:5] == ["database", "page", "content", "set", "page-id"]
        submitted_path = Path(args[args.index("--file") + 1])
        submitted_markdown = submitted_path.read_text(encoding="utf-8")
        submitted_timeout = timeout
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(client, "_run_notion", fake_run_notion)
    monkeypatch.setattr(client, "get_article_markdown", lambda _page_id: submitted_markdown)

    result = client.set_article_content("page-id", str(source))

    assert result == {"success": True}
    assert submitted_markdown == "# Title\n\n```plain text\nliteral output\n```\n"
    assert submitted_timeout == NOTION_CONTENT_WRITE_TIMEOUT_SECONDS


def test_content_set_command_submits_plain_text_code_fence(tmp_path, monkeypatch):
    """The user-facing content set command must submit Notion-safe markdown."""

    source = tmp_path / "post.md"
    source.write_text("# Title\n\n```text\nliteral output\n```\n", encoding="utf-8")

    client = object.__new__(AtaBlogClient)
    submitted_markdown = None

    def fake_process_images(markdown_content, base_dir, verbose):
        assert markdown_content == source.read_text(encoding="utf-8")
        assert base_dir == source.parent
        assert verbose is True
        return markdown_content, 0

    def fake_run_notion(args, timeout=60):
        nonlocal submitted_markdown
        assert args[:5] == ["database", "page", "content", "set", "page-id"]
        assert timeout == NOTION_CONTENT_WRITE_TIMEOUT_SECONDS
        submitted_path = Path(args[args.index("--file") + 1])
        submitted_markdown = submitted_path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(client, "_run_notion", fake_run_notion)
    monkeypatch.setattr(client, "get_article_markdown", lambda _page_id: submitted_markdown)
    monkeypatch.setattr(notion_page, "get_client", lambda: client)
    monkeypatch.setattr(notion_page, "process_local_images_for_wordpress", fake_process_images)

    result = CliRunner().invoke(
        notion_page.app,
        ["content", "set", "page-id", "--file", str(source)],
    )

    assert result.exit_code == 0, result.output
    assert submitted_markdown == "# Title\n\n```plain text\nliteral output\n```\n"


def test_get_article_markdown_rejects_silent_empty_export(monkeypatch):
    client = object.__new__(AtaBlogClient)

    def fake_run_notion(args):
        Path(args[args.index("--out-file") + 1]).write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(client, "_run_notion", fake_run_notion)

    with pytest.raises(ClientError, match="prior content sync did not persist"):
        client.get_article_markdown("page-id")


def test_set_article_content_rejects_unreadable_post_sync_state(tmp_path, monkeypatch):
    source = tmp_path / "post.md"
    source.write_text("# Synced content\n", encoding="utf-8")
    client = object.__new__(AtaBlogClient)
    monkeypatch.setattr(
        client,
        "_run_notion_with_normalized_markdown_file",
        lambda args, file_path, timeout: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )

    def unreadable(_page_id):
        raise ClientError("empty export")

    monkeypatch.setattr(client, "get_article_markdown", unreadable)

    with pytest.raises(ClientError, match="did not persist readable blocks"):
        client.set_article_content("page-id", str(source))


def test_run_notion_reports_exit_code_command_and_empty_diagnostics(monkeypatch):
    client = object.__new__(AtaBlogClient)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 7, stdout="", stderr=""),
    )

    with pytest.raises(ClientError) as exc_info:
        client._run_notion(["database", "page", "get", "page-id"])

    message = str(exc_info.value)
    assert "exit 7" in message
    assert "no diagnostic output" in message
    assert "notion database page get page-id" in message
