import os
import sys

import pytest
import typer

from cli_tools_shared.app_factory import create_app, run_app
from cli_tools_shared.exceptions import ConfigError


def test_run_app_handles_config_error_by_default(capsys):
    class BrokenApp:
        def __call__(self):
            raise ConfigError("Multiple active profiles found")

    with pytest.raises(SystemExit) as exc:
        run_app(BrokenApp())

    assert exc.value.code == 2
    assert "Error: Multiple active profiles found" in capsys.readouterr().err


def _app_with_get_command(captured: dict) -> typer.Typer:
    """Build a throwaway app whose ``get`` command records cache state."""
    app = create_app(name="demo", help="x", version="1.0.0")

    @app.command("get")
    def get_cmd(record_id: str):
        captured["record_id"] = record_id
        captured["cache_enabled"] = os.environ.get("CACHE_ENABLED")

    return app


def test_no_cache_flag_works_after_subcommand(monkeypatch):
    """``--no-cache`` appended AFTER the subcommand must disable the cache.

    Agents type ``coursecraft demos get <id> --no-cache``. The flag is an
    app-level callback option, so Click alone only honours it before the
    subcommand; ``run_app`` hoists it so the trailing position works too.
    """
    captured: dict = {}
    app = _app_with_get_command(captured)

    monkeypatch.delenv("CACHE_ENABLED", raising=False)
    monkeypatch.setattr(sys, "argv", ["demo", "get", "rec123", "--no-cache"])

    with pytest.raises(SystemExit) as exc:
        run_app(app)

    assert exc.value.code == 0
    assert captured["record_id"] == "rec123"
    assert captured["cache_enabled"] == "false"


def test_no_cache_flag_still_works_before_subcommand(monkeypatch):
    """The documented before-subcommand position must keep working (regression)."""
    captured: dict = {}
    app = _app_with_get_command(captured)

    monkeypatch.delenv("CACHE_ENABLED", raising=False)
    monkeypatch.setattr(sys, "argv", ["demo", "--no-cache", "get", "rec123"])

    with pytest.raises(SystemExit) as exc:
        run_app(app)

    assert exc.value.code == 0
    assert captured["record_id"] == "rec123"
    assert captured["cache_enabled"] == "false"


def test_no_cache_as_option_value_is_not_hoisted(monkeypatch):
    """A ``--no-cache`` that is the VALUE of a value-taking option is left intact.

    ``demo create --name --no-cache`` means a record literally named
    ``--no-cache``; the hoist must not steal it or disable the cache.
    """
    captured: dict = {}
    app = create_app(name="demo", help="x", version="1.0.0")

    @app.command("create")
    def create_cmd(name: str = typer.Option(..., "--name")):
        captured["name"] = name
        captured["cache_enabled"] = os.environ.get("CACHE_ENABLED")

    monkeypatch.delenv("CACHE_ENABLED", raising=False)
    monkeypatch.setattr(sys, "argv", ["demo", "create", "--name", "--no-cache"])

    with pytest.raises(SystemExit) as exc:
        run_app(app)

    assert exc.value.code == 0
    assert captured["name"] == "--no-cache"
    assert captured["cache_enabled"] is None  # cache NOT disabled


def test_create_app_normalizes_trailing_no_cache_at_build_time(monkeypatch):
    """Most CLIs use a ``main:app`` entry point that calls ``app()`` directly,
    never reaching run_app. create_app runs at import (before ``app()`` parses
    argv), so it must normalise a trailing ``--no-cache`` there.
    """
    monkeypatch.setattr(sys, "argv", ["demo", "get", "rec123", "--no-cache"])

    create_app(name="demo", help="x", version="1.0.0")

    assert sys.argv == ["demo", "--no-cache", "get", "rec123"]


def test_create_app_leaves_no_cache_option_value_intact_at_build_time(monkeypatch):
    """The build-time normalisation must also never steal an option's value."""
    monkeypatch.setattr(sys, "argv", ["demo", "create", "--name", "--no-cache"])

    create_app(name="demo", help="x", version="1.0.0")

    assert sys.argv == ["demo", "create", "--name", "--no-cache"]


def test_create_app_normalizes_root_help_alias_at_build_time(monkeypatch):
    """``demo help`` should behave like ``demo --help`` for console scripts."""
    monkeypatch.setattr(sys, "argv", ["demo", "help"])

    create_app(name="demo", help="x", version="1.0.0")

    assert sys.argv == ["demo", "--help"]


def test_create_app_does_not_rewrite_help_option_values(monkeypatch):
    """Only the root help alias is rewritten."""
    monkeypatch.setattr(sys, "argv", ["demo", "create", "--name", "help"])

    create_app(name="demo", help="x", version="1.0.0")

    assert sys.argv == ["demo", "create", "--name", "help"]
