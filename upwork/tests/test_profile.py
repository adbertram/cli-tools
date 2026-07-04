"""Tests for Upwork profile parsing and command helpers."""

import json

from typer.testing import CliRunner

import pytest
from cli_tools_shared.exceptions import ClientError

import upwork_cli.commands.profile as profile_commands
from upwork_cli.client import UpworkClient
from upwork_cli.commands.profile import app
from upwork_cli.parsers import (
    normalize_field_name,
    normalize_profile,
    normalize_profile_updates,
)


def _unexpected_live_client():
    raise AssertionError("metadata and dry-run commands must not create a live Upwork client")


def test_normalize_field_aliases():
    assert normalize_field_name("bio") == "overview"
    assert normalize_field_name("hourlyRate") == "hourly_rate"
    assert normalize_field_name("professional-title") == "title"


def test_normalize_profile_extracts_common_fields():
    raw = {
        "url": "https://www.upwork.com/freelancers/~abc",
        "text": (
            "Overview I build automation systems for operations teams. "
            "Skills Python Automation Languages English Availability 30 hours/week"
        ),
        "headings": ["Adam Bertram", "Automation Consultant"],
        "links": [
            {"text": "Python", "href": "https://www.upwork.com/search/profiles/?q=python"},
            {"text": "View Profile", "href": "https://www.upwork.com/freelancers/~abc"},
        ],
        "inputs": [],
        "meta": [{"name": "description", "content": "Fallback overview"}],
        "json_ld": [
            json.dumps(
                {
                    "name": "Adam Bertram",
                    "jobTitle": "Automation Consultant",
                    "address": {
                        "addressLocality": "Indianapolis",
                        "addressCountry": "United States",
                    },
                }
            )
        ],
    }

    profile = normalize_profile(raw)

    assert profile["name"] == "Adam Bertram"
    assert profile["title"] == "Automation Consultant"
    assert profile["overview"] == "I build automation systems for operations teams."
    assert profile["skills"] == ["Python"]
    assert profile["availability"] == "30 hours/week"
    assert profile["location"] == "Indianapolis"
    assert profile["profile_url"] == "https://www.upwork.com/freelancers/~abc"


def test_normalize_profile_updates_normalizes_aliases_and_values():
    updates = normalize_profile_updates(
        {
            "tags": "Python, Automation",
            "rate": "$120/hr",
            "headline": "Automation Consultant",
        }
    )

    assert updates == {
        "skills": ["Python", "Automation"],
        "hourly_rate": 120.0,
        "title": "Automation Consultant",
    }


def test_profile_update_dry_run_does_not_require_client(monkeypatch):
    monkeypatch.setattr(profile_commands, "get_client", _unexpected_live_client)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["update", "--dry-run", "--set", "title=Automation Consultant"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["requested"] == {"title": "Automation Consultant"}


def test_profile_list_returns_metadata_without_client(monkeypatch):
    monkeypatch.setattr(profile_commands, "get_client", _unexpected_live_client)
    runner = CliRunner()

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert any(row["name"] == "title" for row in payload)
    assert any(row["name"] == "overview" for row in payload)


def test_profile_get_field_returns_metadata_without_client(monkeypatch):
    monkeypatch.setattr(profile_commands, "get_client", _unexpected_live_client)
    runner = CliRunner()

    result = runner.invoke(app, ["get", "bio"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["name"] == "overview"
    assert payload["editable"] is True


def test_live_profile_get_is_disabled_due_to_cloudflare():
    client = UpworkClient()

    with pytest.raises(ClientError, match="disabled.*Cloudflare"):
        client.get_profile()


def test_profile_get_command_reports_disabled_due_to_cloudflare():
    runner = CliRunner()

    result = runner.invoke(app, ["get"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "disabled" in result.stderr
    assert "Cloudflare" in result.stderr


def test_live_profile_update_is_disabled_due_to_cloudflare():
    client = UpworkClient()

    with pytest.raises(ClientError, match="disabled.*Cloudflare"):
        client.update_profile({"title": "Automation Consultant"})


def test_profile_update_command_reports_disabled_due_to_cloudflare():
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["update", "--yes", "--set", "title=Automation Consultant"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "disabled" in result.stderr
    assert "Cloudflare" in result.stderr
