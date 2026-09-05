"""Regression tests for WordPress get passthrough options."""

from __future__ import annotations

import re
import subprocess

from typer.testing import CliRunner

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

from ata_blog_cli.commands import wordpress_admin, wordpress_menu, wordpress_page, wordpress_post


def test_wordpress_post_get_forwards_properties_and_raw(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_post.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_post.app,
        ["get", "--properties", "id,title,slug,content", "--raw", "26705"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "posts",
            "get",
            "--properties",
            "id,title,slug,content",
            "--raw",
            "26705",
        ]
    ]


def test_wordpress_post_update_forwards_featured_media(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_post.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_post.app,
        ["update", "--featured-media", "123", "789"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "posts",
            "update",
            "--featured-media",
            "123",
            "789",
        ]
    ]


def test_wordpress_post_update_forwards_content_file_after_post_id(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_post.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_post.app,
        ["update", "26786", "--content-file", "post.html"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "posts",
            "update",
            "--content-file",
            "post.html",
            "26786",
        ]
    ]


def test_wordpress_post_update_forwards_all_content_options(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_post.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_post.app,
        [
            "update",
            "26786",
            "--title",
            "New Title",
            "--content",
            "<p>Body</p>",
            "--status",
            "draft",
            "--slug",
            "new-slug",
            "--date",
            "2026-08-01T09:00:00",
            "--featured-media",
            "123",
            "--excerpt",
            "Short summary",
            "--meta",
            "rank_math_title=SEO Title",
            "--meta",
            "rank_math_description=SEO Description",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "posts",
            "update",
            "--title",
            "New Title",
            "--content",
            "<p>Body</p>",
            "--status",
            "draft",
            "--slug",
            "new-slug",
            "--date",
            "2026-08-01T09:00:00",
            "--featured-media",
            "123",
            "--excerpt",
            "Short summary",
            "--meta",
            "rank_math_title=SEO Title",
            "--meta",
            "rank_math_description=SEO Description",
            "26786",
        ]
    ]


def test_wordpress_post_update_help_lists_content_options():
    result = CliRunner().invoke(wordpress_post.app, ["update", "--help"])

    assert result.exit_code == 0, result.output
    plain_output = _ANSI_ESCAPE.sub("", result.output)
    for option in (
        "--title",
        "--content",
        "--content-file",
        "--status",
        "--slug",
        "--date",
        "--featured-media",
        "--excerpt",
        "--meta",
    ):
        assert option in plain_output, option


def test_wordpress_page_get_forwards_properties_and_raw(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_page.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_page.app,
        ["get", "--properties", "id,title,content", "--raw", "42"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "pages",
            "get",
            "--properties",
            "id,title,content",
            "--raw",
            "42",
        ]
    ]


def test_wordpress_page_update_forwards_content_file_after_page_id(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_page.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_page.app,
        ["update", "42", "--content-file", "page.html"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "pages",
            "update",
            "--content-file",
            "page.html",
            "42",
        ]
    ]


def test_wordpress_page_update_forwards_publish_and_menu_options(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_page.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_page.app,
        [
            "update",
            "27009",
            "--status",
            "publish",
            "--slug",
            "about-adam",
            "--menu-order",
            "10",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "pages",
            "update",
            "--status",
            "publish",
            "--slug",
            "about-adam",
            "--menu-order",
            "10",
            "27009",
        ]
    ]


def test_wordpress_menu_add_page_forwards_header_options(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_menu.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_menu.app,
        [
            "add-page",
            "27009",
            "--location",
            "main_menu",
            "--title",
            "About Adam",
            "--menu-order",
            "8",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "menus",
            "add-page",
            "--location",
            "main_menu",
            "--title",
            "About Adam",
            "--menu-order",
            "8",
            "27009",
        ]
    ]


def test_wordpress_admin_themes_list_forwards_options_and_profile(monkeypatch):
    calls = []

    def fake_run(cmd, text=True):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_admin, "get_runtime_profile_resolution", lambda: ("ata", "custom"))
    monkeypatch.setattr(wordpress_admin.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_admin.app,
        [
            "themes",
            "list",
            "--table",
            "--limit",
            "5",
            "--filter",
            "status:eq:active",
            "--properties",
            "theme,status",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "admin",
            "--profile",
            "ata",
            "themes",
            "list",
            "--table",
            "--limit",
            "5",
            "--filter",
            "status:eq:active",
            "--properties",
            "theme,status",
        ]
    ]


def test_wordpress_admin_plugins_list_help_documents_json_default():
    result = CliRunner().invoke(wordpress_admin.app, ["plugins", "list", "--help"])

    assert result.exit_code == 0, result.output
    assert "List installed WordPress plugins as JSON by default." in result.output
    assert "Display as table instead of JSON" in result.output
    assert "--format" not in result.output


def test_wordpress_admin_themes_file_push_forwards_without_profile(monkeypatch):
    calls = []

    def fake_run(cmd, text=True):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wordpress_admin, "get_runtime_profile_resolution", lambda: ("ata", "custom"))
    monkeypatch.setattr(wordpress_admin.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        wordpress_admin.app,
        [
            "themes",
            "file-push",
            "ata",
            "front-page.php",
            "front-page.php",
            "--remote-root",
            "/srv/www",
            "--host",
            "example.com",
            "--user",
            "deploy",
            "--port",
            "2222",
            "--identity-file",
            "/tmp/id_ed25519",
            "--backup",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "admin",
            "themes",
            "file-push",
            "ata",
            "front-page.php",
            "front-page.php",
            "--remote-root",
            "/srv/www",
            "--host",
            "example.com",
            "--port",
            "2222",
            "--user",
            "deploy",
            "--identity-file",
            "/tmp/id_ed25519",
            "--backup",
            "--yes",
        ]
    ]
