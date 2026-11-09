import os
import re
import subprocess
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


def test_create_app_widens_piped_help_at_build_time(monkeypatch):
    """Captured Rich help must keep long option names searchable."""
    import typer.rich_utils as typer_rich_utils

    monkeypatch.setattr(sys, "argv", ["demo", "items", "--help"])
    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.setattr(typer_rich_utils, "MAX_WIDTH", None)
    # Restored after the test so the compacting console does not leak.
    monkeypatch.setattr(typer_rich_utils, "_get_rich_console", typer_rich_utils._get_rich_console)

    create_app(name="demo", help="x", version="1.0.0")

    assert os.environ["COLUMNS"] == "200"
    assert typer_rich_utils.MAX_WIDTH == 200
    assert typer_rich_utils._get_rich_console.compacts_help


_PIPED_HELP_SCRIPT = """
import typer
from cli_tools_shared.app_factory import create_app, run_app

app = create_app(name="demo", help="Demo tool.", version="1.0.0")
items = typer.Typer(help="Manage items.")
app.add_typer(items, name="items")


@items.command("list")
def list_items(
    include_every_archived_record_variant: bool = typer.Option(
        False, "--include-every-archived-record-variant", help="Include archived records."
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Max rows"),
):
    \"\"\"List items.\"\"\"


run_app(app)
"""


@pytest.mark.parametrize("force_color", [None, "1"])
def test_piped_help_drops_width_padding_and_keeps_content(force_color):
    """Piped help keeps the 200-column layout and every border the help
    parsers anchor on, but no line carries Rich's width padding."""
    env = {k: v for k, v in os.environ.items() if k not in {"FORCE_COLOR", "COLUMNS", "_TYPER_FORCE_DISABLE_TERMINAL"}}
    if force_color:
        env["FORCE_COLOR"] = force_color

    result = subprocess.run(
        [sys.executable, "-c", _PIPED_HELP_SCRIPT, "items", "list", "--help"],
        capture_output=True, text=True, env=env, check=False,
    )

    assert result.returncode == 0, result.stderr
    if force_color:
        assert "\x1b[" in result.stdout
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    lines = text.splitlines()
    assert all(line == line.rstrip() for line in lines)
    assert "╭─ Options ─╮" in lines
    assert "╰─╯" in lines
    assert "│ --include-every-archived-record-variant" in text
    assert "Include archived records. │" in text
    assert not any(re.search(r"\s{2,}│$", line) for line in lines)
    assert all(len(line) <= 200 for line in lines)


def test_create_app_keeps_interactive_help_width(monkeypatch):
    """Interactive terminal help should keep the user's terminal width."""
    import typer.rich_utils as typer_rich_utils

    class InteractiveStdout:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "argv", ["demo", "items", "--help"])
    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.setattr(sys, "stdout", InteractiveStdout())
    monkeypatch.setattr(typer_rich_utils, "MAX_WIDTH", None)

    create_app(name="demo", help="x", version="1.0.0")

    assert "COLUMNS" not in os.environ
    assert typer_rich_utils.MAX_WIDTH is None


def test_create_app_does_not_rewrite_help_option_values(monkeypatch):
    """Only the root help alias is rewritten."""
    monkeypatch.setattr(sys, "argv", ["demo", "create", "--name", "help"])

    create_app(name="demo", help="x", version="1.0.0")

    assert sys.argv == ["demo", "create", "--name", "help"]
