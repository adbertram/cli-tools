import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ata_blog_cli.commands.shoutouts import app


@pytest.fixture
def runner():
    return CliRunner()


def _result(payload, returncode=0, stderr=""):
    result = MagicMock()
    result.stdout = json.dumps(payload)
    result.stderr = stderr
    result.returncode = returncode
    return result


def _write_sponsors(tmp_path: Path, sponsors):
    sponsor_file = tmp_path / "sponsors.json"
    sponsor_file.write_text(json.dumps({"sponsors": sponsors}), encoding="utf-8")
    return sponsor_file


def test_list_requires_post_without_sponsor(runner):
    result = runner.invoke(app, ["list"])

    assert result.exit_code != 0


def test_list_sponsor_filters_sponsored_posts_by_registered_domain(runner, tmp_path, monkeypatch):
    sponsor_file = _write_sponsors(
        tmp_path,
        [{"name": "Specops", "domains": ["specopssoft.com", "specopssoft.co.uk"]}],
    )
    monkeypatch.setenv("ATABLOGGER_SPONSORS_FILE", str(sponsor_file))

    posts = [
        {
            "id": 101,
            "slug": "specops-post",
            "title": "Specops Post",
            "date": "2026-04-01T09:00:00",
            "link": "https://adamtheautomator.com/specops-post/",
        },
        {
            "id": 102,
            "slug": "other-post",
            "title": "Other Post",
            "date": "2026-04-02T09:00:00",
            "link": "https://adamtheautomator.com/other-post/",
        },
    ]
    specops_content = {
        "content": """
<p>Intro</p>
<blockquote><p><a href="https://www.specopssoft.com/key-recovery" rel="sponsored">Recover keys</a></p></blockquote>
<p>Body</p>
<blockquote><p><a href="https://specopssoft.co.uk/demo" rel="sponsored">UK demo</a></p></blockquote>
"""
    }
    other_content = {
        "content": """
<p>Intro</p>
<blockquote><p><a href="https://example.com" rel="sponsored">Other</a></p></blockquote>
"""
    }

    calls = []

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        if cmd[:3] == ["wordpress", "posts", "list"]:
            return _result(posts)
        if cmd == ["wordpress", "posts", "get", "101", "--raw"]:
            return _result(specops_content)
        if cmd == ["wordpress", "posts", "get", "102", "--raw"]:
            return _result(other_content)
        raise AssertionError(f"Unexpected command: {cmd}")

    with patch("ata_blog_cli.commands.shoutouts.subprocess.run", side_effect=fake_run):
        result = runner.invoke(app, ["list", "--sponsor", "Specops"])

    assert result.exit_code == 0, result.output
    assert calls[0] == [
        "wordpress",
        "posts",
        "list",
        "--limit",
        "1000",
        "--filter",
        "tags:eq:7",
        "--properties",
        "id,slug,title,date,link",
    ]
    rows = json.loads(result.stdout)
    assert rows == [
        {
            "post_id": 101,
            "slug": "specops-post",
            "title": "Specops Post",
            "date": "2026-04-01T09:00:00",
            "link": "https://adamtheautomator.com/specops-post/",
            "index": 1,
            "position": 1,
            "preview": "Recover keys",
            "full_html": '<blockquote><p><a href="https://www.specopssoft.com/key-recovery" rel="sponsored">Recover keys</a></p></blockquote>',
        },
        {
            "post_id": 101,
            "slug": "specops-post",
            "title": "Specops Post",
            "date": "2026-04-01T09:00:00",
            "link": "https://adamtheautomator.com/specops-post/",
            "index": 2,
            "position": 3,
            "preview": "UK demo",
            "full_html": '<blockquote><p><a href="https://specopssoft.co.uk/demo" rel="sponsored">UK demo</a></p></blockquote>',
        },
    ]


def test_list_sponsor_applies_filter_limit_properties_to_final_rows(runner, tmp_path, monkeypatch):
    sponsor_file = _write_sponsors(tmp_path, [{"name": "Specops", "domains": ["specopssoft.com"]}])
    monkeypatch.setenv("ATABLOGGER_SPONSORS_FILE", str(sponsor_file))

    posts = [
        {"id": 101, "slug": "first", "title": "First", "date": "2026-04-01", "link": "https://example.test/first/"},
        {"id": 102, "slug": "second", "title": "Second", "date": "2026-04-02", "link": "https://example.test/second/"},
    ]
    content = {
        "content": '<p>Intro</p><blockquote><p><a href="https://specopssoft.com" rel="sponsored">Sponsor</a></p></blockquote>'
    }

    def fake_run(cmd, capture_output=True, text=True):
        if cmd[:3] == ["wordpress", "posts", "list"]:
            return _result(posts)
        if cmd[:3] == ["wordpress", "posts", "get"]:
            return _result(content)
        raise AssertionError(f"Unexpected command: {cmd}")

    with patch("ata_blog_cli.commands.shoutouts.subprocess.run", side_effect=fake_run):
        result = runner.invoke(
            app,
            [
                "list",
                "--sponsor",
                "Specops",
                "--filter",
                "slug:eq:second",
                "--limit",
                "1",
                "--properties",
                "post_id,slug,position",
            ],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"post_id": 102, "slug": "second", "position": 1}]


def test_list_sponsor_fails_for_duplicate_names(runner, tmp_path, monkeypatch):
    sponsor_file = _write_sponsors(
        tmp_path,
        [
            {"name": "Specops", "domains": ["specopssoft.com"]},
            {"name": "Specops", "domains": ["specops.example"]},
        ],
    )
    monkeypatch.setenv("ATABLOGGER_SPONSORS_FILE", str(sponsor_file))

    result = runner.invoke(app, ["list", "--sponsor", "Specops"])

    assert result.exit_code != 0
    assert "duplicate sponsor name" in result.stderr.lower()


def test_list_sponsor_fails_for_unknown_name(runner, tmp_path, monkeypatch):
    sponsor_file = _write_sponsors(tmp_path, [{"name": "Specops", "domains": ["specopssoft.com"]}])
    monkeypatch.setenv("ATABLOGGER_SPONSORS_FILE", str(sponsor_file))

    result = runner.invoke(app, ["list", "--sponsor", "Missing"])

    assert result.exit_code != 0
    assert "unknown sponsor" in result.stderr.lower()
