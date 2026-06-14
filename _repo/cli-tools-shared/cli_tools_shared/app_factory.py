"""App factory: standardised Typer app creation with global flags."""

import io
import os
import sys
from typing import Optional

import typer


def _reconfigure_stream(stream, stream_name: str):
    """Reconfigure a single stream to UTF-8, replacing it if reconfigure fails.

    Args:
        stream: The stream (sys.stdout or sys.stderr) to reconfigure.
        stream_name: "stdout" or "stderr" for setattr on sys.

    Raises:
        RuntimeError: If the stream cannot be reconfigured to UTF-8 by any method.
    """
    if not stream:
        raise RuntimeError(f"sys.{stream_name} is None — cannot set UTF-8 encoding")

    current_encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    if current_encoding == "utf8":
        return  # already UTF-8

    # Method 1: reconfigure() — available on Python 3.7+ TextIOWrapper
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")
        return

    # Method 2: wrap the underlying binary buffer in a new TextIOWrapper
    binary_buffer = getattr(stream, "buffer", None)
    if binary_buffer is None:
        raise RuntimeError(
            f"sys.{stream_name} has no reconfigure() and no buffer attribute — "
            f"cannot set UTF-8 encoding (current encoding: {stream.encoding!r})"
        )

    new_stream = io.TextIOWrapper(binary_buffer, encoding="utf-8", line_buffering=True)
    setattr(sys, stream_name, new_stream)


def _ensure_utf8_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8.

    On Windows, Python defaults to the console's legacy encoding (e.g. cp1252)
    for stdout/stderr. This causes UnicodeEncodeError when outputting characters
    outside that encoding (e.g. U+2192 right arrow, U+200B zero-width space).
    Reconfiguring to UTF-8 matches the behaviour of ``PYTHONIOENCODING=utf-8``
    and is safe on all platforms.

    Raises:
        RuntimeError: If either stream cannot be set to UTF-8.
    """
    _reconfigure_stream(sys.stdout, "stdout")
    _reconfigure_stream(sys.stderr, "stderr")


def _hoist_no_cache_flag() -> None:
    """Make the global ``--no-cache`` flag position-independent.

    ``--no-cache`` is defined as an app-level callback option (see
    :func:`create_app`), so Click only honours it when it appears *before* the
    subcommand. Agents naturally append it
    (``coursecraft demos get <id> --no-cache``), which Click then rejects with
    exit code 2 and empty stdout — making the documented uncached-readback
    verification path look broken. Move a standalone ``--no-cache`` token to the
    front of ``sys.argv`` so the existing callback handles it regardless of
    position.

    A ``--no-cache`` token is moved only when it is NOT immediately preceded by
    another option token (one starting with ``-``). In that ambiguous case it
    may be the *value* of a value-taking option (e.g. ``--name --no-cache``), so
    it is left untouched and parsed natively. This keeps the rewrite from ever
    stealing another option's value.
    """
    args = sys.argv[1:]
    if "--no-cache" not in args:
        return

    moved = False
    rebuilt = []
    for index, token in enumerate(args):
        if (
            token == "--no-cache"
            and not moved
            and (index == 0 or not args[index - 1].startswith("-"))
        ):
            moved = True  # drop here; re-inserted at the front below
            continue
        rebuilt.append(token)

    if moved:
        sys.argv = [sys.argv[0], "--no-cache", *rebuilt]


def create_app(
    name: str,
    help: str,
    version: str,
    *,
    cache_support: bool = True,
) -> typer.Typer:
    """Create a standardised Typer app with --version and optional --no-cache.

    Args:
        name: CLI tool name (e.g. "slack").
        help: Help text shown in the root ``--help``.
        version: Version string printed by ``--version``.
        cache_support: Add a ``--no-cache`` global flag (default True).

    Returns:
        Configured :class:`typer.Typer` instance.
    """
    app = typer.Typer(name=name, help=help, add_completion=True)

    @app.callback(invoke_without_command=True)
    def _callback(
        ctx: typer.Context,
        version_flag: Optional[bool] = typer.Option(
            None, "--version", "-v", help="Show version and exit", is_eager=True,
        ),
        no_cache: bool = typer.Option(
            False, "--no-cache", help="Bypass response cache",
            hidden=not cache_support,
        ),
    ):
        if no_cache and cache_support:
            os.environ["CACHE_ENABLED"] = "false"
        if version_flag:
            typer.echo(f"{name}-cli version {version}")
            raise typer.Exit()
        if ctx.invoked_subcommand is None:
            typer.echo(ctx.get_help())
            raise typer.Exit()

    # Normalise --no-cache position here, not only in run_app: most CLIs use a
    # ``main:app`` console-script entry point that calls ``app()`` directly and
    # never reaches run_app. create_app runs at import time — before ``app()``
    # parses sys.argv — so this is the one chokepoint shared by every entry
    # style. Idempotent: run_app calls it again for the ``main:main`` path.
    _hoist_no_cache_flag()

    return app


def run_app(app: typer.Typer, *, error_types=None) -> None:
    """Run *app* with standard error handling.

    Args:
        app: The Typer application to run.
        error_types: Exception class or tuple of classes treated as client
            errors (printed to stderr, exit 2).  Defaults to
            :class:`cli_tools_shared.exceptions.ClientError`.
    """
    _ensure_utf8_streams()
    _hoist_no_cache_flag()

    if error_types is None:
        from .exceptions import ClientError, ConfigError
        error_types = (ClientError, ConfigError)
    elif isinstance(error_types, type):
        error_types = (error_types,)

    try:
        app()
    except error_types as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(2)
    except KeyboardInterrupt:
        typer.echo("\nAborted!", err=True)
        sys.exit(130)
