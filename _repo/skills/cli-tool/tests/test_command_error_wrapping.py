"""Guard: every Typer command must use the shared ``@command`` decorator.

A Typer command registered with ``@<app>.command(...)`` leaks a raw Python
traceback — instead of a clean ``Error: ...`` message and a correct exit code —
when it raises and nothing catches the exception. This is a real, recurring
bug: the console entry point (``<tool>.main:app``) calls ``app()`` directly, and
``run_app()`` only catches the tool's declared client-error types. Neither path
provides a catch-all, so an unhandled ``ValueError`` (or any other exception)
prints a traceback and exits 1 with no useful message.

The single source of catch-all handling is the shared
``cli_tools_shared.output.command`` decorator: it converts any exception into
``handle_error()``'s ``Error: ...`` message plus the documented exit code
(2 for ``CredentialError``, 1 otherwise) and re-raises ``typer.Exit`` untouched.

**Every Typer command MUST carry the shared ``@command`` decorator.** It is the
one body-wide guarantee, applies uniformly across the fleet, and keeps command
bodies free of per-command error boilerplate. A hand-rolled top-level
``try``/``except Exception`` that routes through ``handle_error`` produces the
same runtime behavior, but it is NOT accepted here: it duplicates the shared
logic in every command, drifts over time, and hides the intent. Commands may
still keep a ``try`` for *specific* exceptions they handle differently
(``FileNotFoundError``, ``json.JSONDecodeError``, etc.) — but the catch-all
guarantee must come from ``@command``, layered as the INNER decorator directly
below ``@<app>.command(...)``.

``register_commands`` does NOT make a command safe: that path only injects
credential/profile checks, not exception handling, so commands mounted through
it still need their own ``@command``. The check is therefore file-local and
applies to every Typer command in the package.

The reusable scan lives in :func:`find_unwrapped_commands`; the per-tool test
:func:`test_typer_commands_handle_errors` runs it against the CLI under test,
and the unit tests at the bottom prove the scan flags a command that lacks the
decorator (including one that only uses a catch-all ``try``) and passes one that
carries it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _iter_source_files(pkg_dir: Path):
    return (path for path in pkg_dir.rglob("*.py") if "__pycache__" not in path.parts)


def _decorator_target(decorator: ast.expr) -> ast.expr:
    """Return the callable referenced by a decorator, unwrapping a call.

    ``@app.command("x")`` -> the ``app.command`` attribute; ``@command`` -> the
    ``command`` name.
    """
    return decorator.func if isinstance(decorator, ast.Call) else decorator


def _is_typer_command_decorator(decorator: ast.expr) -> bool:
    """True for a Typer command registration: ``@<app>.command(...)``.

    Matches any attribute access whose attribute is ``command`` on a bare name
    (``app``, ``field_app``, a local ``app`` inside a factory, etc.). Typer's
    ``add_typer``/``callback`` decorators and the shared bare ``@command`` do not
    match.
    """
    target = _decorator_target(decorator)
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "command"
        and isinstance(target.value, ast.Name)
    )


def _has_shared_command_decorator(func: ast.AST) -> bool:
    """True when the function carries the shared bare ``@command`` decorator."""
    for decorator in func.decorator_list:
        target = _decorator_target(decorator)
        if isinstance(target, ast.Name) and target.id == "command":
            return True
    return False


def _is_typer_command(func: ast.AST) -> bool:
    return any(_is_typer_command_decorator(d) for d in func.decorator_list)


def _command_is_guarded(func: ast.AST) -> bool:
    """True only when the command carries the shared ``@command`` decorator."""
    return _has_shared_command_decorator(func)


def find_unwrapped_commands(pkg_dir: Path) -> list[str]:
    """Return ``relpath::function (Lnn)`` for each command lacking ``@command``.

    A Typer command (a function decorated with ``@<app>.command(...)``) is a
    violation unless it also carries the shared ``@command`` decorator. A
    hand-rolled catch-all ``try`` does NOT satisfy the check. Nested commands
    (defined inside a factory function) are scanned too.
    """
    violations: list[str] = []
    for path in _iter_source_files(pkg_dir):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _is_typer_command(node):
                continue
            if _command_is_guarded(node):
                continue
            try:
                rel = path.relative_to(pkg_dir.parent)
            except ValueError:
                rel = path
            violations.append(f"{rel}::{node.name} (L{node.lineno})")
    return violations


def test_typer_commands_handle_errors(cli_name, cli_dir, command_filter):
    """Every Typer command in the CLI package must use the shared @command."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")

    pkg_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    if not pkg_dir.is_dir():
        pytest.skip(f"No package directory at {pkg_dir}")

    violations = find_unwrapped_commands(pkg_dir)
    if violations:
        listed = "\n".join(f"  - {violation}" for violation in violations)
        pytest.fail(
            f"{cli_name}: {len(violations)} Typer command(s) registered with "
            "@<app>.command(...) do not carry the shared @command decorator and "
            "will leak a raw traceback (instead of a clean 'Error: ...' message "
            f"+ exit code) when they raise:\n{listed}\n\n"
            "Fix: add the shared @command decorator immediately below the "
            "@<app>.command(...) line so it is the INNER decorator:\n"
            "    from cli_tools_shared.output import command\n\n"
            "    @app.command(\"whoami\")\n"
            "    @command\n"
            "    def whoami_command(...):\n"
            "        ...\n\n"
            "A hand-rolled 'try/except Exception' is NOT accepted — the "
            "catch-all guarantee must come from @command. Commands may still "
            "keep a 'try' for SPECIFIC exceptions (FileNotFoundError, "
            "json.JSONDecodeError, ...) alongside the @command decorator."
        )


# ---------------------------------------------------------------------------
# Unit tests for the scan itself (run without --cli-name).
# ---------------------------------------------------------------------------

def _make_pkg(tmp_path: Path, filename: str, source: str) -> Path:
    pkg_dir = tmp_path / "demo_cli"
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / filename).write_text(source)
    return pkg_dir


def test_scan_flags_command_without_any_wrapper(tmp_path):
    pkg_dir = _make_pkg(
        tmp_path,
        "main.py",
        "import typer\n"
        "app = typer.Typer()\n\n"
        "@app.command('whoami')\n"
        "def whoami():\n"
        "    client = get_client()\n"
        "    print(client.whoami())\n",
    )
    violations = find_unwrapped_commands(pkg_dir)
    assert [v for v in violations if "whoami" in v], violations


def test_scan_passes_command_with_shared_command_decorator(tmp_path):
    pkg_dir = _make_pkg(
        tmp_path,
        "main.py",
        "import typer\n"
        "from cli_tools_shared.output import command\n"
        "app = typer.Typer()\n\n"
        "@app.command('whoami')\n"
        "@command\n"
        "def whoami():\n"
        "    client = get_client()\n"
        "    print(client.whoami())\n",
    )
    assert find_unwrapped_commands(pkg_dir) == []


def test_scan_flags_command_with_only_catchall_try(tmp_path):
    # A catch-all try produces the same runtime behavior but is NOT accepted:
    # the guarantee must come from the shared @command decorator.
    pkg_dir = _make_pkg(
        tmp_path,
        "cmd.py",
        "import typer\n"
        "from cli_tools_shared.output import handle_error\n"
        "app = typer.Typer()\n\n"
        "@app.command('list')\n"
        "def list_items():\n"
        "    \"\"\"List items.\"\"\"\n"
        "    try:\n"
        "        client = get_client()\n"
        "        print(client.list())\n"
        "    except Exception as exc:\n"
        "        raise typer.Exit(handle_error(exc))\n",
    )
    violations = find_unwrapped_commands(pkg_dir)
    assert [v for v in violations if "list_items" in v], violations


def test_scan_passes_command_with_decorator_and_specific_try(tmp_path):
    # @command supplies the catch-all; a specific-exception try alongside it is
    # fine and must not be flagged.
    pkg_dir = _make_pkg(
        tmp_path,
        "cmd.py",
        "import json\n"
        "import typer\n"
        "from cli_tools_shared.output import command\n"
        "app = typer.Typer()\n\n"
        "@app.command('create')\n"
        "@command\n"
        "def create_item(path: str):\n"
        "    \"\"\"Create item.\"\"\"\n"
        "    try:\n"
        "        data = json.loads(path)\n"
        "    except json.JSONDecodeError as exc:\n"
        "        raise typer.Exit(1)\n"
        "    print(data)\n",
    )
    assert find_unwrapped_commands(pkg_dir) == []


def test_scan_flags_partial_handler_command(tmp_path):
    # A try that catches only a specific exception type is not a catch-all, and
    # without @command the command is unguarded.
    pkg_dir = _make_pkg(
        tmp_path,
        "cmd.py",
        "import typer\n"
        "app = typer.Typer()\n\n"
        "@app.command('get')\n"
        "def get_item():\n"
        "    \"\"\"Get item.\"\"\"\n"
        "    try:\n"
        "        do_work()\n"
        "    except ClientError as exc:\n"
        "        raise typer.Exit(1)\n",
    )
    violations = find_unwrapped_commands(pkg_dir)
    assert [v for v in violations if "get_item" in v], violations


def test_scan_flags_group_app_command(tmp_path):
    pkg_dir = _make_pkg(
        tmp_path,
        "main.py",
        "import typer\n"
        "field_app = typer.Typer()\n\n"
        "@field_app.command('create')\n"
        "def create_field():\n"
        "    do_work()\n",
    )
    violations = find_unwrapped_commands(pkg_dir)
    assert [v for v in violations if "create_field" in v], violations


def test_scan_flags_nested_factory_command(tmp_path):
    # Commands defined inside a factory function are still scanned.
    pkg_dir = _make_pkg(
        tmp_path,
        "permissions.py",
        "import typer\n\n"
        "def build_app(name):\n"
        "    app = typer.Typer()\n\n"
        "    @app.command('grant')\n"
        "    def cmd_grant(entity_id: str):\n"
        "        grant_permission(entity_id)\n\n"
        "    return app\n",
    )
    violations = find_unwrapped_commands(pkg_dir)
    assert [v for v in violations if "cmd_grant" in v], violations


def test_scan_ignores_callbacks_and_undecorated_helpers(tmp_path):
    pkg_dir = _make_pkg(
        tmp_path,
        "main.py",
        "import typer\n"
        "app = typer.Typer()\n\n"
        "@app.callback()\n"
        "def main_callback():\n"
        "    pass\n\n"
        "def helper():\n"
        "    raise RuntimeError('boom')\n",
    )
    assert find_unwrapped_commands(pkg_dir) == []
