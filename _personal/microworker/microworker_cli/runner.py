"""The one place a site CLI is executed.

`run` never uses a shell, always captures both streams, and reports the two
non-exit outcomes (timeout, missing executable) as `RunnerError` so `discover`
can record them as an `error` envelope instead of crashing mid-run.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class RunnerError(Exception):
    """The command produced no exit status: it timed out or could not start."""


@dataclass(frozen=True)
class RunResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def run(argv: list[str], timeout: int) -> RunResult:
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(f"`{' '.join(argv)}` timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise RunnerError(f"`{argv[0]}` is not installed: {exc}") from exc
    return RunResult(
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
