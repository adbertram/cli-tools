"""Regression tests for shared console color/escape gating.

stdout carries DATA. The shared Rich console must never write ANSI styling or
terminal control/detection escape sequences into stdout when stdout is not a
genuine interactive terminal -- and must honor NO_COLOR / TERM=dumb even when
it is. Otherwise automation that pipes a CLI's JSON output into a parser
chokes on stray escape bytes.

The console is constructed at import time from the process's real ``sys.stdout``
and environment, so these behaviors are exercised in child processes whose
stdout is a pipe or a PTY, capturing the exact bytes written.
"""

import json
import os
import pty
import re
import subprocess
import sys

import pytest

from cli_tools_shared.output import (
    _color_disabled_by_env,
    _stdout_is_interactive_tty,
)

# Matches any ANSI escape: CSI/SGR (ESC [ ...) and OSC (ESC ] ...).
_ANSI_ESCAPE = re.compile(rb"\x1b[\[\]]")

# Child program: report TTY/terminal state on stderr, write a table to stdout.
_TABLE_CHILD = (
    "import sys\n"
    "from cli_tools_shared.output import console, print_table\n"
    "sys.stderr.write('ISATTY=%s IS_TERMINAL=%s\\n'"
    " % (sys.stdout.isatty(), console.is_terminal))\n"
    "print_table([{'a': 1, 'b': 2}])\n"
)

# Child program: write JSON to stdout via the shared print_json path.
_JSON_CHILD = (
    "from cli_tools_shared.output import print_json\n"
    "print_json({'page_id': 'abc', 'ok': True})\n"
)


def _run_in_pipe(child_code: str, extra_env: dict | None = None) -> bytes:
    """Run ``child_code`` with stdout connected to a pipe; return stdout bytes."""
    env = {**os.environ, **(extra_env or {})}
    result = subprocess.run(
        [sys.executable, "-c", child_code],
        capture_output=True,
        env=env,
        check=True,
    )
    return result.stdout


def _run_in_pty(
    child_code: str,
    extra_env: dict | None = None,
    *,
    env: dict | None = None,
) -> bytes:
    """Run ``child_code`` with stdout connected to a real PTY; return all bytes."""
    if extra_env is not None and env is not None:
        raise ValueError("Pass either extra_env or env, not both")
    captured = bytearray()
    child_env = dict(env) if env is not None else {**os.environ, **(extra_env or {})}
    pid, fd = pty.fork()
    if pid == 0:
        # Child process.
        os.execve(sys.executable, [sys.executable, "-c", child_code], child_env)
    while True:
        try:
            data = os.read(fd, 4096)
        except OSError:
            break
        if not data:
            break
        captured.extend(data)
    os.waitpid(pid, 0)
    return bytes(captured)


def test_color_disabled_by_env_honors_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("TERM", raising=False)
    assert _color_disabled_by_env() is True


def test_color_disabled_by_env_honors_term_dumb(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert _color_disabled_by_env() is True


def test_color_not_disabled_when_env_silent(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert _color_disabled_by_env() is False


def test_empty_no_color_does_not_disable(monkeypatch):
    # https://no-color.org: only a *non-empty* NO_COLOR disables color.
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert _color_disabled_by_env() is False


def test_stdout_interactive_detection_false_for_capsys(capsys):
    # Under capture, stdout is not a real TTY.
    assert _stdout_is_interactive_tty() is False
    capsys.readouterr()


def test_table_to_pipe_has_no_escape_bytes():
    out = _run_in_pipe(_TABLE_CHILD)
    assert b"ISATTY" not in out  # diagnostics go to stderr, not stdout
    assert not _ANSI_ESCAPE.search(out), repr(out[:120])


def test_table_to_pipe_with_force_color_still_clean():
    # FORCE_COLOR / TTY_COMPATIBLE must not fake a terminal on a non-TTY stream.
    out = _run_in_pipe(_TABLE_CHILD, {"FORCE_COLOR": "1", "TTY_COMPATIBLE": "1"})
    assert not _ANSI_ESCAPE.search(out), repr(out[:120])


def test_json_to_pipe_is_byte_clean_and_parses():
    out = _run_in_pipe(_JSON_CHILD, {"FORCE_COLOR": "1"})
    assert not _ANSI_ESCAPE.search(out), repr(out[:120])
    # The leading byte must be the JSON payload, never an escape prefix.
    assert out.lstrip().startswith(b"{"), repr(out[:40])
    assert json.loads(out) == {"page_id": "abc", "ok": True}


def test_table_to_pty_with_no_color_has_no_escape_bytes():
    # A genuine interactive terminal, but NO_COLOR opts out of styling.
    out = _run_in_pty(_TABLE_CHILD, {"NO_COLOR": "1"})
    assert not _ANSI_ESCAPE.search(out), repr(out[:160])


def test_table_to_pty_without_no_color_keeps_color():
    # Interactive terminal with color enabled still gets ANSI styling: the fix
    # must not break real interactive use.
    env = {k: v for k, v in os.environ.items()}
    env.pop("NO_COLOR", None)
    env["TERM"] = "xterm-256color"
    out = _run_in_pty(_TABLE_CHILD, env=env)
    assert _ANSI_ESCAPE.search(out), repr(out[:160])
