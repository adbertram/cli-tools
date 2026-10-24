"""Contracts for the terms.json-backed categories and tags commands."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import ata_blog_cli.client as client_module
from ata_blog_cli import corpus
from ata_blog_cli.client import ClientError
from ata_blog_cli.commands import categories, tags

TERMS = {
    "categories": [
        {"id": 5401, "name": "Cloud", "slug": "cloud", "count": 162},
        {"id": 5404, "name": "DevOps", "slug": "devops", "count": 191},
    ],
    "tags": [
        {"id": 5430, "name": "1E Tachyon", "slug": "1e-tachyon", "count": 8},
        {"id": 7, "name": "Sponsored", "slug": "sponsored", "count": 59},
    ],
}


@pytest.fixture
def terms_file(tmp_path, monkeypatch):
    site = tmp_path / "static-site"
    path = site / "src" / "data" / "terms.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(TERMS, indent=2) + "\n")
    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", site)
    return path


def _json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_list_returns_every_term_field(terms_file):
    assert _json(CliRunner().invoke(tags.app, ["list"])) == TERMS["tags"]
    assert _json(CliRunner().invoke(categories.app, ["list"])) == TERMS["categories"]


def test_list_filter_limit_and_properties(terms_file):
    runner = CliRunner()
    assert _json(runner.invoke(tags.app, ["list", "--filter", "name:eq:Sponsored"])) == [
        TERMS["tags"][1]
    ]
    assert _json(runner.invoke(categories.app, ["list", "-l", "1", "-p", "id,name"])) == [
        {"id": 5401, "name": "Cloud"}
    ]


def test_list_table_shows_each_term(terms_file):
    result = CliRunner().invoke(categories.app, ["list", "--table"])
    assert result.exit_code == 0
    assert "Cloud" in result.output and "DevOps" in result.output


def test_get_by_id_and_unknown_id(terms_file):
    assert _json(CliRunner().invoke(tags.app, ["get", "7"])) == TERMS["tags"][1]
    missing = CliRunner().invoke(tags.app, ["get", "5401"])
    assert missing.exit_code != 0
    assert "No tags term has id 5401" in missing.output


def test_create_appends_next_free_id_across_both_taxonomies(terms_file):
    created = _json(CliRunner().invoke(categories.app, ["create", "Business Process Automation"]))

    assert created == {
        "id": 5431,
        "name": "Business Process Automation",
        "slug": "business-process-automation",
        "count": 0,
    }
    document = json.loads(terms_file.read_text())
    assert [term["name"] for term in document["categories"]] == [
        "Business Process Automation",
        "Cloud",
        "DevOps",
    ]
    assert document["tags"] == TERMS["tags"]
    # The file keeps the static site's own formatting.
    assert terms_file.read_text() == json.dumps(document, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", ["sponsored", "SPONSORED", "  Sponsored  "])
def test_create_rejects_case_insensitive_duplicates(terms_file, name):
    before = terms_file.read_text()

    result = CliRunner().invoke(tags.app, ["create", name])

    assert result.exit_code != 0
    assert "already has a term named 'Sponsored' (id 7)" in result.output
    assert terms_file.read_text() == before


def test_create_rejects_a_slug_collision(terms_file):
    with pytest.raises(ClientError, match="already has slug '1e-tachyon'"):
        corpus.create_term("tags", "1E-Tachyon!")


def test_create_rejects_a_name_with_no_slug(terms_file):
    with pytest.raises(ClientError, match="Could not derive a slug"):
        corpus.create_term("tags", "#")


def test_missing_terms_file_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(client_module, "STATIC_SITE_ROOT", tmp_path)
    with pytest.raises(ClientError, match="terms file is missing"):
        corpus.list_terms("tags")
