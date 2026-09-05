"""Tests for sponsor registry resolution in shoutouts commands."""

from __future__ import annotations

import json

import pytest

from ata_blog_cli.commands import shoutouts
from ata_blog_cli.config import Config


def test_sponsors_file_resolves_from_config(monkeypatch, tmp_path):
    """The registry path resolves through Config, with the env var as override."""
    registry = tmp_path / "sponsors.json"
    registry.write_text(
        json.dumps({"sponsors": [{"name": "Specops", "domains": ["specopssoft.com"]}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ATABLOGGER_SPONSORS_FILE", str(registry))

    assert shoutouts._sponsors_file_path() == registry
    assert shoutouts._resolve_sponsor_domains("Specops") == ["specopssoft.com"]


def test_missing_sponsors_config_names_key_and_env_file(monkeypatch):
    """A missing config value must fail loudly with the key and config path."""
    config = Config()
    monkeypatch.setattr(config, "_get", lambda name: None)

    with pytest.raises(ValueError) as exc_info:
        _ = config.sponsors_file

    message = str(exc_info.value)
    assert "ATABLOGGER_SPONSORS_FILE" in message
    assert "~/.local/share/cli-tools/ata-blog/.env" in message


def test_missing_registry_file_fails(monkeypatch, tmp_path):
    """A configured but absent registry path must fail loudly."""
    missing = tmp_path / "absent.json"
    monkeypatch.setenv("ATABLOGGER_SPONSORS_FILE", str(missing))

    with pytest.raises(ValueError, match="Sponsor registry not found"):
        shoutouts._load_sponsors()
