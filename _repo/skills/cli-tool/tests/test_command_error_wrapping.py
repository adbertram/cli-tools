"""Guard: every Typer command must handle its own errors.

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

A command is considered SAFE when it has either of:

* the shared ``@command`` decorator (the preferred, body-wide guarantee), or
* a top-level ``try`` whose handlers include a catch-all
  (``except Exception`` / ``except BaseException`` / bare ``except:``) wrapping
  the body — the older convention most command modules still use.

Anything else can leak a traceback and is flagged. Note that a ``try`` which
catches only specific exceptions (e.g. ``except ClientError``) is NOT a
catch-all and does not make the command safe — a different exception type still
escapes.

``register_commands`` does NOT make a command safe: that path only injects
credential/profile checks, not exception handling, so commands mounted through
it still need their own ``@command`` (or catch-all ``try``). The check is
therefore file-local and applies to every Typer command in the package.

The reusable scan lives in :func:`find_unwrapped_commands`; the per-tool test
:func:`test_typer_commands_handle_errors` runs it against the CLI under test,
and the unit tests at the bottom prove the scan catches an unwrapped command and
passes a wrapped one.
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


def _is_catchall_handler(handler: ast.ExceptHandler) -> bool:
    """True for ``except:``, ``except Exception`` or ``except BaseException``.

    Also matches those names inside a tuple (``except (Exception, OSError)``).
    A handler that only names specific exception types is not a catch-all.
    """
    if handler.type is None:  # bare ``except:``
        return True
    names: list[str] = []
    handler_type = handler.type
    if isinstance(handler_type, ast.Tuple):
        names = [elt.id for elt in handler_type.elts if isinstance(elt, ast.Name)]
    elif isinstance(handler_type, ast.Name):
        names = [handler_type.id]
    return any(name in ("Exception", "BaseException") for name in names)


def _body_without_docstring(func: ast.AST) -> list[ast.stmt]:
    body = list(func.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _has_catchall_try(func: ast.AST) -> bool:
    """True when a top-level ``try`` in the body has a catch-all handler."""
    for stmt in _body_without_docstring(func):
        if isinstance(stmt, ast.Try) and any(
            _is_catchall_handler(handler) for handler in stmt.handlers
        ):
            return True
    return False


def _is_typer_command(func: ast.AST) -> bool:
    return any(_is_typer_command_decorator(d) for d in func.decorator_list)


def _command_is_guarded(func: ast.AST) -> bool:
    return _has_shared_command_decorator(func) or _has_catchall_try(func)


def find_unwrapped_commands(pkg_dir: Path) -> list[str]:
    """Return ``relpath::function (Lnn)`` for each unguarded Typer command.

    A Typer command (a function decorated with ``@<app>.command(...)``) is
    unguarded when it has neither the shared ``@command`` decorator nor a
    top-level catch-all ``try``. Nested commands (defined inside a factory
    function) are scanned too.
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
    """Every Typer command in the CLI package must guard its own errors."""
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
            "@<app>.command(...) lack error handling and will leak a raw "
            "traceback (instead of a clean 'Error: ...' message + exit code) "
            f"when they raise:\n{listed}\n\n"
            "Fix: add the shared @command decorator immediately below the "
            "@<app>.command(...) line so it is the INNER decorator:\n"
            "    from cli_tools_shared.output import command\n\n"
            "    @app.command(\"whoami\")\n"
            "    @command\n"
            "    def whoami_command(...):\n"
            "        ...\n\n"
            "A whole-body 'try/except Exception' that routes through "
            "handle_error() and raises typer.Exit() also satisfies the check, "
            "but @command is preferred. A 'try' that catches only specific "
            "exception types is NOT sufficient — other exceptions still leak."
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


def test_scan_passes_command_with_catchall_try(tmp_path):
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
    assert find_unwrapped_commands(pkg_dir) == []


def test_scan_flags_partial_handler_command(tmp_path):
    # A try that catches only a specific exception type is not a catch-all.
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
