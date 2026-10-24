"""Contracts for earnings commands sourcing post identity from the static corpus."""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

import ata_blog_cli.client as client_module
from ata_blog_cli.commands import earnings

ROW = {
    "pageviews": 100,
    "earnings": 50.0,
    "rpm": 20.0,
    "impressions": 400,
    "cpm": 5.0,
    "viewability": 0.7,
    "impressions_per_pageview": 4.0,
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
}


def _post(slug, title, tag_ids, pub_date="2020-01-01T08:00:00"):
    return (
        f'---\nwpId: 1\nslug: "{slug}"\nauthorId: 2\ncategoryIds: [5401]\n'
        f'tagIds: {json.dumps(tag_ids)}\ntitle: "{title}"\ndescription: "d"\n'
        f"pubDate: {pub_date}\nmodDate: {pub_date}\n---\nbody\n"
    )


@pytest.fixture
def site(tmp_path, monkeypatch):
    root = tmp_path / "static-site"
    posts = root / "src" / "data" / "posts"
    posts.mkdir(parents=True)
    (posts / "1-powershell-basics.md").write_text(_post("powershell-basics", "PowerShell Basics", [3]))
    (posts / "2-vendor-review.md").write_text(_post("vendor-review", "Vendor Review", [7, 3]))
    (root / "src" / "data" / "terms.json").write_text(
        json.dumps(
            {
                "categories": [],
                "tags": [
                    {"id": 3, "name": "PowerShell", "slug": "powershell", "count": 2},
                    {"id": 7, "name": "Sponsored", "slug": "sponsored", "count": 1},
                ],
            }
        )
    )
    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", root)

    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        assert cmd[0] == "raptive", f"unexpected subprocess: {cmd}"
        rows = [
            {**ROW, "page_url": "/powershell-basics/"},
            {**ROW, "page_url": "/vendor-review"},
            {**ROW, "page_url": "/"},
        ]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"results": rows}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return commands


def _json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_list_enriches_publish_date_from_the_corpus(site):
    rows = _json(CliRunner().invoke(earnings.app, ["list"]))

    by_url = {row["page_url"]: row for row in rows}
    assert by_url["/powershell-basics/"]["publish_date"] == "2020-01-01"
    assert by_url["/powershell-basics/"]["earnings_per_day"] > 0
    # A page that is not a post has no corpus record.
    assert by_url["/"]["publish_date"] is None
    assert by_url["/"]["earnings_per_day"] is None
    assert all(command[0] == "raptive" for command in site)


def test_list_exclude_sponsored_uses_corpus_tags(site):
    rows = _json(CliRunner().invoke(earnings.app, ["list", "--exclude-sponsored"]))
    assert [row["page_url"] for row in rows] == ["/powershell-basics/", "/"]


def test_list_post_title_matches_corpus_titles(site):
    rows = _json(CliRunner().invoke(earnings.app, ["list", "--post-title", "powershell"]))
    assert [row["page_url"] for row in rows] == ["/powershell-basics/"]


def test_list_post_title_with_no_match_fails(site):
    result = CliRunner().invoke(earnings.app, ["list", "--post-title", "kubernetes"])
    assert result.exit_code == 1


def test_list_rejects_the_removed_post_id_option(site):
    result = CliRunner().invoke(earnings.app, ["list", "--post-id", "26786"])
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert site == []


def test_get_by_slug(site):
    row = _json(CliRunner().invoke(earnings.app, ["get", "vendor-review"]))
    assert row["page_url"] == "/vendor-review"
    assert row["publish_date"] == "2020-01-01"


def test_get_exclude_sponsored_skips_a_sponsored_post(site):
    assert _json(CliRunner().invoke(earnings.app, ["get", "vendor-review", "--exclude-sponsored"])) == {}
    assert site == []
