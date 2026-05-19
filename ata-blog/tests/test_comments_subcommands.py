"""Tests for `ata-blog notion-page comments` subcommand surface.

These tests assert the CLI exposes a `comments` command group with `add`
and `list` subcommands, and that the `add` help advertises the `--body`
flag. They do not call the live Notion API.
"""
from __future__ import annotations

import subprocess


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ata-blog", *args], capture_output=True, text=True, check=False
    )


def test_comments_group_lists_add_and_list_subcommands() -> None:
    result = _run("notion-page", "comments", "--help")
    assert result.returncode == 0, result.stderr
    assert "add" in result.stdout
    assert "list" in result.stdout


def test_comments_add_help_exposes_body_flag() -> None:
    result = _run("notion-page", "comments", "add", "--help")
    assert result.returncode == 0, result.stderr
    assert "--body" in result.stdout
    assert "PAGE_ID" in result.stdout


def test_comments_list_help_takes_page_id() -> None:
    result = _run("notion-page", "comments", "list", "--help")
    assert result.returncode == 0, result.stderr
    assert "PAGE_ID" in result.stdout


def test_comments_add_requires_body() -> None:
    # Missing --body must produce a non-zero exit and the required-flag message.
    result = _run("notion-page", "comments", "add", "deadbeef")
    assert result.returncode != 0
    assert "--body" in (result.stderr + result.stdout)
