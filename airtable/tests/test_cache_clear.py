"""Tests for the `airtable cache clear` command."""
import json
from pathlib import Path

from typer.testing import CliRunner

import cli_tools_shared.cache_commands as cache_commands


runner = CliRunner()


class _FakeConfig:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir


def _make_cache_app(config):
    return cache_commands.create_cache_app(lambda *a, **kw: config)


def test_cache_clear_empty_cache(tmp_path):
    """`cache clear` exits 0 and reports zero work when no cache exists."""
    app = _make_cache_app(_FakeConfig(tmp_path))
    # Single-command typer subapps collapse the subcommand name, so invoke with
    # no positional args to run the `clear` command.
    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {"files_removed": 0, "bytes_freed": 0}


def test_cache_clear_removes_files(tmp_path):
    """`cache clear` deletes every file in `{storage_dir}/cache/` and reports counts."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "a.json").write_bytes(b"hello")
    (cache_dir / "b.json").write_bytes(b"world!")

    app = _make_cache_app(_FakeConfig(tmp_path))
    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload == {"files_removed": 2, "bytes_freed": len(b"hello") + len(b"world!")}
    assert list(cache_dir.iterdir()) == []


def test_config_exposes_storage_dir(tmp_path, monkeypatch):
    """`Config.storage_dir` must be a real attribute (regression for the AttributeError bug)."""
    from airtable_cli.config import Config

    # Avoid touching the user's real profile directory.
    monkeypatch.setattr(Config, "get_profile_data_dir", lambda self: tmp_path)
    cfg = Config.__new__(Config)  # bypass __init__ (no real profile setup needed)
    assert cfg.storage_dir == tmp_path
